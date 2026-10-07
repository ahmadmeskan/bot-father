"""زیرمجموعه‌گیری — مدل توکن (استخر کلی، بدون گره‌خوردن به دکمه).

هر کاربرِ دعوت‌شده با لینک عمومی ربات:
    https://t.me/<bot_username>?start=ref<user_id>
یک توکن مصرف‌نشده به استخرِ کلی دعوت‌کننده اضافه می‌کند.

قواعد مدل توکن (طبق درخواست صاحب ربات):
    • توکن‌ها به هیچ دکمه‌ای گره نمی‌خورند؛ در استخر کلی کاربر می‌مانند.
    • هر دکمه‌ی قفل‌دار «required_referrals» (ستون ref_count؛ ۰ = تعداد
      پیش‌فرض پنل) دارد. با زدن دکمه:
        - unused ≥ required → دکمه فوراً باز می‌شود و دقیقاً required
          توکن (قدیمی‌ترین‌ها) می‌سوزد (used=1؛ بازگشت‌پذیر نیست).
        - unused < required → پیام «در انتظار» با لینک دعوت نمایش داده
          می‌شود و هیچ توکنی نمی‌سوزد.
    • دکمه‌ای که یک بار با توکن باز شده، برای همان کاربر باز می‌ماند
      («برگشت به دکمه قبلی = ادامه از همان‌جا») و دیگر توکن نمی‌سوزد.
    • کاربر فقط شمارش کلی زیرمجموعه‌هایش را می‌بیند؛ تفکیک
      مصرف‌شده/مصرف‌نشده فقط در پنل مالک (ربات مادر) نشان داده می‌شود.
    • «کنسل کردن» فقط پیام انتظار را می‌بندد؛ توکنی نمی‌سوزد و چیزی
      قفل نمی‌شود. انتخاب دکمه‌ی جدید هم همین‌قدر بی‌هزینه است و
      پیام انتظار قبلی را خودکار می‌بندد (تعویض دکمه).

کلید «ref_enabled» در پنل، کلیدِ اصلی (master) سیستم است.

تنظیمات (در جدول settings):
    ref_enabled    «1» = کلید اصلی فعال
    ref_count      تعداد پیش‌فرض (برای دکمه‌هایی که تعداد جداگانه ندارند)
    ref_text       متن پیام (خالی = پیش‌فرض)
    ref_photo_path مسیر عکس روی دیسک (خالی = بدون عکس)

ستون‌های دکمه (جدول buttons):
    ref_req        «1» = این دکمه به توکن نیاز دارد
    ref_count      required_referrals همین دکمه (۰ = تعداد پیش‌فرض)

متغیرهای متن: {name} {id} {link} {count} {done} {left} {button}
"""
from __future__ import annotations

import compat  # noqa: F401  ← باید قبل از pyrogram ایمپورت شود

import html
import logging
import os
from urllib.parse import quote

from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
import media

log = logging.getLogger("referrals")

DEFAULT_REF_TEXT = (
    "🎁 <b>زیرمجموعه‌گیری</b>\n\n"
    "برای باز کردن «<b>{button}</b>» ابتدا باید <b>{count}</b> نفر را با "
    "لینک اختصاصی خودتان به ربات دعوت کنید:\n\n"
    "🔗 لینک دعوت شما:\n{link}\n\n"
    "پیشرفت شما: <b>{done}</b> زیرمجموعه\n\n"
    "پس از هر دعوت، دوباره روی همان دکمه بزنید تا باز شود."
)


def config(token: str) -> dict:
    try:
        count = int(db.get_setting(token, "ref_count", "0") or 0)
    except ValueError:
        count = 0
    return {
        "enabled": db.get_setting(token, "ref_enabled", "0") == "1",
        "count": max(0, count),
        "text": db.get_setting(token, "ref_text", "") or DEFAULT_REF_TEXT,
        "photo": db.get_setting(token, "ref_photo_path", "").strip(),
    }


def is_active(token: str) -> bool:
    """کلید اصلی: اگر خاموش باشد هیچ دکمه‌ای قفل دعوت ندارد."""
    return config(token)["enabled"]


