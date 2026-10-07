"""تنظیمات پروژه — از فایل .env خوانده می‌شود."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- اطلاعات API تلگرام (از my.telegram.org) ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# --- توکن ربات مادر (از @BotFather) ---
MOTHER_TOKEN = os.getenv("MOTHER_TOKEN", "")

# --- ادمین‌های ربات مادر (آیدی عددی، با کاما جدا شود) ---
ADMINS = [int(x) for x in os.getenv("ADMINS", "").replace(" ", "").split(",") if x]

# --- کانال اجباری برای استفاده از ربات مادر (اختیاری، مثل @mychannel) ---
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL", "").strip()

# --- محدودیت تعداد ربات برای هر کاربر ---
MAX_BOTS_PER_USER = int(os.getenv("MAX_BOTS_PER_USER", "3"))

DB_PATH = BASE_DIR / "data" / "botfather.db"
SESSIONS_DIR = BASE_DIR / "data" / "sessions"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def validate() -> None:
    missing = []
    if not API_ID:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    if not MOTHER_TOKEN:
        missing.append("MOTHER_TOKEN")
    if missing:
        raise SystemExit(
            "❌ مقادیر زیر در فایل .env تنظیم نشده‌اند: " + ", ".join(missing)
        )
