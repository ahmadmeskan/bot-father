#!/data/data/com.termux/files/usr/bin/bash
# start.sh — اجرای ربات در ترموکس با بررسی‌های اولیه
# استفاده:  bash start.sh

cd "$(dirname "$0")" || exit 1

echo "══════════════════════════════════════"
echo " 🤖 راه‌اندازی ربات‌ساز"
echo "══════════════════════════════════════"
echo "📂 پوشه: $(pwd)"
echo "🐍 پایتون: $(python --version 2>&1)"
echo

# --- ۱) بررسی وجود فایل .env ---
if [ ! -f .env ]; then
    echo "❌ فایل .env پیدا نشد."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "   یک نمونه ساختم. حالا آن را ویرایش کنید:"
        echo "   nano .env"
    fi
    exit 1
fi

# --- ۲) بررسی نصب بودن پکیج‌ها ---
python - <<'PY' || exit 1
import sys
from importlib.util import find_spec   # فقط وجود پکیج را چک می‌کند، ایمپورتش نمی‌کند
missing = []
for mod, pkg in (("pyrogram", "pyrogram"), ("dotenv", "python-dotenv")):
    if find_spec(mod) is None:
        missing.append(pkg)
if missing:
    print("❌ این پکیج‌ها نصب نیستند:", ", ".join(missing))
    print("   دستور نصب:  pip install " + " ".join(missing))
    sys.exit(1)
print("✅ پکیج‌های لازم نصب هستند.")
PY

# --- ۳) تست سلامت event loop (مشکل پایتون ۳.۱۴) ---
python - <<'PY' || exit 1
import sys
try:
    import compat, db
    db.init()
    from mother.bot import app
except Exception as e:
    print("❌ خطا هنگام بارگذاری پروژه:", type(e).__name__, e)
    sys.exit(1)

if app.loop is compat.LOOP:
    print("✅ تست event loop موفق بود — ربات پیام‌ها را دریافت خواهد کرد.")
else:
    print("❌ ناسازگاری event loop! ربات ساکت می‌ماند.")
    print("   → مطمئن شوید در main.py خط «import compat» اولین import است.")
    sys.exit(1)
PY

# --- ۴) تست جامع (اختیاری: bash start.sh --test) ---
if [ "$1" = "--test" ]; then
    echo
    echo "🧪 اجرای تست جامع..."
    python tests/test_all.py || { echo "❌ تست‌ها ناموفق بودند."; exit 1; }
    echo
fi

# --- ۵) جلوگیری از خوابیدن گوشی ---
command -v termux-wake-lock >/dev/null && termux-wake-lock && echo "🔒 wake-lock فعال شد."

echo
echo "🚀 در حال اجرای ربات... (برای توقف Ctrl+C)"
echo "══════════════════════════════════════"
python main.py
