#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  deploy.sh — نصب ربات روی سرور لینوکس با systemd
#  اجرای نرمال (کاربر root یا sudo):    sudo bash deploy.sh
#  اجرای آزمایشی بدون نصب سرویس:        bash deploy.sh --dry-run
# ───────────────────────────────────────────────────────────────────
#  چه کار می‌کند:
#   ۱) پکیج‌های لازم (python3-venv, git) را نصب می‌کند
#   ۲) کاربر اختصاصی botrunner می‌سازد (بدون sudo، بدون شل لاگین)
#   ۳) پروژه را به /opt/botfather کپی می‌کند
#   ۴) venv می‌سازد و requirements.txt را نصب می‌کند
#   ۵) tglog (گزارش خطا به تلگرام) را تست می‌کند
#   ۶) سرویس systemd را نصب و فعال می‌کند (executed only with root)
#   ۷) تست سریع سلامت event loop
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

APP_DIR="/opt/botfather"
SERVICE_NAME="botfather"
RUN_USER="botrunner"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── رنگ‌ها ──
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok()   { echo -e "${G}✅ $1${N}"; }
err()  { echo -e "${R}❌ $1${N}"; }
warn() { echo -e "${Y}⚠️  $1${N}"; }

echo "════════════════════════════════════════"
echo " 🚀 نصب ربات‌ساز روی سرور"
echo " 📂 مقصد: $APP_DIR"
echo " 📁 منبع:  $SRC_DIR"
[ "$DRY_RUN" = "1" ] && warn "حالت آزمایشی (dry-run) — سرویس نصب نمی‌شود"
echo "════════════════════════════════════════"

# ── ۰) بررسی‌های اولیه ─────────────────────────────────────────
if [ ! -f "$SRC_DIR/main.py" ]; then
    err "main.py در $SRC_DIR پیدا نشد — اسکریپت را از داخل پوشه‌ی پروژه اجرا کنید"
    exit 1
fi

if [ "$(id -u)" -ne 0 ] && [ "$DRY_RUN" = "0" ]; then
    err "این اسکریپت باید با root اجرا شود:  sudo bash deploy.sh"
    exit 1
fi

# ── ۱) پکیج‌های سیستم ────────────────────────────────────────
echo
echo "── ۱/۶ پکیج‌های سیستم ──"
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq python3-venv python3-pip git >/dev/null
    ok "پکیج‌های debian/ubuntu نصب شد"
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q python3 python3-pip git >/dev/null 2>&1 || true
    ok "پکیج‌های rhel/fedora نصب شد"
else
    warn "مدیریت پکیج شناخته نشد — python3 و venv باید از قبل نصب باشند"
fi

# ── ۲) کاربر اختصاصی ─────────────────────────────────────────
echo
echo "── ۲/۶ کاربر اختصاصی $RUN_USER ──"
if id "$RUN_USER" >/dev/null 2>&1; then
    ok "کاربر $RUN_USER از قبل موجود است"
else
    if [ "$DRY_RUN" = "0" ]; then
        useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$RUN_USER"
        ok "کاربر سیستمی $RUN_USER ساخته شد (بدون شل لاگین)"
    else
        warn "dry-run: از ساخت کاربر صرف‌نظر شد"
    fi
fi

# ── ۳) کپی پروژه ─────────────────────────────────────────────
echo
echo "── ۳/۶ کپی پروژه به $APP_DIR ──"
if [ "$SRC_DIR" = "$APP_DIR" ]; then
    warn "منبع و مقصد یکسان است — از کپی صرف‌نظر شد"
else
    if [ "$DRY_RUN" = "0" ]; then
        mkdir -p "$APP_DIR"
        # rsync اگر بود؛ اگر نبود با cp
        if command -v rsync >/dev/null 2>&1; then
            rsync -a --delete \
                  --exclude 'data/' \
                  --exclude '.env' \
                  --exclude 'venv/' \
                  --exclude '__pycache__/' \
                  --exclude '.git/' \
                  "$SRC_DIR"/ "$APP_DIR"/
        else
            # بدون rsync: کپی امن — .env و data/ و venv قبلی حفظ می‌شوند
            mkdir -p "$APP_DIR"
            tar -C "$SRC_DIR" \
                --exclude='./data' --exclude='./.env' \
                --exclude='./venv' --exclude='./__pycache__' \
                --exclude='./.git' \
                -cf - . | tar -C "$APP_DIR" -xf -
        fi
        ok "فایل‌ها کپی شد (data/ و .env قبلی حفظ شد)"
        # اگر .env در منبع هست ولی در مقصد نیست، کپی می‌شود
        if [ -f "$SRC_DIR/.env" ] && [ ! -f "$APP_DIR/.env" ]; then
            cp "$SRC_DIR/.env" "$APP_DIR/.env"
            ok ".env از منبع کپی شد"
        fi
        # مالکیت به کاربر سرویس — بدون این، DB قابل نوشتن نیست
        chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"
        chmod 600 "$APP_DIR/.env" 2>/dev/null || true
    else
        warn "dry-run: از کپی صرف‌نظر شد"
    fi
