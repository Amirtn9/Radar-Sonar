import sqlite3
import threading
import logging
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

# ایمپورت تنظیمات از فایل جدید
from settings import DB_NAME, SUBSCRIPTION_PLANS, LOG_LEVEL

logger = logging.getLogger(__name__)
# اگر تنظیمات لاگینگ سراسری در bot.py انجام می‌شود، اینجا نیازی به basicConfig نیست
# اما برای اطمینان می‌توان استفاده کرد

# ==============================================================================
# 🗄️ DATABASE MANAGER CLASS
# ==============================================================================
class Database:
    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name
        self.lock = threading.RLock()
        self._configure_db()
        self.init_db()

    def _configure_db(self):
        """تنظیمات اولیه برای جلوگیری از قفل شدن"""
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute('PRAGMA journal_mode=WAL;')
                conn.execute('PRAGMA synchronous=NORMAL;')
                conn.execute('PRAGMA temp_store=MEMORY;')
                conn.execute('PRAGMA cache_size=-64000;') # 64MB cache
        except Exception as e:
            logger.error(f"DB Config Error: {e}")

    @contextmanager
    def get_connection(self):
        """مدیریت اتصال با تایم‌اوت بالا"""
        with self.lock:
            conn = sqlite3.connect(self.db_name, check_same_thread=False, timeout=90.0)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            except sqlite3.Error as e:
                logger.error(f"⚠️ Database Error: {e}")
            finally:
                conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, full_name TEXT, added_date TEXT, expiry_date TEXT, server_limit INTEGER DEFAULT 2, is_banned INTEGER DEFAULT 0, plan_type INTEGER DEFAULT 0, wallet_balance INTEGER DEFAULT 0, referral_count INTEGER DEFAULT 0, invited_by INTEGER DEFAULT 0)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT, UNIQUE(owner_id, name))''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS servers (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, group_id INTEGER, name TEXT, ip TEXT, port INTEGER, username TEXT, password TEXT, expiry_date TEXT, last_status TEXT DEFAULT 'Unknown', is_active INTEGER DEFAULT 1, location_type TEXT DEFAULT 'ext', created_at TEXT, is_monitor_node INTEGER DEFAULT 0, UNIQUE(owner_id, name))''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS settings (owner_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(owner_id, key))''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, chat_id TEXT, name TEXT, usage_type TEXT DEFAULT "all")''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS server_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, server_id INTEGER, cpu REAL, ram REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tunnel_configs (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, type TEXT, link TEXT, name TEXT, last_status TEXT DEFAULT 'Unknown', last_ping INTEGER DEFAULT 0, quality_score INTEGER DEFAULT 10, added_at TEXT, last_jitter INTEGER DEFAULT 0, last_speed_up TEXT DEFAULT '0 Mbps', last_speed_down TEXT DEFAULT '0 Mbps')''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT, amount INTEGER, method TEXT, status TEXT DEFAULT 'pending', created_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS temp_bonuses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bonus_limit INTEGER, created_at TEXT, expires_at TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS payment_methods (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, network TEXT, address TEXT, holder_name TEXT, is_active INTEGER DEFAULT 1)''')
            conn.commit()
            self.migrate()

    def migrate(self):
        with self.get_connection() as conn:
            cols = [
                ("servers", "expiry_date", "TEXT"),
                ("servers", "created_at", "TEXT"),
                ("servers", "location_type", "TEXT DEFAULT 'ext'"),
                ("servers", "is_monitor_node", "INTEGER DEFAULT 0"),
                ("users", "plan_type", "INTEGER DEFAULT 0"),
                ("users", "wallet_balance", "INTEGER DEFAULT 0"),
                ("users", "referral_count", "INTEGER DEFAULT 0"),
                ("users", "invited_by", "INTEGER DEFAULT 0"),
                ("channels", "usage_type", "TEXT DEFAULT 'all'"),
                ("tunnel_configs", "last_jitter", "INTEGER DEFAULT 0"),
                ("tunnel_configs", "last_speed_up", "TEXT DEFAULT '0 Mbps'"),
                ("tunnel_configs", "last_speed_down", "TEXT DEFAULT '0 Mbps'"),
                ("tunnel_configs", "sub_info", "TEXT DEFAULT '{}'"), # ✅ برای ذخیره حجم و انقضا
            ]
            for table, col, dtype in cols:
                try: conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
                except: pass
            conn.commit()

    # --- Helper Time Functions ---
    def get_tehran_datetime(self):
        return datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)

    # --- User Methods ---
    def add_or_update_user(self, user_id, full_name=None, invited_by=0, days=None):
        exist = self.get_user(user_id)
        now_str = self.get_tehran_datetime().strftime('%Y-%m-%d %H:%M:%S')
        default_days = days if days is not None else 60
        
        with self.get_connection() as conn:
            if exist:
                if full_name:
                    conn.execute('UPDATE users SET full_name = ? WHERE user_id = ?', (full_name, user_id))
                if days is not None:
                     try:
                        current_exp = datetime.strptime(exist['expiry_date'], '%Y-%m-%d %H:%M:%S')
                        if current_exp < datetime.now(): current_exp = datetime.now()
                        new_exp = (current_exp + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                        conn.execute('UPDATE users SET expiry_date = ? WHERE user_id = ?', (new_exp, user_id))
                     except: pass
            else:
                expiry = (self.get_tehran_datetime() + timedelta(days=default_days)).strftime('%Y-%m-%d %H:%M:%S')
                conn.execute('''
                    INSERT INTO users (user_id, full_name, added_date, expiry_date, server_limit, invited_by, wallet_balance, referral_count) 
                    VALUES (?, ?, ?, ?, 2, ?, 0, 0)
                ''', (user_id, full_name, now_str, expiry, invited_by))
            conn.commit()

    def get_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            return cursor.fetchone()

    def get_all_users(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users')
            return cursor.fetchall()
            
    def get_all_users_paginated(self, page=1, per_page=5):
        offset = (page - 1) * per_page
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users LIMIT ? OFFSET ?', (per_page, offset))
            users = cursor.fetchall()
            cursor.execute('SELECT COUNT(*) FROM users')
            total = cursor.fetchone()[0]
            return users, total

    def update_user_limit(self, user_id, limit):
        with self.get_connection() as conn:
            conn.execute('UPDATE users SET server_limit = ? WHERE user_id = ?', (limit, user_id))
            conn.commit()

    def toggle_ban_user(self, user_id):
        user = self.get_user(user_id)
        if not user: return 0
        new_state = 0 if user['is_banned'] else 1
        with self.get_connection() as conn:
            conn.execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (new_state, user_id))
            conn.commit()
        return new_state
        
    def toggle_user_plan(self, user_id):
        user = self.get_user(user_id)
        if not user: return 0 
        new_plan = 1 if user['plan_type'] == 0 else 0
        new_limit = 10 if new_plan == 1 else 2
        with self.get_connection() as conn:
            conn.execute('UPDATE users SET plan_type = ?, server_limit = ? WHERE user_id = ?', (new_plan, new_limit, user_id))
            conn.commit()
        return new_plan

    def remove_user(self, user_id):
        with self.get_connection() as conn:
            for t in ['users', 'servers', 'groups', 'channels']:
                col = 'user_id' if t == 'users' else 'owner_id'
                conn.execute(f'DELETE FROM {t} WHERE {col} = ?', (user_id,))
            conn.commit()

    def check_access(self, user_id, super_admin_id=0):
        if user_id == super_admin_id: return True, "Super Admin"
        user = self.get_user(user_id)
        if not user: return False, "کاربر یافت نشد"
        if user['is_banned']: return False, "حساب شما مسدود شده است ⛔️"
        try:
            expiry_dt = datetime.strptime(user['expiry_date'], '%Y-%m-%d %H:%M:%S')
            now_tehran_naive = self.get_tehran_datetime().replace(tzinfo=None)
            if now_tehran_naive > expiry_dt: return False, "اشتراک شما منقضی شده است 📅"
            return True, (expiry_dt - now_tehran_naive).days
        except: return False, "خطا در تاریخ"

    def delete_tunnel_config(self, cid, owner_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM tunnel_configs WHERE id = ? AND owner_id = ?', (cid, owner_id))
            conn.commit()

    # --- Server Methods ---
    def add_server(self, owner_id, group_id, data, super_admin_id=0):
        g_id = group_id if group_id != 0 else None
        user = self.get_user(owner_id)
        current_servers_list = self.get_all_user_servers(owner_id)
        current_count = len(current_servers_list)

        if user and owner_id != super_admin_id:
            if current_count >= user['server_limit']:
                raise Exception("Server Limit Reached")
        
        loc_type = data.get('location_type', 'ext')

        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if current_count == 0 and user['plan_type'] == 0:
                new_expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                conn.execute('UPDATE users SET expiry_date = ? WHERE user_id = ?', (new_expiry, owner_id))
            
            now_reg = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute(
                'INSERT INTO servers (owner_id, group_id, name, ip, port, username, password, expiry_date, location_type, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (owner_id, g_id, data['name'], data['ip'], data['port'], data['username'], data['password'], data.get('expiry_date'), loc_type, now_reg)
            )
            server_id = cursor.lastrowid
            conn.commit()
            return server_id

    def get_all_user_servers(self, owner_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM servers WHERE owner_id = ?', (owner_id,))
            return cursor.fetchall()
            
    def get_all_servers(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM servers')
            return cursor.fetchall()

    def get_servers_by_group(self, owner_id, group_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            sql = 'SELECT * FROM servers WHERE owner_id = ? AND group_id IS NULL' if group_id == 0 else 'SELECT * FROM servers WHERE owner_id = ? AND group_id = ?'
            cursor.execute(sql, (owner_id,) if group_id == 0 else (owner_id, group_id))
            return cursor.fetchall()

    def get_server_by_id(self, s_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM servers WHERE id = ?', (s_id,))
            return cursor.fetchone()

    def delete_server(self, s_id, owner_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM servers WHERE id = ? AND owner_id = ?', (s_id, owner_id))
            conn.commit()

    def update_status(self, s_id, status):
        with self.get_connection() as conn:
            conn.execute('UPDATE servers SET last_status = ? WHERE id = ?', (status, s_id))
            conn.commit()

    def update_server_expiry(self, s_id, new_date):
        with self.get_connection() as conn:
            conn.execute('UPDATE servers SET expiry_date = ? WHERE id = ?', (new_date, s_id))
            conn.commit()
            
    def toggle_server_active(self, s_id, current_state):
        new_state = 0 if current_state else 1
        with self.get_connection() as conn:
            conn.execute('UPDATE servers SET is_active = ? WHERE id = ?', (new_state, s_id))
            conn.commit()
        return new_state
        
    def is_monitor_active(self):
        with self.get_connection() as conn:
            res = conn.execute("SELECT id FROM servers WHERE is_monitor_node = 1 AND is_active = 1 LIMIT 1").fetchone()
            return True if res else False

    # --- Stats Methods ---
    def add_server_stat(self, server_id, cpu, ram):
        with self.get_connection() as conn:
            conn.execute('INSERT INTO server_stats (server_id, cpu, ram) VALUES (?, ?, ?)', (server_id, cpu, ram))
            conn.execute("DELETE FROM server_stats WHERE created_at < datetime('now', '-1 day')")
            conn.commit()

    def add_server_stats_batch(self, stats_list):
        if not stats_list: return
        with self.get_connection() as conn:
            conn.executemany(
                'INSERT INTO server_stats (server_id, cpu, ram) VALUES (?, ?, ?)',
                stats_list
            )
            conn.execute("DELETE FROM server_stats WHERE created_at < datetime('now', '-1 day')")
            conn.commit()

    def get_server_stats(self, server_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT cpu, ram, strftime('%H:%M', created_at, '+3 hours', '+30 minutes') as time_str 
                FROM server_stats 
                WHERE server_id = ? 
                ORDER BY created_at ASC
            ''', (server_id,))
            return cursor.fetchall()

    # --- Group Methods ---
    def add_group(self, owner_id, name):
        with self.get_connection() as conn:
            conn.execute('INSERT INTO groups (owner_id, name) VALUES (?,?)', (owner_id, name))
            conn.commit()

    def get_user_groups(self, owner_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM groups WHERE owner_id = ?', (owner_id,))
            return cursor.fetchall()

    def delete_group(self, group_id, owner_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM groups WHERE id = ? AND owner_id = ?', (group_id, owner_id))
            conn.execute('UPDATE servers SET group_id = NULL WHERE group_id = ? AND owner_id = ?', (group_id, owner_id)) 
            conn.commit()

    # --- Channel & Settings Methods ---
    def add_channel(self, owner_id, chat_id, name, usage_type='all'):
        with self.get_connection() as conn:
            conn.execute('INSERT INTO channels (owner_id, chat_id, name, usage_type) VALUES (?,?,?,?)', (owner_id, chat_id, name, usage_type))
            conn.commit()

    def get_user_channels(self, owner_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM channels WHERE owner_id = ?', (owner_id,))
            return cursor.fetchall()

    def delete_channel(self, c_id, owner_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM channels WHERE id = ? AND owner_id = ?', (c_id, owner_id))
            conn.commit()

    def set_setting(self, owner_id, key, value):
        with self.get_connection() as conn:
            conn.execute('REPLACE INTO settings (owner_id, key, value) VALUES (?, ?, ?)', (owner_id, key, str(value)))
            conn.commit()

    def get_setting(self, owner_id, key):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE owner_id = ? AND key = ?', (owner_id, key,))
            res = cursor.fetchone()
            return res['value'] if res else None

    # --- Payment Methods ---
    def create_payment(self, user_id, plan_type, amount, method):
        now = self.get_tehran_datetime().strftime('%Y-%m-%d %H:%M:%S')
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO payments (user_id, plan_type, amount, method, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, plan_type, amount, method, now)
            )
            conn.commit()
            return cursor.lastrowid

    def approve_payment(self, payment_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM payments WHERE id = ?', (payment_id,))
            pay = cursor.fetchone()
            
            if not pay or pay['status'] == 'approved': return False
            
            conn.execute("UPDATE payments SET status = 'approved' WHERE id = ?", (payment_id,))
            
            plan = SUBSCRIPTION_PLANS.get(pay['plan_type'])
            if plan:
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (pay['user_id'],))
                user = cursor.fetchone()
                
                try:
                    if user['expiry_date']:
                        current_exp = datetime.strptime(user['expiry_date'], '%Y-%m-%d %H:%M:%S')
                    else:
                        current_exp = datetime.now()
                        
                    if current_exp < datetime.now(): 
                        current_exp = datetime.now()
                except Exception as e:
                    logger.error(f"Date Parse Error in Payment: {e}")
                    current_exp = datetime.now()
                
                new_exp = (current_exp + timedelta(days=plan['days'])).strftime('%Y-%m-%d %H:%M:%S')
                p_type_code = 1 if pay['plan_type'] == 'bronze' else 2 if pay['plan_type'] == 'silver' else 3
                
                conn.execute('''
                    UPDATE users 
                    SET server_limit = ?, expiry_date = ?, plan_type = ? 
                    WHERE user_id = ?
                ''', (plan['limit'], new_exp, p_type_code, pay['user_id']))
                
            conn.commit()
            return pay['user_id'], plan['name']

    def add_payment_method(self, p_type, network, address, holder):
        with self.get_connection() as conn:
            conn.execute(
                'INSERT INTO payment_methods (type, network, address, holder_name) VALUES (?, ?, ?, ?)',
                (p_type, network, address, holder)
            )
            conn.commit()

    def get_payment_methods(self, p_type=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if p_type:
                cursor.execute('SELECT * FROM payment_methods WHERE type = ? AND is_active = 1', (p_type,))
            else:
                cursor.execute('SELECT * FROM payment_methods')
            return cursor.fetchall()

    def delete_payment_method(self, p_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM payment_methods WHERE id = ?', (p_id,))
            conn.commit()

    def apply_referral_reward(self, inviter_id):
        user = self.get_user(inviter_id)
        if not user: return False, 0, ""
        
        new_limit = user['server_limit'] + 1
        try:
            current_exp = datetime.strptime(user['expiry_date'], '%Y-%m-%d %H:%M:%S')
            if current_exp < datetime.now(): current_exp = datetime.now()
            new_exp = (current_exp + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
        except:
            new_exp = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')

        bonus_expiry = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with self.get_connection() as conn:
            conn.execute('''
                UPDATE users 
                SET server_limit = ?, expiry_date = ?, referral_count = referral_count + 1 
                WHERE user_id = ?
            ''', (new_limit, new_exp, inviter_id))
            
            conn.execute('''
                INSERT INTO temp_bonuses (user_id, bonus_limit, created_at, expires_at)
                VALUES (?, 1, ?, ?)
            ''', (inviter_id, now_str, bonus_expiry))
            
            conn.commit()
            
        return True, new_limit, new_exp