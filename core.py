import os
import json
import time
import logging
import statistics
import io
import re
import shlex
import socket
import requests
import paramiko
import jdatetime
import asyncio
from datetime import datetime, timedelta, timezone
import matplotlib
from cryptography.fernet import Fernet
from settings import KEY_FILE, AGENT_FILE_PATH, AGENT_PORT

# Centralized connection tuning (WS + SSH)
from connections_config import SSH_CONF, compute_backoff_delay, ssh_connect_kwargs

# Persistent WebSocket pool (keeps connections open + auto-reconnect)
from ws_client import GLOBAL_WS_POOL

# Attempt to import websockets (Critical for new agent)
try:
    import websockets
except ImportError:
    websockets = None

# Configure matplotlib backend
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# Configure logger
logger = logging.getLogger(__name__)

# ==============================================================================
# 📅 DATE & TIME UTILS
# ==============================================================================
def get_tehran_datetime():
    """Get current Tehran time"""
    return datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)

def get_jalali_str():
    """Get formatted Jalali date string"""
    tehran_now = get_tehran_datetime()
    j_date = jdatetime.datetime.fromgregorian(datetime=tehran_now)
    months = {
        1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر', 5: 'مرداد',
        6: 'شهریور', 7: 'مهر', 8: 'آبان', 9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'
    }
    return f"{j_date.day} {months[j_date.month]} {j_date.year} | {j_date.hour:02d}:{j_date.minute:02d}"

# ==============================================================================
# 🛠 HELPER UTILS
# ==============================================================================
def extract_safe_json(text):
    """Smart JSON extraction from text output"""
    try:
        text = text.strip()
        if not text: return None
        
        if text.startswith('{') and text.endswith('}'):
            try: return json.loads(text)
            except: pass

        matches = re.findall(r'(\{.*?\})', text, re.DOTALL)
        if matches:
            for m in reversed(matches):
                try: return json.loads(m)
                except: continue
        
        return None
    except:
        return None

