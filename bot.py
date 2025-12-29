import logging
import json
import asyncio
import datetime as dt
import os
import fcntl
from telegram.ext import ApplicationBuilder, JobQueue
from logger_setup import setup_logger
from dispatcher import register_all_handlers
import cronjobs
import bot_logic  # برای دسترسی به ارور هندلر و توکن

# خواندن تنظیمات
try:
    with open('sonar_config.json', 'r') as f:
        config = json.load(f)
        TOKEN = config.get('bot_token')
except:
    print("❌ Config file not found!")
    TOKEN = None

# راه‌اندازی لاگر
logger = setup_logger()

def acquire_single_instance_lock() -> int:
    """Prevent running multiple bot instances on the same machine.

    Telegram polling (getUpdates) supports only one active consumer per bot token.
    If two processes run concurrently, Telegram returns `Conflict` and the bot becomes unstable.
    We use a simple OS file lock to guarantee single instance per host.
    """
    lock_path = os.getenv("SONAR_BOT_LOCK", "/run/sonar-bot.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Keep the message plain for journalctl readability
        print(f"Another sonar-bot instance is already running (lock: {lock_path}). Exiting.")
        raise SystemExit(0)
    return fd

def main():
    if not TOKEN:
        print("⛔️ Error: Token not set.")
        return

    lock_fd = acquire_single_instance_lock()

    print("🚀 SONAR ULTRA PRO RUNNING...")
    
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .job_queue(JobQueue())
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .concurrent_updates(True)
        .build()
    )
    
    # اضافه کردن ارور هندلر از فایل لاجیک
    app.add_error_handler(bot_logic.error_handler)

    # ✅ ثبت تمام هندلرها از فایل دیسپچر
    # این خط حیاتی است: تمام دکمه‌ها و دستورات اینجا لود می‌شوند
    register_all_handlers(app)

    # راه‌اندازی جاب‌ها (Job Queue)
    if app.job_queue:
        app.job_queue.run_once(cronjobs.system_startup_notification, when=2)
        app.job_queue.run_once(cronjobs.startup_whitelist_job, when=15)
        app.job_queue.run_once(cronjobs.send_startup_topic_test, when=10)
        app.job_queue.run_daily(cronjobs.check_expiry_job, time=dt.time(hour=8, minute=30, second=0))
        app.job_queue.run_repeating(cronjobs.auto_scheduler_job, interval=120, first=30)
        app.job_queue.run_repeating(cronjobs.global_monitor_job, interval=60, first=10)
        app.job_queue.run_repeating(cronjobs.monitor_tunnels_job, interval=60, first=20)
        app.job_queue.run_repeating(cronjobs.auto_update_subs_job, interval=43200, first=3600)
        app.job_queue.run_repeating(cronjobs.auto_backup_send_job, interval=3600, first=300)
        app.job_queue.run_repeating(cronjobs.check_bonus_expiry_job, interval=43200, first=600)
    else:
        logger.error("JobQueue not available.")

    try:
        app.run_polling(
            drop_pending_updates=True,
            close_loop=False,
        )
    finally:
        try:
            os.close(lock_fd)
        except Exception:
            pass

if __name__ == '__main__':
    main()