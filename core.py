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
from datetime import datetime, timedelta, timezone
import matplotlib
# تنظیم بک‌اند نمودار برای اجرا در سرور بدون محیط گرافیکی
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# تنظیم لاگر مخصوص این ماژول
logger = logging.getLogger(__name__)

# ==============================================================================
# 📅 DATE & TIME UTILS (ابزارهای زمان و تاریخ)
# ==============================================================================
def get_tehran_datetime():
    """دریافت زمان فعلی تهران"""
    return datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)

def get_jalali_str():
    """دریافت تاریخ شمسی به صورت رشته فرمت شده"""
    tehran_now = get_tehran_datetime()
    j_date = jdatetime.datetime.fromgregorian(datetime=tehran_now)
    months = {
        1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر', 5: 'مرداد',
        6: 'شهریور', 7: 'مهر', 8: 'آبان', 9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'
    }
    return f"{j_date.day} {months[j_date.month]} {j_date.year} | {j_date.hour:02d}:{j_date.minute:02d}"

# ==============================================================================
# 🛠 HELPER UTILS (ابزارهای کمکی)
# ==============================================================================
def extract_safe_json(text):
    """استخراج هوشمند JSON از بین خروجی‌های متنی"""
    try:
        text = text.strip()
        if not text: return None
        
        if text.startswith('{') and text.endswith('}'):
            try: return json.loads(text)
            except: pass

        match = re.search(r'(\{.*\})', text, re.DOTALL) 
        if match:
            potential_json = match.group(1)
            try: return json.loads(potential_json)
            except:
                matches = re.findall(r'(\{.*?\})', text, re.DOTALL)
                if matches:
                    for m in reversed(matches):
                        try: return json.loads(m)
                        except: continue
        return None
    except:
        return None

