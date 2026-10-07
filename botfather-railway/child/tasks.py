"""وظیفه‌ی اجباری — مدل «تأیید عضویت + پنجره‌ی ۲ دقیقه‌ای».

مدل قبلی (پیام + تاخیر بدون تأیید) حذف شد؛ طبق درخواست صاحب ربات:
    • سر راه هر درخواست محتوا چک می‌شود: اگر کاربر در ۲ دقیقه‌ی اخیر
      وظیفه را تأیید کرده باشد، محتوا بدون هیچ چکِ دیگری ارسال می‌شود.
    • در غیر این صورت عضویت کاربر در «کانال خواسته» بررسی می‌شود:
        عضو بود → زمان تأیید (verified_at) ثبت و محتوا ارسال می‌شود.
        عضو نبود → پیام وظیفه با دکمه‌ی «✅ عضو شدم» نمایش داده می‌شود؛
        با زدن آن دکمه عضویت دوباره چک می‌شود (مسیر تأیید در runtime).
    • پنجره: از لحظه‌ی تأیید تا ۲ دقیقه، همه‌ی درخواست‌های بعدی آزادند؛
      بعد از آن وظیفه دوباره باید انجام شود.

تنظیمات (جدول settings):
    task_enabled      «1» = فعال
    task_channel      کانال خواسته (از پنل مادر؛ خالی = پیش‌فرض @HAJI_TAKAVAR_CH)
    task_text         متن سفارشی پیام (خالی = پیش‌فرض)
    task_completions  شمارنده‌ی مجموع تأییدها (آمار)

متغیرهای متن: {name} {id} {channel}

نکته: چکِ واقعی عضویت نیاز دارد ربات فرزند در کانالِ خواسته ادمین باشد.
"""
from __future__ import annotations

import compat  # noqa: F401  ← باید قبل از pyrogram ایمپورت شود

import html
import logging

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db

log = logging.getLogger("tasks")

# مدت اعتبار یک تأیید (میلی‌ثانیه)
TASK_WINDOW_MS = 2 * 60 * 1000

# کانال خواسته‌ی پیش‌فرض — قابل تغییر از پنل ربات مادر («📢 کانال خواسته»)؛
# اگر سازنده چیزی تنظیم نکرده باشد، همین کانال ملاک چک عضویت است.
DEFAULT_TASK_CHANNEL = "@HAJI_TAKAVAR_CH"

DEFAULT_TASK_TEXT = (
    "🤜 وظیفه اجباری\n\n"
    "برای دریافت فایل، ابتدا این خواسته انجام شود:\n"
    "🔹 {channel}"
)


def config(token: str) -> dict:
    channel = db.get_setting(token, "task_channel", "").strip()
    return {
        "enabled": db.get_setting(token, "task_enabled", "0") == "1",
        # کانال تنظیم‌نشده/خالی = پیش‌فرض (قابل تغییر از پنل مادر)
        "channel": channel or DEFAULT_TASK_CHANNEL,
        "text": db.get_setting(token, "task_text", "") or DEFAULT_TASK_TEXT,
    }


def is_active(token: str) -> bool:
    cfg = config(token)
    return bool(cfg["enabled"] and cfg["channel"])


def completions(token: str) -> int:
    """مجموع دفعات تأیید وظیفه (برای آمار پنل)."""
    return db.task_completions(token)


# ─────────────────────────────── پنجره‌ی تأیید
def verified_recently(token: str, user_id: int) -> bool:
    """آیا کاربر در ۲ دقیقه‌ی اخیر وظیفه را تأیید کرده است؟"""
    last = db.task_verified_at(token, user_id)
    return last > 0 and (db.now_ms() - last) < TASK_WINDOW_MS


def mark_verified(token: str, user_id: int) -> None:
    """ثبت زمان تأیید وظیفه + یک واحد به شمارنده‌ی آمار."""
    db.set_task_verified(token, user_id)


def seconds_left(token: str, user_id: int) -> int:
    """ثانیه‌ی باقی‌مانده از پنجره‌ی تأیید (۰ = پنجره بسته)."""
    last = db.task_verified_at(token, user_id)
    if last <= 0:
        return 0
    left_ms = TASK_WINDOW_MS - (db.now_ms() - last)
    return max(0, left_ms // 1000)


# ─────────────────────────────── پیام وظیفه
def render_text(token: str, user) -> str:
    cfg = config(token)
    # fix: {name} escape می‌شود تا نام‌های حاوی < یا & پیام وظیفه را نشکنند
    return (
        cfg["text"]
        .replace("{name}", html.escape(str(getattr(user, "first_name", "") or ""), quote=False))
        .replace("{id}", str(getattr(user, "id", "")))
        .replace("{channel}", cfg["channel"])
    )


def keyboard(channel: str) -> InlineKeyboardMarkup:
    """دکمه‌ی «عضو شدم» + لینک ورود به کانال (اگر یوزرنیم عمومی باشد)."""
    rows = []
    if channel and channel.startswith("@"):
        rows.append([InlineKeyboardButton(
            "📢 ورود به کانال", url=f"https://t.me/{channel[1:]}")])
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data="taskjoin")])
    return InlineKeyboardMarkup(rows)