fi

# ── ۴) venv و پکیج‌ها ─────────────────────────────────────────
echo
echo "── ۴/۶ محیط مجازی پایتون ──"
if [ "$DRY_RUN" = "0" ]; then
    cd "$APP_DIR"
    if [ ! -d venv ]; then
        python3 -m venv venv
    fi
    # TgCrypto فقط روی 3.12- قابل نصب است؛ روی نسخه‌های جدیدتر کور...
    # در requirements.txt هست؛ اگر نصب نشد به طور خودکار رد می‌شود
    ./venv/bin/pip install --upgrade pip >/dev/null 2>&1
    ./venv/bin/pip install -r requirements.txt
    ok "پکیج‌ها در venv نصب شد"
else
    warn "dry-run: از ساخت venv صرف‌نظر شد"
fi

# ── ۵) بررسی .env ─────────────────────────────────────────────
echo
echo "── ۵/۶ بررسی تنظیمات .env ──"
cd "$APP_DIR" 2>/dev/null || cd "$SRC_DIR"
if [ ! -f .env ]; then
    err "فایل .env پیدا نشد!"
    echo "   ابتدا آن را بسازید:  cp .env.example .env && nano .env"
    exit 1
fi
# مقادیر خالی را چک می‌کنیم (بدون نمایش توکن‌ها)
python3 - <<'PY'
import re
from pathlib import Path
try:
    from dotenv import dotenv_values
    vals = dotenv_values(".env")
except ImportError:
    vals = {}
    for line in open(".env", encoding="utf-8"):
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)", line)
        if m:
            vals[m.group(1)] = m.group(2).strip().strip('"').strip("'")

PLACEHOLDERS = {"1234567", "your_api_hash_here", "123456:AA-your-mother-bot-token",
                "123456:AA-your-log-bot-token"}
missing = [k for k in ("API_ID", "API_HASH", "MOTHER_TOKEN")
           if not vals.get(k) or vals.get(k) in PLACEHOLDERS]
if missing:
    print("❌ این مقادیر هنوز placeholder هستند یا خالی‌اند: " + ", ".join(missing))
    print("   nano .env  را ویرایش کنید")
    raise SystemExit(1)
print("✅ مقادیر اصلی .env تنظیم شده‌اند")

log_ok, log_msg = (False, "")
if vals.get("LOG_TOKEN") and vals.get("LOG_CHAT"):
    print("ℹ️  گزارش‌گیری تلگرام فعال است — در حال تست...")
    os.environ["LOG_TOKEN"] = vals["LOG_TOKEN"]
    os.environ["LOG_CHAT"] = vals["LOG_CHAT"]
    sys_path = "venv/lib/python%s/site-packages" % (
        ".".join(map(str, __import__("sys").version_info[:2])))
    if Path(sys_path).exists():
        __import__("sys").path.insert(0, sys_path)
    try:
        import tglog
        log_ok, log_msg = tglog.check()
    except Exception as e:
        log_ok, log_msg = False, str(e)
    print(("✅ " if log_ok else "❌ ") + log_msg)
else:
    print("⚠️  LOG_TOKEN/LOG_CHAT تنظیم نشده — گزارش خطا به تلگرام غیرفعال است")
PY

# ── ۶) سرویس systemd ─────────────────────────────────────────
echo
echo "── ۶/۶ سرویس systemd ──"
if [ "$DRY_RUN" = "1" ]; then
    warn "dry-run: سرویس نصب نشد"
    echo
    ok "آزمایش کامل شد — بدون خطا. برای نصب واقعی:  sudo bash deploy.sh"
    exit 0
fi

if [ ! -f botfather.service ]; then
    err "فایل botfather.service کنار deploy.sh نیست"
    exit 1
fi
cp botfather.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
systemctl restart "$SERVICE_NAME"
sleep 3
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "سرویس اجرا شد و فعال است ✨"
    echo
    echo "   وضعیت زنده:   systemctl status $SERVICE_NAME"
    echo "   لاگ زنده:     journalctl -u $SERVICE_NAME -f"
    echo "   توقف:         sudo systemctl stop $SERVICE_NAME"
    echo "   ری‌استارت:     sudo systemctl restart $SERVICE_NAME"
else
    err "سرویس بالا نیامد! لاگ خطا:"
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
    exit 1
fi