# ==============================================================================
# 📊 PLOTTING (رسم نمودار)
# ==============================================================================
def generate_plot(server_name, stats):
    """تولید نمودار گرافیکی مصرف منابع"""
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
# 🧠 SERVER MONITOR CORE (هسته اصلی مانیتورینگ)
# ==============================================================================
class ServerMonitor:
    @staticmethod
    def get_ssh_client(ip, port, user, password):
        """ایجاد اتصال SSH"""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=port, username=user, password=password, timeout=10) # تایم‌اوت به ۱۰ افزایش یافت
        return client

    # --- 👇 توابع جدید اضافه شده برای سیستم ضد بلاک 👇 ---
    @staticmethod
    def get_bot_public_ip():
        """آی‌پی سرور خود ربات را می‌گیرد (برای وایت‌لیست کردن)"""
        try:
            # استفاده از ۳ سرویس مختلف برای اطمینان
            services = [
                "https://api.ipify.org",
                "https://ifconfig.me/ip",
                "https://icanhazip.com"
            ]
            for url in services:
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200:
                        return resp.text.strip()
                except: continue
            return None
        except:
            return None

    @staticmethod
    def whitelist_bot_ip(target_ip, port, user, password, bot_ip):
        """آی‌پی ربات را در سرور مقصد (Fail2Ban, UFW, IPTables) وایت‌لیست می‌کند"""
        if not bot_ip: return False, "Bot IP not found"

        # دستورات جامع برای جلوگیری از بلاک شدن
        # 1. اگر Fail2Ban نصب بود، آنبن و وایت‌لیست کن
        # 2. اگر UFW بود، اجازه بده
        # 3. در IPTables به عنوان قانون اول اضافه کن
        cmds = [
            f"if command -v fail2ban-client >/dev/null; then fail2ban-client set sshd unbanip {bot_ip} && fail2ban-client set sshd addignoreip {bot_ip}; fi",
            f"if command -v ufw >/dev/null; then ufw insert 1 allow from {bot_ip}; fi",
            f"iptables -I INPUT -s {bot_ip} -j ACCEPT || true"
        ]
        full_cmd = " && ".join(cmds)

        return ServerMonitor.run_remote_command(target_ip, port, user, password, full_cmd, timeout=20)
    # -----------------------------------------------------

    @staticmethod
    def format_full_global_results(data):
        """فرمت‌دهی نتایج پینگ جهانی"""
        if not isinstance(data, dict): return "❌ خطا در داده‌های دریافتی"
        flags = {
            'us': '🇺🇸', 'fr': '🇫🇷', 'de': '🇩🇪', 'nl': '🇳🇱', 'uk': '🇬🇧', 'ru': '🇷🇺',
            'ca': '🇨🇦', 'tr': '🇹🇷', 'ua': '🇺🇦', 'ir': '🇮🇷', 'ae': '🇦🇪', 'in': '🇮🇳',
            'cn': '🇨🇳', 'jp': '🇯🇵', 'kr': '🇰🇷', 'br': '🇧🇷', 'it': '🇮🇹', 'es': '🇪🇸',
            'au': '🇦🇺', 'sg': '🇸🇬', 'hk': '🇭🇰', 'ch': '🇨🇭', 'se': '🇸🇪', 'fi': '🇫🇮'
        }
        lines = []
        for node, result in data.items():
            if not result or not result[0]: continue
            country_code = node[:2].lower()
            flag = flags.get(country_code, '🌍')
            rtts = [p[1] * 1000 for p in result[0] if p[0] == "OK"]
            if rtts:
                avg = int(sum(rtts) / len(rtts))
                status = "🟢" if avg < 100 else "🟡" if avg < 200 else "🔴"
                lines.append(f"{flag} `{node.ljust(12)}` : {status} **{avg}ms**")
            else:
                lines.append(f"{flag} `{node.ljust(12)}` : ❌ Timeout")
        if not lines: return "⚠️ نتیجه‌ای دریافت نشد."
        lines.sort(key=lambda x: 0 if '🇮🇷' in x else 1)
        return "\n".join(lines)

    @staticmethod
    def get_datacenter_info(ip):
        """دریافت اطلاعات دیتاسنتر از API"""
        try:
            url = f"https://api.iplocation.net/?ip={ip}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('response_code') == '200':
                    return True, data
                else:
                    return False, data.get('response_message', 'API Error')
            else:
                return False, f"HTTP Error: {response.status_code}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def format_iran_ping_stats(check_host_data):
        # ... (بدون تغییر نسبت به کد شما) ...
        if not isinstance(check_host_data, dict):
            return "\n   ❌ خطا در دریافت پینگ ایران"
        node_map = {
            'ir1': 'Tehran (MCI)', 'ir-thr': 'Tehran (Datacenter)',
            'ir3': 'Karaj (Asiatech)', 'ir-krj': 'Karaj (Asiatech)',
            'ir4': 'Shiraz (ParsOnline)', 'ir-shz': 'Shiraz (ParsOnline)',
            'ir5': 'Mashhad (Ferdowsi)', 'ir-mhd': 'Mashhad (Ferdowsi)',
            'ir6': 'Esfahan (Mokhaberat)', 'ir-ifn': 'Esfahan (Mokhaberat)',
            'ir2': 'Tabriz (Shatel)', 'ir-tbz': 'Tabriz (IT)'
        }
        lines = []
        for node, result in check_host_data.items():
            node_key = node.split('.')[0].lower()
            if 'ir' not in node_key: continue
            city_name = node_map.get(node_key, 'Iran (Unknown)')
            if not result or not result[0]:
                lines.append(f"🔴 {city_name}: Timeout")
                continue
            rtts = [p[1] * 1000 for p in result[0] if p[0] == "OK"]
            if rtts:
                avg_ping = sum(rtts) / len(rtts)
                status_icon = "🟢" if avg_ping < 100 else "🟡" if avg_ping < 200 else "🔴"
                lines.append(f"{status_icon} {city_name}: {avg_ping:.0f} ms")
            else:
                lines.append(f"🔴 {city_name}: Packet Loss")
        if not lines: return "\n   ⚠️ هیچ نود فعالی در ایران یافت نشد."
        return "\n" + "\n".join([f"   {line}" for line in lines])

    @staticmethod
    def make_bar(percentage, length=10):
        """ساخت نوار وضعیت متنی"""
        if not isinstance(percentage, (int, float)):
            percentage = 0
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

    @staticmethod
    def check_full_stats(ip, port, user, password):
        """دریافت کامل وضعیت سرور (SSH) با مدیریت خطا برای پایداری"""
        client = None
        try:
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            
            commands = [
                "grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print usage}'",
                "free -m | awk 'NR==2{printf \"%.2f\", $3*100/$2 }'",
                "df -h / | awk 'NR==2{print $5}' | tr -d '%'",
                "uptime -p",
                "cat /proc/uptime | awk '{print $1}'",
                "cat /proc/net/dev | awk 'NR>2 {rx+=$2; tx+=$10} END {print rx+tx}'",
                "who | awk '{print $1 \"_\" $5}'"
            ]
            results = []
            for cmd in commands:
                try:
                    _, stdout, _ = client.exec_command(cmd, timeout=5) 
                    out = stdout.read().decode().strip()
                    results.append(out if out else "0")
                except:
                    results.append("0")
            client.close()

            try:
                uptime_sec = float(results[4]) if results[4].replace('.', '', 1).isdigit() else 0
            except ValueError: uptime_sec = 0
            
            traffic_bytes = int(results[5]) if results[5].isdigit() else 0
            traffic_gb = round(traffic_bytes / (1024 ** 3), 2)
            uptime_str = results[3].replace('up ', '').replace('weeks', 'w').replace('days', 'd').replace('hours','h').replace('minutes', 'm')

            try: cpu_val = round(float(results[0]), 1)
            except: cpu_val = 0.0
            try: ram_val = round(float(results[1]), 1)
            except: ram_val = 0.0
            try: disk_val = int(results[2])
            except: disk_val = 0
                
            who_data = results[6].split('\n') if results[6] != "0" else []
            current_sessions = [line.strip().replace('(', '').replace(')', '') for line in who_data if line.strip()]
            
            return {
                'status': 'Online', 'cpu': cpu_val, 'ram': ram_val, 'disk': disk_val,
                'uptime_str': uptime_str, 'uptime_sec': uptime_sec, 'traffic_gb': traffic_gb,
                'ssh_sessions': current_sessions,
                'error': None
            }
            
        except (paramiko.ssh_exception.SSHException, socket.error, Exception) as e:
            if client: client.close()
            err_msg = str(e)[:50] if "Connection reset" in str(e) or "Timed out" in str(e) else "SSH Error"
            return {'status': 'Offline', 'error': err_msg, 'uptime_sec': 0, 'traffic_gb': 0, 'ssh_sessions': []}
        
        finally:
            if client:
                try: client.close()
                except: pass

    @staticmethod
    def run_remote_command(ip, port, user, password, command, timeout=60):
        """اجرای دستور روی سرور ریموت"""
        client = None
        try:
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            full_cmd = f"export DEBIAN_FRONTEND=noninteractive; {command}"
            _, stdout, stderr = client.exec_command(full_cmd, timeout=timeout)
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            client.close()
            return True, (out + "\n" + err).strip()
        except Exception as e:
            if client:
                try:
                    client.close()
                except:
                    pass
            return False, str(e)

    # ... (بقیه متدهای کمکی مثل install_speedtest، run_speedtest و غیره را می‌توانید از فایل قبلی خود حفظ کنید اگر تغییری نکرده‌اند. برای جلوگیری از طولانی شدن پاسخ، آن‌ها را تکرار نکردم اما اگر لازم است بگویید تا فایل کامل را بفرستم) ...
    # برای اطمینان، بخش Check Host را هم می‌گذارم چون تغییر خاصی ندارد.
    @staticmethod
    def install_speedtest(ip, port, user, password):
        cmd = "sudo DEBIAN_FRONTEND=noninteractive apt-get update -y && (sudo DEBIAN_FRONTEND=noninteractive apt-get install -y speedtest-cli || (sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pip && pip3 install --upgrade speedtest-cli))"
        return ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=300)

    @staticmethod
    def run_speedtest(ip, port, user, password):
        return ServerMonitor.run_remote_command(ip, port, user, password, "speedtest-cli --simple", timeout=90)

    @staticmethod
    def clear_cache(ip, port, user, password):
        return ServerMonitor.run_remote_command(ip, port, user, password,
                                                "sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'", timeout=30)

    @staticmethod
    def clean_disk_space(ip, port, user, password):
        try:
            client = ServerMonitor.get_ssh_client(ip, port, user, password)
            _, stdout, _ = client.exec_command("df / --output=used | tail -n 1")
            start_used = int(stdout.read().decode().strip())
            commands = (
                "sudo DEBIAN_FRONTEND=noninteractive apt-get autoremove -y && "
                "sudo DEBIAN_FRONTEND=noninteractive apt-get clean && "
                "sudo journalctl --vacuum-time=3d && "
                "sudo rm -rf /var/log/*.gz /var/tmp/* /tmp/*"
            )
            chan = client.get_transport().open_session()
            chan.exec_command(commands)
            chan.recv_exit_status()
            _, stdout, _ = client.exec_command("df / --output=used | tail -n 1")
            end_used = int(stdout.read().decode().strip())
            client.close()
            freed_kb = start_used - end_used
            if freed_kb < 0: freed_kb = 0
            freed_mb = freed_kb / 1024
            return True, freed_mb
        except Exception as e:
            return False, str(e)

    @staticmethod
    def set_dns(ip, port, user, password, dns_type):
        dns_map = {
            "google": "nameserver 8.8.8.8\nnameserver 8.8.4.4",
            "cloudflare": "nameserver 1.1.1.1\nnameserver 1.0.0.1",
            "quad9": "nameserver 9.9.9.9\nnameserver 149.112.112.112",
            "opendns": "nameserver 208.67.222.222\nnameserver 208.67.220.220",
            "yandex": "nameserver 77.88.8.8\nnameserver 77.88.8.1",
            "comodo": "nameserver 8.26.56.26\nnameserver 8.20.247.20",
            "adguard": "nameserver 94.140.14.14\nnameserver 94.140.15.15",
            "shecan": "nameserver 178.22.122.100\nnameserver 185.51.200.2"
        }
        if dns_type not in dns_map: return False, "Invalid DNS"
        cmd = (
            f"sudo chattr -i /etc/resolv.conf 2>/dev/null; "
            f"echo '{dns_map[dns_type]}' | sudo tee /etc/resolv.conf; "
            f"sudo chattr +i /etc/resolv.conf 2>/dev/null"
        )
        return ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=30)

    @staticmethod
    def full_system_update(ip, port, user, password):
        cmd = (
            "sudo DEBIAN_FRONTEND=noninteractive apt-get update -y && "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y -o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold' && "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get autoremove -y && "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get clean"
        )
        return ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=900)

    @staticmethod
    def repo_update(ip, port, user, password):
        cmd = (
            "sudo DEBIAN_FRONTEND=noninteractive apt-get update -y && "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"
        )
        return ServerMonitor.run_remote_command(ip, port, user, password, cmd, timeout=300)

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
            'ir1': 'Tehran (MCI - همراه اول)', 'ir-mci': 'Tehran (MCI - همراه اول)',
            'ir-mtn': 'Tehran (Irancell - ایرانسل)', 'ir-tci': 'Tehran (Mokhaberat - مخابرات)',
            'ir-teh': 'Tehran (Afranet - افرانت)', 'ir-thr': 'Tehran (Datacenter)',
            'ir-afn': 'Tehran (Afranet - افرانت)', 'ir-hiw': 'Tehran (HiWeb - های‌وب)',
            'ir-mbn': 'Tehran (MobinNet - مبین‌نت)', 'ir-rsp': 'Tehran (Respina - رسپینا)',
            'ir-ztn': 'Tehran (Zitel - زیتل)', 'ir-pt': 'Tehran (Parstabar - پارس‌تبار)',
            'ir2': 'Tabriz (Shatel - شاتل)', 'ir-tbz': 'Tabriz (Shatel - شاتل)',
            'ir3': 'Karaj (Asiatech - آسیاتک)', 'ir-krj': 'Karaj (Asiatech - آسیاتک)',
            'ir4': 'Shiraz (ParsOnline - پارس‌آنلاین)', 'ir-shz': 'Shiraz (ParsOnline - پارس‌آنلاین)',
            'ir5': 'Mashhad (Ferdowsi - دانشگاه)', 'ir-mhd': 'Mashhad (HostIran - هاست ایران)',
            'ir6': 'Isfahan (Mokhaberat - مخابرات)', 'ir-ifn': 'Isfahan (Mokhaberat - مخابرات)',
            'ir-ahw': 'Ahvaz (Mokhaberat - اهواز)', 'ir-qom': 'Qom (Asiatech - قم)'
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
                location_display = f"🇮🇷 Iran, {city_name}"
                packets = result[0]
                total_packets = len(packets)
                ok_packets = 0
                rtts = []
                for p in packets:
                    if p[0] == "OK":
                        ok_packets += 1
                        rtts.append(p[1] * 1000)
                packet_stat = f"{ok_packets}/{total_packets}"
                if rtts:
                    ping_stat = f"{min(rtts):.0f} / {statistics.mean(rtts):.0f} / {max(rtts):.0f}"
                else:
                    ping_stat = "Timeout"
                line = f"`{location_display.ljust(17)}`|`{packet_stat}`| `{ping_stat}`"
                rows.append(line)
            except Exception as e:
                continue
        if not has_iran: return "⚠️ هیچ سرور فعالی از ایران یافت نشد."
        return "🌍 **Check-Host (Iran Only)**\n`Location         | Pkts| Latency (m/a/x)`\n" + "─" * 48 + "\n" + "\n".join(
            rows)