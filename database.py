import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import threading
import logging
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

# Import settings
from settings import DB_CONFIG, SUBSCRIPTION_PLANS, SUPER_ADMIN_ID

logger = logging.getLogger(__name__)

class Database:
    """PostgreSQL access layer with a shared connection pool.

    IMPORTANT:
    - The project imports Database() in multiple modules. Creating multiple
      pools is unnecessary and can exhaust PostgreSQL connections.
    - We therefore implement a lightweight singleton: every Database() call
      returns the same instance and pool.
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # Avoid reinitializing the singleton
        if getattr(self, "_initialized", False):
            return
        self.db_config = DB_CONFIG
        self.lock = threading.RLock()
        
        # Connection Pool Configuration
        try:
            self.pool = psycopg2.pool.ThreadedConnectionPool(1, 60, **self.db_config)
        except Exception as e:
            logger.error(f"❌ Error creating connection pool: {e}")
            raise e

        self.init_db()
        self._initialized = True

    def _checkout_conn(self):
        """Get a healthy connection from pool (best-effort).

        psycopg2 pools don't validate connections; network hiccups can leave
        stale connections in the pool. We do a lightweight 'SELECT 1' probe
        to avoid random crashes in long-running systemd services.
        """
        last_err = None
        for _ in range(2):
            conn = None
            try:
                conn = self.pool.getconn()
                if conn is None or getattr(conn, 'closed', 1):
                    raise psycopg2.OperationalError('connection is closed')
                # Probe
                try:
                    with conn.cursor() as _c:
                        _c.execute('SELECT 1')
                except Exception as e:
                    last_err = e
                    try:
                        self.pool.putconn(conn, close=True)
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
                    conn = None
                    continue
                return conn
            except Exception as e:
                last_err = e
                if conn is not None:
                    try:
                        self.pool.putconn(conn, close=True)
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
        raise last_err if last_err else Exception('db_connection_failed')

    @contextmanager
    def get_connection(self):
        """Manage database connections using the pool"""
        conn = None
        cur = None
        bad_conn = False
        try:
            conn = self._checkout_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            yield conn, cur
        except psycopg2.Error as e:
            # Operational errors usually mean the connection is broken/stale.
            if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
                bad_conn = True
            logger.error(f"⚠️ Database Error: {e}")
            if conn: conn.rollback()
            raise e
        except Exception as e:
            logger.error(f"⚠️ General Error in DB Context: {e}")
            raise e
        finally:
            if conn:
                try: cur.close()
                except: pass
                try:
                    if bad_conn:
                        self.pool.putconn(conn, close=True)
                    else:
                        self.pool.putconn(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def execute(self, query, params=None, fetch=None):
        """Helper to execute a single query quickly.

        fetch: None | 'one' | 'all'
        """
        with self.get_connection() as (conn, cur):
            cur.execute(query, params)
            res = None
            if fetch == 'one':
                res = cur.fetchone()
            elif fetch == 'all':
                res = cur.fetchall()
            conn.commit()
            return res

    def init_db(self):
        """Initialize database schema"""
        with self.get_connection() as (conn, cur):
            # Users
            cur.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, 
                full_name TEXT, 
                added_date TEXT, 
                expiry_date TEXT, 
                server_limit INTEGER DEFAULT 2, 
                is_banned INTEGER DEFAULT 0, 
                plan_type INTEGER DEFAULT 0, 
                wallet_balance BIGINT DEFAULT 0, 
                referral_count INTEGER DEFAULT 0, 
                invited_by BIGINT DEFAULT 0
            )''')
            
            # Groups
            cur.execute('''CREATE TABLE IF NOT EXISTS groups (
                id SERIAL PRIMARY KEY, 
                owner_id BIGINT, 
                name TEXT, 
                UNIQUE(owner_id, name)
            )''')
            
            # Servers
            cur.execute('''CREATE TABLE IF NOT EXISTS servers (
                id SERIAL PRIMARY KEY, 
                owner_id BIGINT, 
                group_id INTEGER, 
                name TEXT, 
                ip TEXT, 
                port INTEGER, 
                username TEXT, 
                password TEXT, 
                expiry_date TEXT, 
                last_status TEXT DEFAULT 'Unknown', 
                is_active INTEGER DEFAULT 1, 
                location_type TEXT DEFAULT 'ext', 
                created_at TEXT, 
                is_monitor_node INTEGER DEFAULT 0, 
                UNIQUE(owner_id, name)
            )''')
            
            # Settings
            cur.execute('''CREATE TABLE IF NOT EXISTS settings (
                owner_id BIGINT, 
                key TEXT, 
                value TEXT, 
                PRIMARY KEY(owner_id, key)
            )''')
            
            # Channels
            cur.execute('''CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY, 
                owner_id BIGINT, 
                chat_id TEXT, 
                name TEXT, 
                usage_type TEXT DEFAULT 'all',
                topic_id INTEGER DEFAULT 0
            )''')
            
            # Server Stats
            cur.execute('''CREATE TABLE IF NOT EXISTS server_stats (
                id SERIAL PRIMARY KEY, 
                server_id INTEGER, 
                cpu REAL, 
                ram REAL, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Payments
            cur.execute('''CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY, 
                user_id BIGINT, 
                plan_type TEXT, 
                amount BIGINT, 
                method TEXT, 
                status TEXT DEFAULT 'pending', 
                created_at TEXT
            )''')
            
            # Temp Bonuses
            cur.execute('''CREATE TABLE IF NOT EXISTS temp_bonuses (
                id SERIAL PRIMARY KEY, 
                user_id BIGINT, 
                bonus_limit INTEGER, 
                created_at TEXT, 
                expires_at TEXT
            )''')
            
            # Payment Methods
            cur.execute('''CREATE TABLE IF NOT EXISTS payment_methods (
                id SERIAL PRIMARY KEY, 
                type TEXT, 
                network TEXT, 
                address TEXT, 
                holder_name TEXT, 
                is_active INTEGER DEFAULT 1
            )''')
            
            # Tunnel Configs
            cur.execute('''CREATE TABLE IF NOT EXISTS tunnel_configs (
                id SERIAL PRIMARY KEY, 
                owner_id BIGINT, 
                type TEXT, 
                link TEXT UNIQUE, 
                name TEXT, 
                last_status TEXT DEFAULT 'Unknown', 
                last_ping INTEGER DEFAULT 0, 
                quality_score INTEGER DEFAULT 10, 
                added_at TEXT, 
                last_jitter INTEGER DEFAULT 0, 
                last_speed_up TEXT DEFAULT '0 Mbps', 
                last_speed_down TEXT DEFAULT '0 Mbps',
                sub_info TEXT DEFAULT '{}'
            )''')
            
            conn.commit()

    # --- Helper Time Functions ---
    def get_tehran_datetime(self):
        return datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)

    # ==========================================================================
    # 📌 CRITICAL METHODS FOR BOT LOGIC & CRONJOBS
    # ==========================================================================
    
    def check_access(self, user_id, super_admin_id=None):
        """Validate user access based on ban status and expiry"""
        if super_admin_id is None:
            super_admin_id = SUPER_ADMIN_ID
        if user_id == super_admin_id:
            return True, "Super Admin"
        user = self.get_user(user_id)
        if not user: return False, "کاربر یافت نشد"
        if user['is_banned']: return False, "حساب شما مسدود شده است ⛔️"
        try:
            # Handle potential None expiry_date for permanent users
            if not user['expiry_date']: return True, "Unlimited"
            
            expiry_dt = datetime.strptime(user['expiry_date'], '%Y-%m-%d %H:%M:%S')
            now_tehran_naive = self.get_tehran_datetime().replace(tzinfo=None)
            
            if now_tehran_naive > expiry_dt: return False, "اشتراک شما منقضی شده است 📅"
            return True, (expiry_dt - now_tehran_naive).days
        except Exception as e:
            logger.error(f"Date check error for {user_id}: {e}")
            return False, "خطا در بررسی تاریخ"

    def get_active_servers(self):
        """Get all active servers for monitoring"""
        with self.get_connection() as (conn, cur):
            cur.execute("SELECT * FROM servers WHERE is_active = 1")
            return cur.fetchall()

    def get_near_expiry_services(self):
        """Get services expiring in 3 days"""
        target = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')
        with self.get_connection() as (conn, cur):
            cur.execute("SELECT * FROM servers WHERE expiry_date = %s AND is_active = 1", (target,))
            return cur.fetchall()

    def add_server_stats_batch(self, stats_list):
        """Batch insert server statistics"""
        if not stats_list: return
        with self.get_connection() as (conn, cur):
            cur.executemany(
                'INSERT INTO server_stats (server_id, cpu, ram) VALUES (%s, %s, %s)',
                stats_list
            )
            cur.execute("DELETE FROM server_stats WHERE created_at < NOW() - INTERVAL '1 day'")
            conn.commit()

    def is_monitor_active(self):
        """Check if a monitor node exists and is active"""
        with self.get_connection() as (conn, cur):
            cur.execute("SELECT id FROM servers WHERE is_monitor_node = 1 AND is_active = 1 LIMIT 1")
            return cur.fetchone() is not None

    # ==========================================================================
    # 👤 USER METHODS
    # ==========================================================================
    def get_user(self, user_id):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
            return cur.fetchone()

    def add_or_update_user(self, user_id, full_name=None, invited_by=0, days=None):
        exist = self.get_user(user_id)
        now_str = self.get_tehran_datetime().strftime('%Y-%m-%d %H:%M:%S')
        default_days = days if days is not None else 60
        
        with self.get_connection() as (conn, cur):
            if exist:
                if full_name:
                    cur.execute('UPDATE users SET full_name = %s WHERE user_id = %s', (full_name, user_id))
                
                if days is not None:
                    try:
                        current_exp_str = exist['expiry_date']
                        if current_exp_str:
                            current_exp = datetime.strptime(current_exp_str, '%Y-%m-%d %H:%M:%S')
                            if current_exp < datetime.now(): current_exp = datetime.now()
                        else:
                            current_exp = datetime.now()
                            
                        new_exp = (current_exp + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                        cur.execute('UPDATE users SET expiry_date = %s WHERE user_id = %s', (new_exp, user_id))
                    except: pass
            else:
                expiry = (self.get_tehran_datetime() + timedelta(days=default_days)).strftime('%Y-%m-%d %H:%M:%S')
                cur.execute('''
                    INSERT INTO users (user_id, full_name, added_date, expiry_date, server_limit, invited_by, wallet_balance, referral_count) 
                    VALUES (%s, %s, %s, %s, 2, %s, 0, 0)
                ''', (user_id, full_name, now_str, expiry, invited_by))
            conn.commit()

    def get_all_users(self):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM users')
            return cur.fetchall()
            
    def get_all_users_paginated(self, page=1, per_page=5):
        offset = (page - 1) * per_page
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM users LIMIT %s OFFSET %s', (per_page, offset))
            users = cur.fetchall()
            cur.execute('SELECT COUNT(*) FROM users')
            total = cur.fetchone()['count']
            return users, total

    def update_user_limit(self, user_id, limit):
        self.execute('UPDATE users SET server_limit = %s WHERE user_id = %s', (limit, user_id))

    def toggle_ban_user(self, user_id):
        user = self.get_user(user_id)
        if not user: return 0
        new_state = 0 if user['is_banned'] else 1
        self.execute('UPDATE users SET is_banned = %s WHERE user_id = %s', (new_state, user_id))
        return new_state
        
    def toggle_user_plan(self, user_id):
        user = self.get_user(user_id)
        if not user: return 0 
        new_plan = 1 if user['plan_type'] == 0 else 0
        new_limit = 10 if new_plan == 1 else 2
        self.execute('UPDATE users SET plan_type = %s, server_limit = %s WHERE user_id = %s', (new_plan, new_limit, user_id))
        return new_plan

    def remove_user(self, user_id):
        with self.get_connection() as (conn, cur):
            for t in ['users', 'servers', 'groups', 'channels']:
                col = 'user_id' if t == 'users' else 'owner_id'
                cur.execute(f'DELETE FROM {t} WHERE {col} = %s', (user_id,))
            conn.commit()

    # ==========================================================================
    # 🖥 SERVER METHODS
    # ==========================================================================
    def get_all_user_servers(self, owner_id):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM servers WHERE owner_id = %s ORDER BY id ASC', (owner_id,))
            return cur.fetchall()
            
    def get_all_servers(self):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM servers')
            return cur.fetchall()

    def get_server_by_id(self, sid):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM servers WHERE id = %s', (sid,))
            return cur.fetchone()

    def add_server(self, owner_id, group_id, data, super_admin_id=0):
        g_id = group_id if group_id != 0 else None
        user = self.get_user(owner_id)
        current = len(self.get_all_user_servers(owner_id))
        
        if user and owner_id != super_admin_id:
            if current >= user['server_limit']: 
                return -1 # Limit reached
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        loc = data.get('location_type', 'ext')
        
        with self.get_connection() as (conn, cur):
            try:
                cur.execute(
                    'INSERT INTO servers (owner_id, group_id, name, ip, port, username, password, expiry_date, location_type, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id', 
                    (owner_id, g_id, data['name'], data['ip'], data['port'], data['username'], data['password'], data.get('expiry_date'), loc, now)
                )
                server_id = cur.fetchone()['id']
                conn.commit()
                return server_id
            except psycopg2.IntegrityError:
                conn.rollback()
                return -2 # Duplicate name

    def delete_server(self, s_id, owner_id):
        self.execute('DELETE FROM servers WHERE id = %s AND owner_id = %s', (s_id, owner_id))

    def update_status(self, s_id, status):
        self.execute('UPDATE servers SET last_status = %s WHERE id = %s', (status, s_id))

    def update_server_expiry(self, s_id, new_date):
        self.execute('UPDATE servers SET expiry_date = %s WHERE id = %s', (new_date, s_id))

    def toggle_server_active(self, s_id, current_state):
        new_state = 0 if current_state else 1
        self.execute('UPDATE servers SET is_active = %s WHERE id = %s', (new_state, s_id))
        return new_state

    def get_servers_by_group(self, owner_id, group_id):
        with self.get_connection() as (conn, cur):
            sql = 'SELECT * FROM servers WHERE owner_id = %s AND group_id IS NULL' if group_id == 0 else 'SELECT * FROM servers WHERE owner_id = %s AND group_id = %s'
            cur.execute(sql, (owner_id,) if group_id == 0 else (owner_id, group_id))
            return cur.fetchall()

    # ==========================================================================
    # 📊 STATS & GROUP METHODS
    # ==========================================================================
    def add_server_stat(self, server_id, cpu, ram):
        with self.get_connection() as (conn, cur):
            cur.execute('INSERT INTO server_stats (server_id, cpu, ram) VALUES (%s, %s, %s)', (server_id, cpu, ram))
            conn.commit()

    def get_server_stats(self, server_id):
        with self.get_connection() as (conn, cur):
            cur.execute('''
                SELECT cpu, ram, to_char(created_at + INTERVAL '3 hours 30 minutes', 'HH24:MI') as time_str 
                FROM server_stats 
                WHERE server_id = %s 
                ORDER BY created_at ASC
            ''', (server_id,))
            return cur.fetchall()

    def add_group(self, owner_id, name):
        try:
            self.execute('INSERT INTO groups (owner_id, name) VALUES (%s,%s)', (owner_id, name))
            return True
        except psycopg2.IntegrityError: return False

    def get_user_groups(self, owner_id):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM groups WHERE owner_id = %s', (owner_id,))
            return cur.fetchall()

    def delete_group(self, group_id, owner_id):
        with self.get_connection() as (conn, cur):
            cur.execute('DELETE FROM groups WHERE id = %s AND owner_id = %s', (group_id, owner_id))
            cur.execute('UPDATE servers SET group_id = NULL WHERE group_id = %s AND owner_id = %s', (group_id, owner_id)) 
            conn.commit()

    # ==========================================================================
    # ⚙️ SETTINGS & CHANNELS
    # ==========================================================================
    def get_setting(self, owner_id, key):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT value FROM settings WHERE owner_id = %s AND key = %s', (owner_id, key))
            res = cur.fetchone()
            return res['value'] if res else None

    def set_setting(self, owner_id, key, value):
        with self.get_connection() as (conn, cur):
            cur.execute('''
                INSERT INTO settings (owner_id, key, value) VALUES (%s, %s, %s) 
                ON CONFLICT (owner_id, key) DO UPDATE SET value = EXCLUDED.value
            ''', (owner_id, key, str(value)))
            conn.commit()

    def get_user_channels(self, owner_id):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM channels WHERE owner_id = %s', (owner_id,))
            return cur.fetchall()

    def add_channel(self, owner_id, chat_id, name, usage_type='all', topic_id=0):
        with self.get_connection() as (conn, cur):
            cur.execute('DELETE FROM channels WHERE owner_id=%s AND usage_type=%s', (owner_id, usage_type))
            cur.execute('INSERT INTO channels (owner_id, chat_id, name, usage_type, topic_id) VALUES (%s,%s,%s,%s,%s)', (owner_id, chat_id, name, usage_type, topic_id))
            conn.commit()
            
    def delete_channel(self, c_id, owner_id):
        self.execute('DELETE FROM channels WHERE id = %s AND owner_id = %s', (c_id, owner_id))

    # ==========================================================================
    # 💳 PAYMENT & TUNNEL METHODS
    # ==========================================================================
    def get_payment_methods(self, p_type=None):
        with self.get_connection() as (conn, cur):
            if p_type: cur.execute('SELECT * FROM payment_methods WHERE type = %s AND is_active = 1', (p_type,))
            else: cur.execute('SELECT * FROM payment_methods')
            return cur.fetchall()
            
    def add_payment_method(self, p_type, network, address, holder):
        self.execute('INSERT INTO payment_methods (type, network, address, holder_name) VALUES (%s, %s, %s, %s)', (p_type, network, address, holder))

    def delete_payment_method(self, p_id):
        self.execute('DELETE FROM payment_methods WHERE id = %s', (p_id,))

    def create_payment(self, user_id, plan_type, amount, method):
        now = self.get_tehran_datetime().strftime('%Y-%m-%d %H:%M:%S')
        with self.get_connection() as (conn, cur):
            cur.execute(
                'INSERT INTO payments (user_id, plan_type, amount, method, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                (user_id, plan_type, amount, method, now)
            )
            pid = cur.fetchone()['id']
            conn.commit()
            return pid

    def approve_payment(self, payment_id):
        with self.get_connection() as (conn, cur):
            cur.execute('SELECT * FROM payments WHERE id = %s', (payment_id,))
            pay = cur.fetchone()
            if not pay or pay['status'] == 'approved': return False
            
            cur.execute("UPDATE payments SET status = 'approved' WHERE id = %s", (payment_id,))
            
            plan = SUBSCRIPTION_PLANS.get(pay['plan_type'])
            if plan:
                cur.execute('SELECT * FROM users WHERE user_id = %s', (pay['user_id'],))
                user = cur.fetchone()
                try:
                    current_exp_str = user['expiry_date']
                    if current_exp_str:
                        current_exp = datetime.strptime(current_exp_str, '%Y-%m-%d %H:%M:%S')
                        if current_exp < datetime.now(): current_exp = datetime.now()
                    else:
                        current_exp = datetime.now()
                except:
                    current_exp = datetime.now()
                
                new_exp = (current_exp + timedelta(days=plan['days'])).strftime('%Y-%m-%d %H:%M:%S')
                p_type_code = 1 if pay['plan_type'] == 'bronze' else 2 if pay['plan_type'] == 'silver' else 3
                
                cur.execute('''
                    UPDATE users 
                    SET server_limit = %s, expiry_date = %s, plan_type = %s 
                    WHERE user_id = %s
                ''', (plan['limit'], new_exp, p_type_code, pay['user_id']))
                
            conn.commit()
            return pay['user_id'], plan['name']

    def delete_tunnel_config(self, cid, owner_id):
        self.execute('DELETE FROM tunnel_configs WHERE id = %s AND owner_id = %s', (cid, owner_id))

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

        with self.get_connection() as (conn, cur):
            cur.execute('''
                UPDATE users 
                SET server_limit = %s, expiry_date = %s, referral_count = referral_count + 1 
                WHERE user_id = %s
            ''', (new_limit, new_exp, inviter_id))
            
            cur.execute('''
                INSERT INTO temp_bonuses (user_id, bonus_limit, created_at, expires_at)
                VALUES (%s, 1, %s, %s)
            ''', (inviter_id, now_str, bonus_expiry))
            conn.commit()
            
        return True, new_limit, new_exp