def _btn_field(btn, name: str) -> int:
    """خواندن امن فیلد عددی دکمه (دیتابیس‌های قدیمی بعد از مهاجرت هم دارند)."""
    try:
        return int(btn[name] or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        return 0


def need_for(token: str, btn) -> int:
    """required_referrals این دکمه (۰ تعداد کلی پنل؛ قفلِ روشن حداقل ۱)."""
    cfg = config(token)
    own = _btn_field(btn, "ref_count") if btn is not None else 0
    need = own if own > 0 else cfg["count"]
    if need <= 0 and _btn_field(btn, "ref_req") == 1:
        need = 1   # قفل روشن بدون تعداد = حداقل یک توکن
    return need


def button_gate(token: str, btn) -> bool:
    """آیا این دکمه پشت قفل توکن است؟"""
    if btn is None:
        return False
    if _btn_field(btn, "ref_req") != 1:
        return False
    if not is_active(token):
        return False
    return need_for(token, btn) > 0


def _open_key(btn) -> str:
    return f"refopen:{int(btn['id'])}"


def is_open(token: str, user_id: int, btn) -> bool:
    """آیا این دکمه قبلاً برای این کاربر با توکن باز شده؟ (باز می‌ماند)"""
    if btn is None:
        return False
    return db.user_get_state(token, int(user_id), _open_key(btn)) == "1"


def mark_open(token: str, user_id: int, btn) -> None:
    """دکمه برای این کاربر برای همیشه باز می‌شود (توکنش سوخته است)."""
    if btn is not None:
        db.user_set_state(token, int(user_id), _open_key(btn), "1")


# ─────────────────────── پیام انتظار (کنسل خودکار با انتخاب دکمه)
_wait_msgs: dict[tuple[str, int], object] = {}


def _remember_wait(token: str, user_id: int, msg) -> None:
    """آخرین پیام «در انتظار توکن» کاربر را نگه می‌دارد (برای تعویض دکمه)."""
    _wait_msgs[(token, int(user_id))] = msg


def forget_waiting(token: str, user_id: int) -> None:
    """فراموش‌کردن پیام انتظار (وقتی کاربر خودش «❌ کنسل» زد)."""
    _wait_msgs.pop((token, int(user_id)), None)


async def cancel_waiting(token: str, user_id: int) -> None:
    """کنسل خودکار: با انتخاب هر دکمه، پیام انتظارِ قبلی حذف می‌شود.

    توکنی نمی‌سوزد و وضعیت هیچ دکمه‌ای عوض نمی‌شود (مدل توکن، کنسل را
    بی‌هزینه می‌کند). حذفِ ناموفق (مثلاً پیامِ قبلاً پاک‌شده) بی‌صدا
    نادیده گرفته می‌شود.
    """
    msg = _wait_msgs.pop((token, int(user_id)), None)
    if msg is None:
        return
    try:
        await msg.delete()
    except RPCError as e:
        log.debug("حذف پیام انتظار قبلی ناموفق بود: %s", e)


def register(token: str, invited_id: int, inviter_id: int) -> bool:
    """ثبت دعوت = افزودن یک توکن مصرف‌نشده به استخر دعوت‌کننده.

    قواعد:
        • دعوت‌کننده باید خودش ربات را استارت کرده باشد.
        • دعوتِ خودی و دعوتِ تکراری شمرده نمی‌شود (اولین دعوت‌کننده ملاک است).
    """
    if not inviter_id or inviter_id == invited_id:
        return False
    if db.referrer_of(token, invited_id) is not None:
        return False
    if not db.get_bot_user(token, inviter_id):
        return False
    db.add_referral(token, inviter_id, invited_id)
    log.info("توکن جدید برای %s ثبت شد (دعوت %s)", inviter_id, invited_id)
    return True


def link_of(bot_username: str, user_id: int) -> str:
    if not bot_username:
        return "(لینک در دسترس نیست — یوزرنیم ربات نامشخص است)"
    return f"https://t.me/{bot_username}?start=ref{user_id}"


def render_text(token: str, user, link: str, done: int,
                cfg: dict | None = None, button: str = "",
                need: int | None = None) -> str:
    cfg = cfg or config(token)
    count = cfg["count"] if need is None else int(need)
    # fix: {name} escape می‌شود تا نام‌های حاوی < یا & پیام دعوت را نشکنند
    return (
        cfg["text"]
        .replace("{name}", html.escape(str(getattr(user, "first_name", "") or ""), quote=False))
        .replace("{id}", str(getattr(user, "id", "")))
        .replace("{link}", link)
        .replace("{button}", html.escape(str(button or "این بخش"), quote=False))
        .replace("{count}", str(count))
        .replace("{done}", str(done))
        .replace("{left}", str(max(0, count - done)))
    )


def render_preview(token: str, user) -> str:
    """پیش‌نمایش متن در پنل ربات مادر (لینک واقعی هنوز در دسترس نیست)."""
    link = link_of("your_bot", getattr(user, "id", 0) or 0)
    return render_text(token, user, link, 0)


def keyboard(token: str, link: str) -> InlineKeyboardMarkup:
    """اشتراک‌گذاری لینک + کنسل کردن (فقط بستن پیام — بدون سوختن توکن)."""
    share = ("https://t.me/share/url?url=" + quote(link, safe="")
             + "&text=" + quote("به این ربات سر بزن 👇", safe=""))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 اشتراک‌گذاری لینک", url=share)],
        [InlineKeyboardButton("❌ کنسل کردن", callback_data="refcancel")],
    ])


