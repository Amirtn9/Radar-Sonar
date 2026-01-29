import sys
import os
import json
import time
import subprocess
import base64
import urllib.parse
import urllib.request
import zipfile
import re
import random
import socket
import logging
import math
import shlex
from datetime import datetime
import argparse
import signal

# ==============================================================================
# ⚙️ ADVANCED CONFIGURATION
# ==============================================================================
USER_HOME = os.path.expanduser("~")
WORK_DIR = os.path.join(USER_HOME, "xray_workspace")
XRAY_BIN = os.path.join(WORK_DIR, "xray")
LOG_FILE = os.path.join(USER_HOME, "agent_debug.log")

TEST_URL = "http://www.google.com/generate_204"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

if not os.path.exists(WORK_DIR):
    try: os.makedirs(WORK_DIR, mode=0o755)
    except: pass

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
)

def log_and_print(msg, level="info"):
    if level == "info": logging.info(msg)
    elif level == "error": logging.error(msg); sys.stderr.write(f"[ERROR] {msg}\n")

# ==============================================================================
# ⏰ TIME SYNC (CRITICAL FOR VMESS)
# ==============================================================================
def sync_system_time():
    """همگام‌سازی اجباری ساعت سیستم برای رفع خطای VMess"""
    try:
        # دریافت تاریخ دقیق از هدر گوگل (چون پورت NTP ممکن است بسته باشد)
        # این دستور تاریخ را از گوگل می‌گیرد و با دستور date ست می‌کند
        cmd = "date -s \"$(curl -sI --connect-timeout 5 https://google.com | grep -i '^date:' | sed 's/^[Dd]ate: //g')\""
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log_and_print(f"Time Sync Failed: {e}", "error")

# ==============================================================================
# 🛠 UTILITIES
# ==============================================================================
def get_free_port():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]
    except: return random.randint(20000, 30000)

