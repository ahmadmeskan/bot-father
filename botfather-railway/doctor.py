"""doctor.py — عیب‌یاب ربات مادر.

اجرا:  python doctor.py
این اسکریپت مرحله‌به‌مرحله بررسی می‌کند چرا ربات به /start پاسخ نمی‌دهد.
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

import compat  # noqa: F401  ← قبل از pyrogram

import config
import db

OK, BAD, WARN = "✅", "❌", "⚠️ "


def api(method: str, token: str, timeout: int = 15) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def step(n: int, title: str) -> None:
    print(f"\n{'─' * 55}\n[{n}] {title}")


async def main() -> None:
    # ------------------------------------------------ ۱) کانفیگ
    step(1, "بررسی فایل .env")
    try:
        config.validate()
    except SystemExit as e:
        print(BAD, e)
        sys.exit(1)
    print(f"{OK} API_ID = {config.API_ID}")
    print(f"{OK} API_HASH = {config.API_HASH[:6]}...  (طول: {len(config.API_HASH)})")
    if len(config.API_HASH) != 32:
        print(f"{BAD} طول API_HASH باید ۳۲ کاراکتر باشد!")
    print(f"{OK} MOTHER_TOKEN = {config.MOTHER_TOKEN[:12]}...")
    print(f"{'✅' if config.ADMINS else '⚠️ '} ADMINS = {config.ADMINS or 'خالی'}")
    print(f"   FORCE_CHANNEL = {config.FORCE_CHANNEL or '—'}")

    # ------------------------------------------------ ۲) اتصال به تلگرام
    step(2, "اتصال ساده به Bot API (تست شبکه و توکن)")
    try:
        me = api("getMe", config.MOTHER_TOKEN)
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} به api.telegram.org وصل نشد: {e}")
        print("   → یعنی مشکل شبکه/فیلترینگ است، نه کد. از پروکسی/VPN استفاده کنید.")
        return
    if not me.get("ok"):
        print(f"{BAD} توکن نامعتبر: {me}")
        return
    u = me["result"]
    print(f"{OK} ربات مادر: @{u['username']} (id={u['id']})")

    # ------------------------------------------------ ۳) وبهوک (مهم‌ترین علت سکوت)
    step(3, "بررسی Webhook — شایع‌ترین دلیل بی‌پاسخ ماندن ربات")
    wh = api("getWebhookInfo", config.MOTHER_TOKEN)["result"]
    if wh.get("url"):
        print(f"{BAD} یک webhook فعال است: {wh['url']}")
        print("   تا وقتی webhook ست باشد، آپدیت‌ها به کد شما نمی‌رسند.")
        print("   در حال حذف آن...")
        r = api("deleteWebhook?drop_pending_updates=true", config.MOTHER_TOKEN)
        print(f"   {OK if r.get('ok') else BAD} deleteWebhook → {r.get('ok')}")
    else:
        print(f"{OK} webhook فعال نیست.")
    if wh.get("pending_update_count"):
        print(f"{WARN}{wh['pending_update_count']} آپدیت معلق وجود دارد "
              "(یعنی پیام‌ها رسیده ولی مصرف نشده‌اند).")

    # ------------------------------------------------ ۴) نشست تکراری
    step(4, "بررسی اجرای همزمان چند نسخه از ربات")
    print("   اگر جای دیگری (سرور، ترمینال دیگر) همین توکن در حال اجراست،")
    print("   آپدیت‌ها بین آن‌ها تقسیم می‌شود و ربات شما ساکت به نظر می‌رسد.")
    print("   در ترموکس بررسی کنید:  ps aux | grep main.py")

    # ------------------------------------------------ ۵) دیتابیس
    step(5, "بررسی دیتابیس")
    db.init()
    s = db.stats()
    print(f"{OK} فایل دیتابیس: {config.DB_PATH}")
    print(f"   ربات‌های ثبت‌شده: {s['bots']} | کاربران: {s['users']}")

    # ------------------------------------------------ ۶) تست زنده هندلرها
    step(6, "تست زنده — الان در تلگرام به ربات مادر /start بدهید")
    from pyrogram import Client, filters
    from pyrogram.handlers import MessageHandler, RawUpdateHandler

    app = Client(
        name="doctor",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.MOTHER_TOKEN,
        workdir=str(config.SESSIONS_DIR),
        in_memory=True,
    )
    got = {"raw": 0, "msg": 0}

    async def on_raw(client, update, users, chats):
        got["raw"] += 1
        print(f"   📡 آپدیت خام دریافت شد: {type(update).__name__}")

    async def on_msg(client, message):
        got["msg"] += 1
        print(f"   💬 پیام از {message.from_user.id}: {message.text!r}")
        await message.reply("✅ تست موفق بود — هندلرها کار می‌کنند.")

    app.add_handler(RawUpdateHandler(on_raw))
    app.add_handler(MessageHandler(on_msg, filters.private))

    await app.start()
    print(f"{OK} کلاینت Pyrogram متصل شد. ۴۵ ثانیه منتظر پیام شما هستم...")
    await asyncio.sleep(45)
    await app.stop()

    print(f"\n{'─' * 55}\nنتیجه: آپدیت خام = {got['raw']} | پیام = {got['msg']}")
    if got["msg"]:
        print(f"{OK} همه‌چیز سالم است. پس مشکل از main.py/هندلرهای شماست.")
        print("   → مطمئن شوید main.py را اجرا می‌کنید و لاگ خطایی چاپ نمی‌شود.")
    elif got["raw"]:
        print(f"{WARN}آپدیت می‌رسد ولی به هندلر پیام نمی‌رسد → مشکل فیلترها/نسخه Pyrogram.")
    else:
        print(f"{BAD} هیچ آپدیتی نرسید. محتمل‌ترین دلایل:")
        print("   • webhook فعال بوده (بالا حذف شد) → دوباره doctor.py را اجرا کنید")
        print("   • نسخه Pyrogram قدیمی است → pip install -U kurigram")
        print("   • نسخه دیگری از همین توکن جای دیگری در حال اجراست")
        print("   • API_ID/API_HASH متعلق به حساب دیگری است یا اشتباه است")


def check_task_mode() -> None:
    """گزارش وضعیت وظیفه اجباری (نسخه‌ی جدید بدون تأیید ری‌اکشن)."""
    print(f"\n{'─' * 55}\n🤜 وظیفه اجباری:")
    print(f"{OK} مدل جدید «پیام + تاخیر» فعال است — نیازی به ادمین‌بودن ربات")
    print("   در کانالِ وظیفه نیست و هیچ دسترسی خاصی لازم ندارد.")
    print("   پیام هر ۲۴ ساعت برای هر کاربر نمایش داده می‌شود و بعد از")
    print("   تاخیرِ قابل‌تنظیم (پیش‌فرض ۱۵ ثانیه) فایل ارسال می‌شود.")


if __name__ == "__main__":
    check_task_mode()
    compat.run(main())