async def _bot_username(client: Client) -> str:
    # pyrogram نتیجه‌ی get_me را کش می‌کند؛ بعد از بار اول هزینه‌ای ندارد
    me = await client.get_me()
    return getattr(me, "username", "") or ""


async def send_prompt(client: Client, token: str, chat_id: int, user,
                      bot_username: str | None = None,
                      need: int | None = None, btn=None) -> None:
    """پیام «در انتظار توکن» را می‌فرستد (عکس‌دار اگر تنظیم شده باشد).

    کاربر فقط شمارش کلی زیرمجموعه‌هایش را می‌بیند (نه تفکیک مصرف‌شده).
    """
    cfg = config(token)
    if need is None:
        need = need_for(token, btn)
    btn_title = str(btn["title"]) if btn is not None else ""
    if not bot_username:
        bot_username = await _bot_username(client)
    uid = getattr(user, "id", 0) or 0
    link = link_of(bot_username, uid)
    done = db.referral_count(token, uid)   # فقط شمارش کلی برای کاربر
    text = render_text(token, user, link, done, cfg,
                       button=btn_title, need=need)

    if cfg["photo"]:
        if os.path.exists(cfg["photo"]):
            try:
                sent = await media.send_content(
                    client, chat_id, kind="photo", text=text,
                    file_path=cfg["photo"], token=token, cache_key="refphoto",
                )
                if sent is not None:
                    _remember_wait(token, uid, sent)
                    return
            except Exception as e:  # noqa: BLE001
                log.warning("ارسال عکس پیام دعوت ناموفق: %s", e)
        else:
            log.warning("عکس پیام دعوت روی دیسک نیست: %s", cfg["photo"])
            db.set_setting(token, "ref_photo_path", "")

    msg = await client.send_message(
        chat_id, text, reply_markup=keyboard(token, link),
        disable_web_page_preview=True,
    )
    _remember_wait(token, uid, msg)


async def enforce_button(client: Client, token: str, owner_id: int,
                         chat_id: int, user, btn) -> bool:
    """دروازه‌ی توکنِ یک دکمه. True یعنی «اجازه‌ی باز کردن نیست».

    سوختن توکن دقیقاً هنگام باز شدنِ اول دکمه انجام می‌شود؛ چون دکمه‌ی
    بازشده باز می‌ماند، مسیرهای بعدی (مثلاً بعد از وارد کردن پسورد یا
    تأیید وظیفه) دوباره توکن نمی‌سوزانند.
    """
    if not button_gate(token, btn):
        return False
    # معافیت مالک (همان معافیتِ مشترک عضویت/وظیفه)
    if user.id == owner_id and db.get_setting(token, "owner_bypass", "0") == "1":
        return False
    if is_open(token, user.id, btn):
        return False   # قبلاً باز شده — ادامه از همان‌جا، بدون سوختن دوباره
    need = need_for(token, btn)
    if db.unused_tokens(token, user.id) >= need:
        db.burn_tokens(token, user.id, need)   # قدیمی‌ترین توکن‌ها می‌سوزند
        mark_open(token, user.id, btn)
        return False
    try:
        await send_prompt(client, token, chat_id, user, need=need, btn=btn)
    except RPCError as e:
        log.error("ارسال پیام زیرمجموعه‌گیری ناموفق: %s", e)
    return True