# ==============================================================================
# 📊 PLOTTING
# ==============================================================================
def generate_plot(server_name, stats):
    """Generate resource usage plot"""
    if not stats: return None
    try:
        fig = Figure(figsize=(10, 5))
        ax = fig.add_subplot(111)

        times = [s['time_str'] for s in stats]
        cpus = [s['cpu'] for s in stats]
        rams = [s['ram'] for s in stats]

        ax.plot(times, cpus, label='CPU (%)', color='red', linewidth=2)
        ax.plot(times, rams, label='RAM (%)', color='blue', linewidth=2)

        ax.set_title(f"Server Monitor: {server_name} (Last 24h)")
        ax.set_xlabel('Time')
        ax.set_ylabel('Usage %')
        ax.set_ylim(0, 100)
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)

        if len(times) > 10:
            step = max(1, len(times) // 8)
            ax.set_xticks(range(0, len(times), step))
            ax.set_xticklabels(times[::step], rotation=45)

        fig.tight_layout()
        buf = io.BytesIO()
        FigureCanvasAgg(fig).print_png(buf)
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Plot error: {e}")
        return None

# ==============================================================================
# 🧠 SERVER MONITOR CORE
# ==============================================================================
class ServerMonitor:
    
    # ---------------------------------------------------------
    # 🔌 INTERNAL SSH HELPER (Fallback)
    # ---------------------------------------------------------
    @staticmethod
    def get_ssh_client(ip, port, user, password):
        """Create SSH connection (stable defaults).

        NOTE: SSH is fallback; WS is primary.
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kw = {}
        try:
            kw.update(ssh_connect_kwargs())
        except Exception:
            kw = {"timeout": 10, "banner_timeout": 10, "auth_timeout": 15}

        # Make behavior deterministic (no local ssh-agent surprises)
        client.connect(
            ip,
            port=int(port),
            username=str(user),
            password=str(password),
            look_for_keys=False,
            allow_agent=False,
            **kw,
        )

        # Keepalive helps long commands behind NAT
        try:
            t = client.get_transport()
            if t:
                t.set_keepalive(int(getattr(SSH_CONF, "keepalive_interval", 20)))
        except Exception:
            pass

        return client

    @staticmethod
    def _run_ssh_command(ip, port, user, password, command, timeout=60):
        """Raw SSH command execution with retry + backoff.

        This reduces false Offline reports caused by transient handshake/auth issues.
        """
        full_cmd = f"export DEBIAN_FRONTEND=noninteractive; {command}"

        max_attempts = max(1, int(getattr(SSH_CONF, "retries", 1)) + 1)
        last_err = None

        for attempt in range(max_attempts):
            client = None
            try:
                client = ServerMonitor.get_ssh_client(ip, port, user, password)
                _, stdout, stderr = client.exec_command(full_cmd, timeout=timeout)
                out = stdout.read().decode(errors="ignore").strip()
                err = stderr.read().decode(errors="ignore").strip()
                try:
                    client.close()
                except Exception:
                    pass
                return True, (out + "\n" + err).strip()
            except Exception as e:
                last_err = e
                if client:
                    try:
                        client.close()
                    except Exception:
                        pass

                if attempt >= max_attempts - 1:
                    break

                delay = 0.5
                try:
                    delay = compute_backoff_delay(
                        attempt,
                        base=getattr(SSH_CONF, "backoff_base", 0.35),
                        factor=getattr(SSH_CONF, "backoff_factor", 1.8),
                        cap=getattr(SSH_CONF, "backoff_cap", 6.0),
                        jitter=getattr(SSH_CONF, "backoff_jitter", 0.25),
                    )
                except Exception:
                    delay = 0.5

                logger.warning(
                    f"SSH error {ip}:{port} (attempt {attempt+1}/{max_attempts}) -> retry in {delay:.2f}s | {e}"
                )
                time.sleep(delay)

        return False, str(last_err)

    # ---------------------------------------------------------
    # 🚀 WEBSOCKET COMMAND RUNNER (New Architecture)
    # ---------------------------------------------------------
    @staticmethod
    async def ws_send_command(ip, ws_port, token, payload, timeout=10):
        """Send a command to the monitor agent using a persistent WebSocket.

        Important:
        - Connection is kept open (pooled) and reused.
        - Auto-reconnect is handled by the pool.
        - Token is sent once per connection (during connect).
        """
        if websockets is None:
            return {"error": "websockets lib missing"}

        try:
            return await GLOBAL_WS_POOL.request(
                ip=str(ip),
                port=int(ws_port),
                token=str(token or ""),
                payload=payload,
                timeout=float(timeout),
                # 2 retries = 3 total tries (improves stability on flaky networks)
                retries=2,
            )
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    async def run_remote_command(ip, port, user, password, command, timeout=60):
        """Execute command via WebSocket"""
        if websockets is None:
            return False, "Error: 'websockets' library is missing."

        # Always use the Agent Port for these commands
        target_ws_port = AGENT_PORT 

        payload = {
            "action": "run_cmd",
            "cmd": command,
            "timeout": timeout
        }
        
        res = await ServerMonitor.ws_send_command(ip, target_ws_port, password, payload, timeout + 5)
        
        if "error" in res:
            return False, f"Agent Error: {res['error']}"
        
        return res.get("ok", False), res.get("output", "")

    @staticmethod
    async def check_full_stats_ws(ip, ws_port, password):
        """Get stats via WebSocket"""
        payload = {"action": "get_stats"}
        res = await ServerMonitor.ws_send_command(ip, ws_port, password, payload)
        
        if "error" in res:
            return {'status': 'Offline', 'error': res['error'], 'uptime_sec': 0, 'traffic_gb': 0}
            
        return {
            'status': 'Online',
            'cpu': res.get('cpu', 0),
            'ram': res.get('ram', 0),
            'disk': res.get('disk', 0),
            'traffic_out': res.get('traffic_gb', 0),
            'uptime_str': res.get('uptime_str', 'N/A')
        }

    # ---------------------------------------------------------
    # 🛠 INSTALLATION & SETUP
    # ---------------------------------------------------------
    @staticmethod
    def install_agent_service(ip, port_ssh, user, password, ws_port):
        """Install agent via SSH"""
        try:
            client = ServerMonitor.get_ssh_client(ip, port_ssh, user, password)
            sftp = client.open_sftp()
            
            if not os.path.exists(AGENT_FILE_PATH):
                return False, "Local agent file not found"

            sftp.put(AGENT_FILE_PATH, "/root/monitor_agent.py")
            
            service_content = f"""[Unit]
Description=Sonar Monitor Agent
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 -u /root/monitor_agent.py {ws_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""
            with sftp.file("/etc/systemd/system/sonar-agent.service", "w") as f:
                f.write(service_content)
                
            sftp.close()
            
            cmds = (
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get update -y && "
                "apt-get install -y python3-pip && "
                "pip3 install websockets psutil && "
                "chmod +x /root/monitor_agent.py && "
                "systemctl daemon-reload && "
                "systemctl enable sonar-agent && "
                "systemctl restart sonar-agent && "
                f"ufw allow {ws_port}/tcp || true"
            )
            
            ok, out = ServerMonitor._run_ssh_command(ip, port_ssh, user, password, cmds, timeout=300)
            
            if ok:
                return True, "Agent Installed & Started"
            else:
                return False, out
                
        except Exception as e:
            return False, str(e)

    @staticmethod
    def get_bot_public_ip():
        """Get bot's public IP"""
        try:
            services = ["https://api.ipify.org", "https://ifconfig.me/ip"]
            for url in services:
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200:
                        return resp.text.strip()
                except: continue
            return None
        except: return None

    @staticmethod
    def whitelist_bot_ip(target_ip, port, user, password, bot_ip):
        """Whitelist bot IP via SSH"""
        cmds = [
            f"if command -v fail2ban-client >/dev/null; then fail2ban-client set sshd unbanip {bot_ip} || true; fi",
            f"if command -v ufw >/dev/null; then ufw insert 1 allow from {bot_ip}; fi",
            f"iptables -I INPUT -s {bot_ip} -j ACCEPT || true"
        ]
        full_cmd = " && ".join(cmds)
        return ServerMonitor._run_ssh_command(target_ip, port, user, password, full_cmd, timeout=20)

    # ---------------------------------------------------------
    # 📡 MONITORING & TOOLS (Legacy SSH Fallback & New Tools)
    # ---------------------------------------------------------
    @staticmethod
    def check_full_stats(ip, port, user, password):
        """Legacy SSH stats check"""
        try:
            cmd = "echo $(grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print usage}')_$(free -m | awk 'NR==2{printf \"%.2f\", $3*100/$2 }')"
            ok, out = ServerMonitor._run_ssh_command(ip, port, user, password, cmd, 10)
            if ok:
                parts = out.split('_')
                return {'status': 'Online', 'cpu': float(parts[0]), 'ram': float(parts[1])}
            else:
                return {'status': 'Offline', 'error': 'SSH Error'}
        except:
            return {'status': 'Offline', 'error': 'Connect Fail'}

    @staticmethod
    async def install_speedtest(ip, port, user, password):
        cmd = "apt-get install -y speedtest-cli || pip3 install speedtest-cli"
        return await ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=300)

    @staticmethod
    async def run_speedtest(ip, port, user, password):
        return await ServerMonitor.run_remote_command(ip, port, user, password, "speedtest-cli --simple", timeout=90)

    @staticmethod
    async def clear_cache(ip, port, user, password):
        return await ServerMonitor.run_remote_command(ip, port, user, password, "sync; echo 3 > /proc/sys/vm/drop_caches", timeout=10)

    @staticmethod
    async def clean_disk_space(ip, port, user, password):
        cmd = "apt-get autoremove -y && apt-get clean && journalctl --vacuum-time=1d && rm -rf /tmp/*"
        return await ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=60)

    @staticmethod
    async def set_dns(ip, port, user, password, dns_type):
        dns_map = {
            "google": "nameserver 8.8.8.8\nnameserver 8.8.4.4",
            "cloudflare": "nameserver 1.1.1.1\nnameserver 1.0.0.1",
            "shecan": "nameserver 178.22.122.100\nnameserver 185.51.200.2"
        }
        if dns_type not in dns_map: return False, "Invalid DNS"
        cmd = f"echo '{dns_map[dns_type]}' > /etc/resolv.conf"
        return await ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=10)

    @staticmethod
    async def full_system_update(ip, port, user, password):
        cmd = "apt-get update -y && apt-get upgrade -y"
        return await ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=600)

    @staticmethod
    async def repo_update(ip, port, user, password):
        cmd = "apt-get update -y"
        return await ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=120)

    # ---------------------------------------------------------
    # 🌍 GLOBAL PING & API TOOLS
    # ---------------------------------------------------------
    @staticmethod
    def check_host_api(target):
        try:
            headers = {'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'}
            url = f"https://check-host.net/check-ping?host={target}&max_nodes=50"
            req = requests.get(url, headers=headers, timeout=10)
            if req.status_code != 200: return False, f"API Error: {req.status_code}"
            request_id = req.json().get('request_id')
            result_url = f"https://check-host.net/check-result/{request_id}"
            poll_data = {}
            for _ in range(8):
                time.sleep(2.5)
                res_req = requests.get(result_url, headers=headers, timeout=10)
                poll_data = res_req.json()
                if isinstance(poll_data, dict):
                    completed = sum(1 for k, v in poll_data.items() if v)
                    if completed >= 10: break
            return True, poll_data
        except Exception as e:
            return False, str(e)
            
    @staticmethod
    def format_check_host_results(data):
        if not isinstance(data, dict): return "❌ داده نامعتبر"
        ir_city_map = {
            'ir1': 'Tehran (MCI)', 'ir-mci': 'Tehran (MCI)', 'ir-mtn': 'Tehran (Irancell)', 
            'ir-tci': 'Tehran (Mokhaberat)', 'ir-teh': 'Tehran (Afranet)', 'ir-thr': 'Tehran (DC)',
            'ir-afn': 'Tehran (Afranet)', 'ir-hiw': 'Tehran (HiWeb)', 'ir-mbn': 'Tehran (MobinNet)',
            'ir-rsp': 'Tehran (Respina)', 'ir-ztn': 'Tehran (Zitel)', 'ir-pt': 'Tehran (Parstabar)',
            'ir2': 'Tabriz (Shatel)', 'ir-tbz': 'Tabriz (Shatel)', 'ir3': 'Karaj (Asiatech)',
            'ir-krj': 'Karaj (Asiatech)', 'ir4': 'Shiraz (ParsOnline)', 'ir-shz': 'Shiraz (ParsOnline)',
            'ir5': 'Mashhad (Ferdowsi)', 'ir-mhd': 'Mashhad (HostIran)', 'ir6': 'Isfahan (Mokhaberat)',
            'ir-ifn': 'Isfahan (Mokhaberat)', 'ir-ahw': 'Ahvaz (Mokhaberat)', 'ir-qom': 'Qom (Asiatech)'
        }
        rows = []
        has_iran = False
        for node, result in data.items():
            if not result or not isinstance(result, list) or len(result) == 0 or not result[0]: continue
            try:
                if node[:2].lower() != 'ir': continue
                has_iran = True
                node_clean = node.split('.')[0].lower()
                city_name = "Tehran"
                for key, val in ir_city_map.items():
                    if key in node_clean:
                        city_name = val
                        break
                location_display = f"🇮🇷 {city_name}"
                packets = result[0]
                total_packets = len(packets)
                ok_packets = 0
                rtts = []
                for p in packets:
                    if p[0] == "OK":
                        ok_packets += 1
                        rtts.append(p[1] * 1000)
                if rtts:
                    ping_stat = f"{min(rtts):.0f}/{statistics.mean(rtts):.0f}/{max(rtts):.0f}"
                else:
                    ping_stat = "Timeout"
                line = f"`{location_display.ljust(15)}` | `{ping_stat}`"
                rows.append(line)
            except: continue
        if not has_iran: return "⚠️ هیچ سرور فعالی از ایران یافت نشد."
        return "🌍 **Check-Host (Iran)**\n`Location       | Latency (min/avg/max)`\n" + "─" * 45 + "\n" + "\n".join(rows)

    @staticmethod
    def format_iran_ping_stats(check_host_data):
        return ServerMonitor.format_check_host_results(check_host_data)

    @staticmethod
    def make_bar(percentage, length=10):
        if not isinstance(percentage, (int, float)): percentage = 0
        blocks = "▏▎▍▌▋▊▉█"
        if percentage < 0: percentage = 0
        if percentage > 100: percentage = 100
        full_blocks = int((percentage / 100) * length)
        remainder = (percentage / 100) * length - full_blocks
        idx = int(remainder * len(blocks))
        if idx >= len(blocks): idx = len(blocks) - 1
        bar = "█" * full_blocks
        if full_blocks < length: bar += blocks[idx] + " " * (length - full_blocks - 1)
        return bar

# ==============================================================================
# 🔐 SECURITY HELPER
# ==============================================================================
class Security:
    def __init__(self):
        if not os.path.exists(KEY_FILE):
            with open(KEY_FILE, 'wb') as f:
                f.write(Fernet.generate_key())
        with open(KEY_FILE, 'rb') as f:
            self.key = f.read()
        self.cipher = Fernet(self.key)

    def encrypt(self, txt):
        return self.cipher.encrypt(txt.encode()).decode()

    def decrypt(self, txt):
        try:
            return self.cipher.decrypt(txt.encode()).decode()
        except Exception as e:
            return ""

# Initialize global security instance
sec = Security()