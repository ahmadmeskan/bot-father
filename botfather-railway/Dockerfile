# ربات‌ساز تلگرام — اجرای مستقیم روی Railway بدون دسکتاپ/VNC
# 3.10 چون TgCrypto ویل آماده دارد؛ روی 3.11 باید کامپایل شود و در slim شکست می‌خورد
FROM python:3.10-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# پکیج‌ها (لایه جدا برای cache سریع‌تر)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || \
    (grep -vi 'tgcrypto' requirements.txt > /tmp/req-lite.txt && \
     pip install --no-cache-dir -r /tmp/req-lite.txt)

# کد پروژه
COPY . .

# توکن‌ها را در پنل Railway → Variables تنظیم کنید:
# API_ID, API_HASH, MOTHER_TOKEN, ADMINS, LOG_TOKEN, LOG_CHAT
# اگر ربات کرش کند، خود کانتینر بعد از ۱۰ ثانیه دوباره اجرایش می‌کند
# (حداکثر ۱۰ بار؛ بیشتر از آن یعنی مشکل پایدار — لاگ Railway را ببینید)
CMD ["sh", "-c", "n=0; while true; do python main.py; c=$?; [ $c -eq 0 ] && break; n=$((n+1)); [ $n -ge 10 ] && echo 'DEPLOY FAILED: too many crashes' && break; echo \"[runner] crash code=$c, restart 10s ($n/10)\"; sleep 10; done"]