def check_port_open(port, timeout=5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(('127.0.0.1', port)) == 0: return True
        time.sleep(0.2)
    return False

# ==============================================================================
# 📦 INSTALLATION MANAGER
# ==============================================================================
def install_xray():
    if os.path.exists(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK):
        try:
            subprocess.check_output([XRAY_BIN, "-version"], stderr=subprocess.STDOUT)
            return
        except:
            if os.path.exists(XRAY_BIN): os.remove(XRAY_BIN)

    log_and_print("Installing Xray Core...")
    zip_path = os.path.join(WORK_DIR, "xray.zip")
    
    # لینک کمکی (Backup Link) در صورت فیلتر بودن گیت‌هاب
    urls = [
        "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip",
        "https://mirror.ghproxy.com/https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    ]

    downloaded = False
    for url in urls:
        if downloaded: break
        try:
            safe_url = shlex.quote(url)
            safe_path = shlex.quote(zip_path)
            cmd = f"curl -L -k -o {safe_path} {safe_url} --connect-timeout 15 --max-time 600 --retry 2"
            subprocess.call(cmd, shell=True)
            
            if os.path.exists(zip_path) and os.path.getsize(zip_path) > 5 * 1024 * 1024:
                try:
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        if 'xray' in z.namelist(): downloaded = True
                except: pass
        except: pass

    if not downloaded and not os.path.exists(XRAY_BIN):
        log_and_print("CRITICAL: Failed to download Xray.", "error")
        sys.exit(1)

    try:
        if os.path.exists(zip_path):
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(WORK_DIR)
            os.remove(zip_path)
        
        os.chmod(XRAY_BIN, 0o755)
        
        # دانلود فایل‌های Geo
        geo_files = [
            (os.path.join(WORK_DIR, 'geoip.dat'), 'https://github.com/v2fly/geoip/releases/latest/download/geoip.dat'),
            (os.path.join(WORK_DIR, 'geosite.dat'), 'https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat')
        ]
        for f_path, url in geo_files:
            if not os.path.exists(f_path):
                subprocess.run(["curl", "-L", "-k", "-o", f_path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except Exception as e:
        log_and_print(f"Install Error: {e}", "error")
        sys.exit(1)

# ==============================================================================
# 🧩 PARSING LOGIC (Fixed for VMess/VLESS JSON Structure)
# ==============================================================================
def decode_base64(data):
    try:
        data = data.strip().replace('\n', '').replace('\r', '').replace(' ', '')
        missing_padding = len(data) % 4
        if missing_padding: data += '=' * (4 - missing_padding)
        data = data.replace('-', '+').replace('_', '/')
        return base64.b64decode(data).decode('utf-8', errors='ignore')
    except: return data

def parse_xray_config(link):
    """تبدیل لینک‌های vmess/vless به ساختار دقیق Xray JSON"""
    try:
        link = link.strip()
        if not link: return None

        # تمیزکاری لینک
        if link.startswith('"') and link.endswith('"'): link = link[1:-1]
        if link.startswith("'") and link.endswith("'"): link = link[1:-1]

        # 1. اگر کاربر JSON مستقیم فرستاده
        if link.startswith('{'):
            try:
                conf = json.loads(link)
                # پشتیبانی از فرمت‌های مختلف (کل کانفیگ یا فقط Outbound)
                if 'outbounds' in conf: return conf['outbounds'][0]
                if 'settings' in conf and 'protocol' in conf: return conf 
                return None
            except: return None

        # 2. پردازش VMess
        if link.startswith('vmess://'):
            try:
                b64 = link[8:]
                c = json.loads(decode_base64(b64))
                
                # ساختار پایه StreamSettings
                stream_settings = {
                    "network": c.get('net', 'tcp'),
                    "security": c.get('tls', 'none')
                }
                
                # تنظیمات WS
                if c.get('net') == 'ws':
                    stream_settings["wsSettings"] = {
                        "path": c.get('path', '/'),
                        "headers": {"Host": c.get('host', '')}
                    }
                
                # تنظیمات TCP HTTP (طبق نمونه شما)
                elif c.get('net') == 'tcp' and c.get('type') == 'http':
                    stream_settings["tcpSettings"] = {
                        "header": {
                            "type": "http",
                            "request": {
                                "headers": {
                                    "Host": [c.get('host', '')]
                                },
                                "path": [c.get('path', '/')]
                            }
                        }
                    }

                # تنظیمات TLS
                if c.get('tls') == 'tls':
                    stream_settings["tlsSettings"] = {
                        "serverName": c.get('sni') or c.get('host'),
                        "allowInsecure": True,
                        "fingerprint": c.get('fp', 'chrome')
                    }

                # ساختار نهایی مطابق Xray Outbound
                return {
                    "protocol": "vmess",
                    "settings": {
                        "vnext": [{
                            "address": c.get('add'),
                            "port": int(c.get('port')),
                            "users": [{
                                "id": c.get('id'),
                                "alterId": int(c.get('aid', 0)),
                                "security": "auto"
                            }]
                        }]
                    },
                    "streamSettings": stream_settings,
                    "tag": "proxy"
                }
            except: return None

        # 3. پردازش VLESS / Trojan
        if link.startswith(('vless://', 'trojan://')):
            try:
                parsed = urllib.parse.urlparse(link)
                q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                protocol = 'vless' if link.startswith('vless') else 'trojan'
                
                # استخراج پارامترها
                sni = q.get('sni', [parsed.hostname])[0]
                host = q.get('host', [''])[0]
                path = q.get('path', ['/'])[0]
                security = q.get('security', ['none'])[0]
                net_type = q.get('type', ['tcp'])[0]
                pbk = q.get('pbk', [''])[0]
                fp = q.get('fp', ['chrome'])[0]
                alpn = q.get('alpn', [''])[0]
                flow = q.get('flow', [''])[0]
                sid = q.get('sid', [''])[0]
                spx = q.get('spx', [''])[0]
                
                stream_settings = {
                    "network": net_type,
                    "security": security
                }

                # WS
                if net_type == 'ws':
                    stream_settings["wsSettings"] = {"path": path, "headers": {"Host": host}}
                
                # TCP HTTP
                elif net_type == 'tcp' and q.get('headerType', [''])[0] == 'http':
                     stream_settings["tcpSettings"] = {
                        "header": {
                            "type": "http",
                            "request": {"headers": {"Host": [host]}, "path": [path]}
                        }
                    }
                
                # GRPC
                elif net_type == 'grpc':
                    stream_settings["grpcSettings"] = {"serviceName": q.get('serviceName', [''])[0]}

                # TLS / Reality
                tls_settings = {"serverName": sni, "allowInsecure": True, "fingerprint": fp}
                if alpn: tls_settings['alpn'] = alpn.split(',')

                if security == 'tls':
                     stream_settings["tlsSettings"] = tls_settings
                elif security == 'reality':
                     stream_settings["realitySettings"] = {
                         "publicKey": pbk, "shortId": sid, "serverName": sni, 
                         "fingerprint": fp, "spiderX": spx
                     }

                return {
                    "protocol": protocol,
                    "settings": {
                        "vnext": [{
                            "address": parsed.hostname,
                            "port": parsed.port,
                            "users": [{
                                "id": parsed.username,
                                "password": parsed.username,
                                "encryption": "none",
                                "flow": flow
                            }]
                        }]
                    },
                    "streamSettings": stream_settings,
                    "tag": "proxy"
                }
            except: return None

        return None
    except: return None

# ==============================================================================
# 🚀 CORE TESTING LOGIC
# ==============================================================================
def test_config(outbound, dl_size_mb, config_name="Config"):
    local_port = get_free_port()
    config_file = os.path.join(WORK_DIR, f"config_{local_port}.json")
    
    # تنظیمات کامل Xray برای اجرا
    full_config = {
        "log": {"loglevel": "error"},
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
        "routing": {
            "domainStrategy": "IPOnDemand",
            "rules": [
                {"type": "field", "ip": ["geoip:private", "geoip:ir"], "outboundTag": "direct"}
            ]
        }
    }
    
    proc = None
    try:
        with open(config_file, 'w') as f:
            json.dump(full_config, f, indent=2)
            
        proc = subprocess.Popen([XRAY_BIN, "-c", config_file], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        if not check_port_open(local_port, timeout=4):
            return {"status": "Fail", "msg": "Core Failed Start", "score": 0}
            
        prox = f"socks5://127.0.0.1:{local_port}"
        
        # 1. PING & JITTER TEST
        pings = []
        success_count = 0
        total_probes = 5
        
        for _ in range(total_probes):
            try:
                curl_args = [
                    "curl", "-x", prox, "-s", "-k", "-A", USER_AGENT,
                    "-o", "/dev/null", "-w", "%{http_code} %{time_total}",
                    TEST_URL, "--connect-timeout", "3", "--max-time", "5"
                ]
                res = subprocess.run(curl_args, capture_output=True, text=True)
                parts = res.stdout.split()
                if len(parts) >= 2 and (parts[0] == "204" or parts[0] == "200"):
                    pings.append(float(parts[1]) * 1000)
                    success_count += 1
            except: pass
            time.sleep(0.2)
            
        if success_count == 0:
            return {"status": "Fail", "msg": "Timeout/Filtering", "score": 0}

        avg_ping = int(sum(pings) / len(pings))
        jitter = int(math.sqrt(sum([(x - avg_ping) ** 2 for x in pings]) / len(pings))) if len(pings) > 1 else 0

        # 2. SPEED TEST (Only if requested)
        dl_speed, ul_speed = 0.0, 0.0
        
        if dl_size_mb > 0.1:
            bytes_dl = int(dl_size_mb * 1024 * 1024)
            url_dl = f"https://speed.cloudflare.com/__down?bytes={bytes_dl}"
            cmd_dl = [
                "curl", "-L", "-k", "-x", prox, "-A", USER_AGENT, "-s",
                "-w", "%{speed_download}", "-o", "/dev/null", url_dl,
                "--connect-timeout", "5", "--max-time", "30"
            ]
            res_dl = subprocess.run(cmd_dl, capture_output=True, text=True)
            try: dl_speed = round(float(res_dl.stdout) / 1024 / 1024, 2)
            except: pass

            if dl_size_mb > 2.0:
                url_ul = "https://speed.cloudflare.com/__up"
                safe_prox = shlex.quote(prox)
                cmd_ul = f"dd if=/dev/zero bs=1000 count=1000 2>/dev/null | curl -L -k -x {safe_prox} -s -w '%{{speed_upload}}' -o /dev/null --upload-file - {url_ul} --connect-timeout 5 --max-time 20"
                res_ul = subprocess.run(cmd_ul, shell=True, capture_output=True, text=True)
                try: ul_speed = round(float(res_ul.stdout) / 1024 / 1024, 2)
                except: pass

        # 3. SCORING
        score = 10.0
        if avg_ping > 200: score -= (avg_ping - 200) / 100
        if jitter > 50: score -= (jitter / 50)
        if dl_size_mb > 0.1:
            if dl_speed < 0.5: score -= 3
            elif dl_speed < 2.0: score -= 1
            
        score = round(max(0.0, min(10.0, score)), 1)

        return {
            "status": "OK", "ping": avg_ping, "jitter": jitter,
            "down": dl_speed, "up": ul_speed, "score": score,
            "protocol": outbound.get('protocol', 'unknown'),
            "msg": "Connected"
        }

    except Exception as e:
        return {"status": "Fail", "msg": str(e), "score": 0}
    finally:
        if proc:
            try: proc.terminate(); proc.wait(timeout=1)
            except: proc.kill()
        if os.path.exists(config_file):
            try: os.remove(config_file)
            except: pass

# ==============================================================================
# 🏁 MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument("link", help="Config Link")
    parser.add_argument("size", nargs="?", default="0.5", help="DL Size MB")
    args = parser.parse_args()

    # ✅ STEP 1: Sync Time (Critical for VMess/Reality)
    sync_system_time()
    
    # ✅ STEP 2: Install Core
    install_xray()
    
    input_str = args.link
    try: dl_param = float(args.size)
    except: dl_param = 0.5

    # Check if subscription
    is_sub = input_str.startswith(('http://', 'https://')) and not any(p in input_str for p in ['vless://', 'vmess://', 'trojan://', 'ss://'])
    
    configs_to_test = []

    # -----------------------------------------------------------
    # اصلاح بخش پردازش سابسکریپشن برای استخراج User-Info
    # -----------------------------------------------------------
    if is_sub:
        try:
            req = urllib.request.Request(input_str, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as r:
                # 1. خواندن محتوا
                raw_content = r.read().decode('utf-8', errors='ignore')
                
                # 2. استخراج اطلاعات اشتراک (User-Info) از هدرها
                headers = r.info()
                user_info_header = headers.get('Subscription-Userinfo', '')
                profile_title = headers.get('Profile-Title', 'Unknown')
                
                sub_stats = {
                    "upload": 0, "download": 0, "total": 0, "expire": 0, "title": profile_title
                }
                
                if user_info_header:
                    # فرمت: upload=123; download=456; total=789; expire=123456
                    try:
                        info_parts = user_info_header.split(';')
                        for part in info_parts:
                            key, val = part.strip().split('=')
                            if key in sub_stats:
                                sub_stats[key] = int(val)
                    except: pass

                # 3. دیکد کردن کانفیگ‌ها
                try: decoded = decode_base64(raw_content)
                except: decoded = raw_content
                
                patterns = r'(vless://[^\s\n]+|vmess://[^\s\n]+|trojan://[^\s\n]+|ss://[^\s\n]+)'
                links = re.findall(patterns, decoded)
                
                for i, l in enumerate(links):
                    name = f"Config_{i+1}"
                    # تلاش برای استخراج نام از هشتگ
                    if '#' in l: 
                        try: name = urllib.parse.unquote(l.split('#')[-1]).strip()
                        except: pass
                    configs_to_test.append({"name": name, "link": l})
            
            # ارسال متا دیتا همراه با اطلاعات حجم
            print(json.dumps({
                "type": "meta", 
                "total": len(configs_to_test), 
                "sub_info": sub_stats # ✅ اضافه شده
            }, ensure_ascii=False), flush=True)

        except Exception as e:
            print(json.dumps({"status": "Fail", "msg": f"Sub Error: {e}"}))
            sys.exit(1)
    else:
        # اگر کاربر JSON فرستاده باشد، همینجا به عنوان لینک تلقی می‌شود
        # پارسر ما در parse_xray_config آن را هندل می‌کند
        configs_to_test.append({"name": "Single_Config", "link": input_str})

    for cfg in configs_to_test:
        outbound = parse_xray_config(cfg['link'])
        
        if outbound:
            res = test_config(outbound, dl_param, config_name=cfg['name'])
            res['type'] = 'result'
            res['name'] = cfg['name']
            res['link'] = cfg['link'] # لینک اصلی را برمی‌گردانیم
            print(json.dumps(res, ensure_ascii=False), flush=True)
        else:
            # اگر پارس نشد
            print(json.dumps({"type": "result", "name": cfg['name'], "status": "Fail", "msg": "Parse Failed"}, ensure_ascii=False), flush=True)