"""media.py — مدیریت فایل‌های رسانه‌ای بین ربات مادر و ربات‌های فرزند.

⚠️ نکته‌ی کلیدی تلگرام:
    file_id مخصوص همان رباتی است که فایل را دریافت کرده.
    یعنی file_id ای که «ربات مادر» می‌گیرد، برای «ربات فرزند» بی‌اعتبار است
    و ارسال با آن خطای MEDIA_EMPTY / FILE_REFERENCE_INVALID می‌دهد.

راه‌حل:
    ۱) ربات مادر فایل را روی دیسک ذخیره می‌کند.
    ۲) ربات فرزند بار اول از روی دیسک آپلود می‌کند.
    ۳) file_id حاصل (که مال خودِ ربات فرزند است) کش می‌شود
       تا دفعات بعد بدون آپلود مجدد ارسال شود.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message

import config
import db

log = logging.getLogger("media")

MEDIA_DIR = config.BASE_DIR / "data" / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# انواع رسانه‌ای که پشتیبانی می‌شوند
KINDS = ("photo", "video", "document", "audio", "voice", "animation", "sticker")


def detect_kind(message: Message) -> str:
    """نوع محتوای پیام را تشخیص می‌دهد."""
    for kind in KINDS:
        if getattr(message, kind, None):
            return kind
    return "text"


def get_text(message: Message) -> str:
    """متن یا کپشن پیام را با حفظ قالب‌بندی (HTML) برمی‌گرداند."""
    if message.text:
        return message.text.html
    if message.caption:
        return message.caption.html
    return ""


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[-80:] if len(name) > 80 else name


# ── fix: پاک‌سازی فایل‌ها هنگام حذف دکمه/عکس/ربات — قبلاً رکوردهای دیتابیس
# پاک می‌شدند ولی فایل‌ها برای همیشه روی دیسک می‌ماندند (نشت فضای دیسک).
def unlink_media(path: str | None) -> bool:
    """حذف امن یک فایل رسانه‌ای؛ فقط فایل‌های داخل MEDIA_DIR پاک می‌شوند.

    خروجی: True اگر فایل واقعاً حذف شد.
    """
    if not path:
        return False
    try:
        p = Path(path)
        if not p.is_file():
            return False
        # هر دو طرف resolve می‌شوند؛ در غیر این صورت مسیرهای نام‌کوتاه
        # (ویندوز ~1) یا سیم‌لینک‌دار (macOS /tmp) با هم نمی‌گنجند
        if MEDIA_DIR.resolve() not in p.resolve().parents:
            log.warning("حذف رد شد — خارج از MEDIA_DIR است: %s", path)
            return False
        p.unlink()
        return True
    except OSError as e:
        log.warning("حذف فایل رسانه ناموفق: %s (%s)", path, e)
        return False


def delete_button_files(token: str, button_id: int) -> int:
    """فایل‌های رسانه‌ی یک دکمه (آیتم‌ها + مسیر قدیمی) را پاک می‌کند."""
    n = 0
    row = db.fetchone(
        "SELECT file_path FROM buttons WHERE token=? AND id=?", (token, button_id)
    )
    if row and row["file_path"] and unlink_media(row["file_path"]):
        n += 1
    for item in db.button_items(token, button_id):
        if unlink_media(item["file_path"]):
            n += 1
    return n


def delete_bot_files(token: str) -> int:
    """کل پوشه‌ی رسانه‌ی یک ربات را هنگام حذف ربات پاک می‌کند."""
    target = MEDIA_DIR / _safe_name(token.split(":")[0])
    if not target.is_dir():
        return 0
    # گارد: مطمئن شویم داخل MEDIA_DIR است
    if MEDIA_DIR.resolve() not in target.resolve().parents:
        return 0
    shutil.rmtree(target, ignore_errors=True)
    log.info("پوشه رسانه ربات حذف شد: %s", target)
    return 1


async def save_media(client: Client, message: Message, subdir: str) -> str | None:
    """رسانه‌ی پیام را روی دیسک ذخیره می‌کند و مسیر آن را برمی‌گرداند."""
    kind = detect_kind(message)
    if kind == "text":
        return None

    obj = getattr(message, kind)
    target_dir = MEDIA_DIR / _safe_name(subdir)
    target_dir.mkdir(parents=True, exist_ok=True)

    original = getattr(obj, "file_name", None)
    if original:
        filename = f"{obj.file_unique_id}_{_safe_name(original)}"
    else:
        ext = {"photo": ".jpg", "voice": ".ogg", "video": ".mp4",
               "animation": ".mp4", "audio": ".mp3", "sticker": ".webp"}.get(kind, ".bin")
        filename = f"{obj.file_unique_id}{ext}"

    dest = target_dir / filename
    try:
        path = await client.download_media(message, file_name=str(dest))
        if path:
            log.info("رسانه ذخیره شد: %s", path)
            return str(path)
    except Exception as e:  # noqa: BLE001
        log.error("دانلود رسانه ناموفق بود: %s", e)
    return None


async def send_content(
    client: Client,
    chat_id: int,
    kind: str,
    text: str = "",
    file_path: str | None = None,
    token: str | None = None,
    cache_key: str | None = None,
    reply_markup=None,
) -> Message | None:
    """محتوا را با کلاینت داده‌شده ارسال می‌کند (با کش file_id مخصوص همان ربات).

    reply_markup: اختیاری — برای دکمه‌های 👍/👎 زیر فایل‌ها.
    """
    if kind == "text" or not file_path:
        return await client.send_message(chat_id, text or "—",
                                         reply_markup=reply_markup)

    # ۱) اگر قبلاً همین ربات این فایل را فرستاده، از file_id کش‌شده استفاده کن
    cached = db.get_cached_file(token, cache_key) if token and cache_key else None
    source = cached or file_path

    if not cached and not os.path.exists(file_path):
        log.error("فایل روی دیسک نیست: %s", file_path)
        warn = "⚠️ فایل این بخش در دسترس نیست."
        return await client.send_message(
            chat_id, f"{text}\n\n{warn}" if text else warn,
            reply_markup=reply_markup,
        )

    senders = {
        "photo": client.send_photo,
        "video": client.send_video,
        "document": client.send_document,
        "audio": client.send_audio,
        "voice": client.send_voice,
        "animation": client.send_animation,
        "sticker": client.send_sticker,
    }
    send = senders.get(kind, client.send_document)

    kwargs: dict = {}
    if kind not in ("sticker", "voice"):
        kwargs["caption"] = text or None
        kwargs["parse_mode"] = ParseMode.HTML
    elif kind == "voice" and text:
        kwargs["caption"] = text
        kwargs["parse_mode"] = ParseMode.HTML
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup

    try:
        sent = await send(chat_id, source, **kwargs)
    except Exception as e:  # noqa: BLE001
        # اگر file_id کش‌شده باطل شده بود، یک بار از روی دیسک تلاش کن
        if cached:
            log.warning("file_id کش‌شده کار نکرد (%s) — آپلود مجدد از دیسک", e)
            db.clear_cached_file(token, cache_key)
            try:
                sent = await send(chat_id, file_path, **kwargs)
            except Exception as e2:  # noqa: BLE001
                log.error("ارسال رسانه ناموفق: %s", e2)
                return None
        else:
            log.error("ارسال رسانه ناموفق: %s", e)
            return None

    # ۲) file_id جدید (مخصوص همین ربات) را کش کن
    if token and cache_key and not cached:
        obj = getattr(sent, detect_kind(sent), None)
        if obj is not None and getattr(obj, "file_id", None):
            db.set_cached_file(token, cache_key, obj.file_id)

    return sent


async def build_payload(client: Client, message: Message, subdir: str) -> dict:
    """از یک پیام دریافتی، یک «بسته‌ی محتوا» می‌سازد که هر رباتی بتواند بفرستد."""
    kind = detect_kind(message)
    path = await save_media(client, message, subdir) if kind != "text" else None
    if kind != "text" and not path:
        kind = "text"  # اگر دانلود نشد، حداقل متن را بفرست
    return {"kind": kind, "text": get_text(message), "path": path}
