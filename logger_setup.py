import logging
from logging.handlers import RotatingFileHandler
import sys
import traceback
import threading

# تنظیمات اصلی
LOG_FILE_NAME = "sonar_bot.log"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 Megabytes
BACKUP_COUNT = 5  # نگه داشتن 5 فایل قدیمی

def handle_exception(exc_type, exc_value, exc_traceback):
    """این تابع هر خطای مهلکی که باعث کرش برنامه شود را می‌گیرد"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("🔥 Uncaught exception (CRASH):", exc_info=(exc_type, exc_value, exc_traceback))

def handle_thread_exception(args):
    """این تابع خطاهای داخل Thread ها را می‌گیرد"""
    logging.critical("🧵 Uncaught exception in thread:", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

def setup_logger():
    """تنظیمات پیشرفته لاگینگ"""
    
    # فرمت دقیق: زمان | سطح | فایل:خط | پیام
    log_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(funcName)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. هندلر فایل (ذخیره با چرخش)
    file_handler = RotatingFileHandler(
        LOG_FILE_NAME, 
        maxBytes=MAX_LOG_SIZE, 
        backupCount=BACKUP_COUNT, 
        encoding='utf-8'
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)

    # 2. هندلر کنسول (رنگی برای دیباگ راحت‌تر در ترمینال)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)

    # تنظیمات ریشه (Root Logger)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # پاک کردن هندلرهای قبلی برای جلوگیری از تکرار
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # ✅ فعال‌سازی لاگ‌های وب‌سوکت (فقط ارورها و وارنینگ‌ها)
    # اگر می‌خواهید تمام پکت‌ها را ببینید، این را به DEBUG تغییر دهید (ولی لاگ خیلی شلوغ می‌شود)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # ✅ اتصال هوک‌های مدیریت خطای گلوبال
    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception

    logging.info("✅ Advanced Logging System Initialized.")
    return root_logger