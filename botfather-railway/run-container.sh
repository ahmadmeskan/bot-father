#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  run-container.sh — اجرای ربات داخل کانتینر/دسکتاپ بدون systemd
#  (مثل: docker-ubuntu-desktop روی Railway، یا هر محیط Docker)
#
#  استفاده در ترمینال داخل دسکتاپ:
#      bash run-container.sh                        ← پیش‌زمینه (Ctrl+C توقف)
#      nohup bash run-container.sh > runner.log 2>&1 &   ← پایدار
#
#  venv می‌سازد، پکیج‌ها را نصب می‌کند، .env را چک می‌کند و اگر
#  ربات کرش کند خودش بعد از ۱۰ ثانیه دوباره اجرا می‌کند.
# ═══════════════════════════════════════════════════════════════
set -u
cd "$(dirname "$0")"

say() { echo "[runner] $(date '+%H:%M:%S') $*"; }

# ── پیش‌نیاز: git فقط اگر root هستیم و نصب نیست ──
if [ "$(id -u)" -eq 0 ] && ! command -v git >/dev/null 2>&1; then
    say "در حال نصب git ..."
    apt-get update -qq && apt-get install -y -qq git || true
fi

# ── venv ──
if [ ! -x venv/bin/python ]; then
    if ! python3 -m venv venv 2>/dev/null; then
        say "ماژول venv نصب نیست — در حال نصب python3-venv"
        if [ "$(id -u)" -eq 0 ]; then
            apt-get update -qq && apt-get install -y -qq python3-venv python3-pip
            python3 -m venv venv
        else
            say "❌ root نیستم و venv در دسترس نیست — دستی نصب کنید"
            exit 1
        fi
    fi
fi

# ── پکیج‌ها (اگر TgCrypto نصب نشد، بدون آن ادامه می‌دهیم — کندتر ولی سالم) ──
if ! ./venv/bin/pip install -q -r requirements.txt; then
    say "نصب کامل شکست خورد — ادامه بدون TgCrypto"
    grep -vi 'tgcrypto' requirements.txt > /tmp/req-lite.txt
    ./venv/bin/pip install -q -r /tmp/req-lite.txt
fi

# ── .env ──
if [ ! -f .env ]; then
    say "❌ فایل .env نیست. اجرا کنید:"
    say "   cp .env.example .env   و بعد   nano .env"
    exit 1
fi

# ── حلقه اجرا با ری‌استارت خودکار ──
say "🚀 شروع ربات (Ctrl+C = توقف)"
while true; do
    ./venv/bin/python main.py
    code=$?
    if [ "$code" -eq 0 ] || [ "$code" -eq 130 ]; then
        say "خروج تمیز (کد $code)"
        break
    fi
    say "💥 کرش (کد $code) — ری‌استارت تا ۱۰ ثانیه"
    sleep 10
done
