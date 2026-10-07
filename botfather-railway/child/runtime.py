"""موتور ربات‌های فرزند — هر توکن یک Client جدا با هندلرهای مشترک.

جدید در این نسخه:
    • وظیفه اجباری با تأیید واقعی: چک عضویت + پنجره‌ی ۲ دقیقه‌ای (child/tasks.py)
    • زیرمجموعه‌گیری مدل توکن: استخر کلی، سوختن هنگام باز شدن دکمه (child/referrals.py)
    • 👍/👎 لایک و دیسلایک + 👁 بازدید برای فایل‌ها (کال‌بک fv)
    • 🎲 فایل رندوم و 🔍 جستجوی فایل (دکمه‌های اختیاری منو)
    • 🔑 پسورد فایل‌ها (تا کاربر رمز را نفرسد، محتوا ارسال نمی‌شود)
    • 🎂 سن و جنسیت اختیاری برای آمار دموگرافیک
    • 🗑 حذف خودکار محتوا بعد از N ثانیه
"""
from __future__ import annotations

import compat  # noqa: F401  ← باید قبل از pyrogram ایمپورت شود

import asyncio
import html
import logging
import random
import re
import time

from pyrogram import Client, StopPropagation, filters
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import (
    ChannelPrivate,
    ChatAdminRequired,
    PeerIdInvalid,
    RPCError,
    UsernameInvalid,
    UsernameNotOccupied,
    UserNotParticipant,
)
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import config
import db
import media
from child import referrals, tasks

log = logging.getLogger("child")

# سقف اندازهٔ کش‌های درون‌حافظه‌ای — جلوگیری از رشد بی‌رویه در ربات‌های پرکاربر
CACHE_MAX = 20000


def _cache_store(d: dict, key, value) -> None:
    """fix: درج در کش با سقف اندازه؛ اگر پر شد، قدیمی‌ترین کلید حذف می‌شود."""
    if len(d) >= CACHE_MAX:
        d.pop(next(iter(d)), None)
    d[key] = value


def esc(s) -> str:
    """fix: مقادیر تولیدیِ کاربر (مثل نام) قبل از قرارگرفتن در پیام HTML
    باید escape شوند، وگرنه کاربری که < یا & در نامش دارد باعث خطای
    «Can't parse entities» می‌شود و هیچ پیامی دریافت نمی‌کند."""
    return html.escape(str(s or ""), quote=False)

# متن‌های قابل تنظیم از ربات مادر (کلید → پیش‌فرض)
TEXTS: dict[str, str] = {
    "blocked_text": "⛔️ دسترسی شما به این ربات مسدود شده است.",
    "menu_hint": "از دکمه‌های منو استفاده کنید 👇",
    "support_prompt": "پیام خود را بنویسید (متن، عکس یا فایل)."
                      " برای لغو دکمه انصراف را بزنید.",
    "support_sent": "✅ پیام شما برای پشتیبانی ارسال شد.",
    "support_failed": "❌ ارسال پیام ممکن نشد.",
    "cancel_text": "لغو شد.",
}


def txt(token: str, key: str) -> str:
    """متن قابل تنظیم را می‌خواند؛ اگر خالی بود، پیش‌فرض را برمی‌گرداند."""
    return db.get_setting(token, key, "") or TEXTS.get(key, "")


SUPPORT_BTN = "☎️ ارتباط با پشتیبانی"
CANCEL_BTN = "❌ انصراف"
RND_BTN = "🎲 فایل رندوم"
SEARCH_BTN = "🔍 جستجوی فایل"
DEMO_SKIP = "رد کردن"
DEMO_MALE = "👨 مرد"
DEMO_FEMALE = "👩 زن"

PASS_PROMPT = ("🔐 <b>این محتوا با رمز محافظت شده است.</b>\n"
               "لطفاً رمز را بفرستید تا محتوا برای شما ارسال شود:")
PASS_WRONG = "❌ رمز اشتباه است. دوباره بفرستید یا «❌ انصراف» را بزنید."
PASS_OK = "✅ رمز درست بود."
SEARCH_PROMPT = ("🔍 کلیدواژه جستجو را بفرستید تا در عنوان و متن فایل‌ها بگردیم.\n"
                 "برای لغو دکمه انصراف را بزنید.")
SEARCH_EMPTY = "🔍 چیزی پیدا نشد. کلیدواژه دیگری را امتحان کنید."
DEMO_AGE_PROMPT = ("🎂 برای آمار ربات، <b>سن</b> خود را به عدد بفرستید"
                   " (مثلاً ۲۵).\nاگر نمی‌خواهید، «رد کردن» را بزنید.")
DEMO_GENDER_PROMPT = ("⚥ <b>جنسیت</b> خود را انتخاب کنید"
                      " (فقط برای آمار کلی استفاده می‌شود):")
DEMO_DONE = "✅ ممنون! اطلاعات شما ثبت شد."

# کاربرانی که در حالت «ارسال پیام به پشتیبانی» هستند: (token, user_id)
_support_mode: set[tuple[str, int]] = set()

# حالت‌های قابلیت‌های جدید
_search_mode: set[tuple[str, int]] = set()              # در حال جستجوی فایل
_pass_mode: dict[tuple[str, int], str] = {}             # منتظر رمز («rnd» یا id دکمه)
_demo_stage: dict[tuple[str, int], str] = {}            # 'age' | 'gender'
# دکمه‌ی در انتظارِ تأیید وظیفه: بعد از زدن «عضو شدم» همین محتوا ارسال شود
_task_pending: dict[tuple[str, int], int] = {}

# کش نتیجه‌ی بررسی عضویت: (token, user_id) -> (زمان, عضو همه کانال‌ها؟)
_member_cache: dict[tuple[str, int], tuple[float, bool]] = {}

# ⚠️ صفر یعنی «هر بار واقعاً از تلگرام بپرس».
# اگر کش مثبت داشته باشیم، کاربری که از کانال خارج می‌شود تا پایان کش
# همچنان می‌تواند از ربات استفاده کند — که دقیقاً نباید اتفاق بیفتد.
DEFAULT_CACHE_TTL = 0


def cache_ttl(token: str) -> int:
    try:
        return max(0, int(db.get_setting(token, "check_ttl", str(DEFAULT_CACHE_TTL))))
    except (TypeError, ValueError):
        return DEFAULT_CACHE_TTL

# جلوگیری از اسپم مالک بابت خطای پیکربندی: token -> زمان آخرین اطلاع
_misconfig_notified: dict[str, float] = {}
MISCONFIG_NOTIFY_INTERVAL = 1800  # ثانیه

# کلاینت ربات مادر (برای fallback ارسال تیکت پشتیبانی) —
# main.py پس از start مادر آن را تزریق می‌کند تا circular import نداشته باشیم
_mother_client: Client | None = None


def set_mother_client(client: Client) -> None:
    global _mother_client
    _mother_client = client


def get_mother_client() -> Client | None:
    return _mother_client


def fa_to_en_digits(s: str) -> str:
    """اعداد فارسی/عربی را به لاتین تبدیل می‌کند (ورودی سن و رمز)."""
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return (s or "").translate(table)


# ─────────────────────────────────────────────── ابزارهای کانال اجباری
def normalize_channel(raw: str) -> str:
    """ورودی‌های مختلف را استاندارد می‌کند.

    '@ch' | 'ch' | 't.me/ch' | 'https://t.me/ch' | '-1001234567890'
    لینک دعوت خصوصی (+ABC) پشتیبانی نمی‌شود چون قابل بررسی نیست.
    """
    ch = (raw or "").strip()
    if not ch:
        return ""
    if ch.startswith("-100") and ch[1:].lstrip("-").isdigit():
        return ch
    ch = re.sub(r"^https?://", "", ch, flags=re.I)
    ch = re.sub(r"^(www\.)?t\.me/", "", ch, flags=re.I)
    ch = ch.split("?")[0].strip("/")
    if not ch or ch.startswith("+") or ch.lower().startswith("joinchat"):
        return ""
    ch = ch.lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", ch):
        return ""
    return f"@{ch}"


def channel_link(channel: str) -> str:
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}"
    return "https://t.me/"


async def channel_status(client: Client, channel: str, user_id: int) -> str:
    """وضعیت یک کاربر در یک کانال: 'ok' | 'join' | 'misconfig'"""
    try:
        member = await client.get_chat_member(channel, user_id)
        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            return "join"
        return "ok"
    except UserNotParticipant:
        return "join"
    except (
        ChatAdminRequired,
        ChannelPrivate,
        PeerIdInvalid,
        UsernameNotOccupied,
        UsernameInvalid,
    ) as e:
        log.error("کانال %s قابل بررسی نیست: %s", channel, e)
        return "misconfig"
    except RPCError as e:
        log.error("بررسی عضویت %s ناموفق: %s", channel, e)
        return "misconfig"


async def check_membership(
    client: Client, token: str, user_id: int, use_cache: bool = True
) -> tuple[str, list[str], list[str]]:
    """بررسی عضویت در همه‌ی کانال‌های اجباری.

    خروجی: (وضعیت, کانال‌هایی که عضو نیست, کانال‌های خراب)
        "off" | "ok" | "join" | "misconfig"
    """
    channels = db.get_channels(token)
    if not channels:
        return "off", [], []

    key = (token, user_id)
    ttl = cache_ttl(token)
    if use_cache and ttl > 0:
        cached = _member_cache.get(key)
        if cached and (time.monotonic() - cached[0]) < ttl and cached[1]:
            return "ok", [], []

    missing: list[str] = []
    broken: list[str] = []
    for ch in channels:
        state = await channel_status(client, ch, user_id)
        if state == "join":
            missing.append(ch)
        elif state == "misconfig":
            broken.append(ch)

    if broken:
        _member_cache.pop(key, None)
        return "misconfig", missing, broken
    if missing:
        _cache_store(_member_cache, key, (time.monotonic(), False))
        return "join", missing, []

    _cache_store(_member_cache, key, (time.monotonic(), True))
    return "ok", [], []


DEFAULT_JOIN_TEXT = (
    "برای استفاده از ربات باید در کانال‌های زیر عضو شوید 👇\n\n"
    "{channels}\n\n"
    "پس از عضویت، دکمه‌ی «✅ عضو شدم» را بزنید."
)


def render_join_text(token: str, user, channels: list[str]) -> str:
    """پیام عضویت اجباری را با جای‌گذاری متغیرها می‌سازد.

    متغیرها: {name} {id} {count} {channels} {links}
    """
    tpl = db.get_setting(token, "join_text", "") or DEFAULT_JOIN_TEXT
    ch_list = "\n".join(f"🔹 {c}" for c in channels)
    links = "\n".join(f"🔹 <a href=\"{channel_link(c)}\">{c}</a>" for c in channels)
    return (
        tpl.replace("{name}", esc(getattr(user, "first_name", "")))
        .replace("{id}", str(getattr(user, "id", "")))
        .replace("{count}", str(len(channels)))
        .replace("{channels}", ch_list)
        .replace("{links}", links)
    )


def join_keyboard(channels: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📢 عضویت در {ch}", url=channel_link(ch))]
        for ch in channels
    ]
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data="checkjoin")])
    return InlineKeyboardMarkup(rows)


async def _send_join_prompt(
    token: str, message: Message, channels: list[str]
) -> None:
    await message.reply(
        render_join_text(token, message.from_user, channels),
        reply_markup=join_keyboard(channels),
        disable_web_page_preview=True,
    )


async def _notify_owner_misconfig(
    client: Client, token: str, owner_id: int, broken: list[str]
) -> None:
    """اطلاع به مالک ربات درباره‌ی کانال خراب (حداکثر هر نیم‌ساعت)."""
    last = _misconfig_notified.get(token)          # None یعنی «هرگز اطلاع داده نشده»
    if last is not None and (time.monotonic() - last) < MISCONFIG_NOTIFY_INTERVAL:
        return
    _misconfig_notified[token] = time.monotonic()
    lst = "\n".join(f"• <code>{c}</code>" for c in broken)
    try:
        await client.send_message(
            owner_id,
            "⚠️ <b>کانال عضویت اجباری کار نمی‌کند</b>\n\n"
            f"{lst}\n\n"
            "ربات نمی‌تواند عضویت کاربران را بررسی کند. برای رفع مشکل:\n"
            "۱) این ربات را در کانال <b>ادمین</b> کنید.\n"
            "۲) یوزرنیم کانال را بررسی کنید.\n\n"
            "تا رفع مشکل، دسترسی کاربران بسته می‌ماند.",
        )
    except RPCError:
        pass


async def enforce_all(
    client: Client, token: str, owner_id: int, message: Message
) -> bool:
    """دروازه‌های ورودی: مسدودی → عضویت اجباری.

    True یعنی «جلوی ادامه را بگیر».

    fix: وظیفه اجباری از این دروازه جدا شد — حالا پیام وظیفه فقط روی
    /start و هنگام درخواستِ محتوا (child/tasks.enforce) نمایش داده می‌شود
    و بعد از تاخیرِ قابل تنظیم، محتوا خودکار ارسال می‌گردد.
    """
    user = message.from_user

    # ۱) کاربر مسدود
    if db.is_blocked(token, user.id):
        await message.reply(txt(token, "blocked_text"))
        return True

    # ۲) عضویت اجباری
    if await enforce_join(client, token, owner_id, message):
        return True

    return False


async def enforce_join(
    client: Client, token: str, owner_id: int, message: Message
) -> bool:
    """اگر کاربر مجاز نیست پیام مناسب می‌فرستد و True برمی‌گرداند (یعنی «متوقف کن»)."""
    user_id = message.from_user.id

    # معافیت مالک فقط اگر خودش روشنش کرده باشد (پیش‌فرض: خاموش)
    if user_id == owner_id and db.get_setting(token, "owner_bypass", "0") == "1":
        return False

    state, missing, broken = await check_membership(client, token, user_id)
    if state in ("off", "ok"):
        return False

    if state == "misconfig":
        # ⚠️ کاربر مقصر نیست؛ نباید پیام گنگ «در دسترس نیست» ببیند.
        # همان پیام عضویت را می‌بیند و مالک ربات جداگانه هشدار می‌گیرد.
        await _notify_owner_misconfig(client, token, owner_id, broken)
        await _send_join_prompt(token, message, missing + broken)
        return True

    await _send_join_prompt(token, message, missing)
    return True


# ───────────────── وظیفه اجباری (تأیید عضویت + پنجره‌ی ۲ دقیقه)
async def enforce_task(client: Client, token: str, owner_id: int,
                       chat_id: int, user, btn=None) -> bool:
    """دروازه‌ی وظیفه‌ی اجباری. True یعنی «محتوا هنوز ارسال نشود».

    • تأیید ۲ دقیقه‌ای معتبر → بدون هیچ چکی باز شود.
    • عضو کانالِ خواسته → تأیید همین حالا ثبت و باز شود.
    • غیرعضو → پیام وظیفه + «✅ عضو شدم» (پس از تأیید، همین دکمه ارسال
      می‌شود؛ برای این کار دکمه در _task_pending نگه داشته می‌شود).
    • خرابی بررسی (مثل ادمین‌نبودن ربات) → fail-closed + هشدار به مالک.
    """
    if not tasks.is_active(token):
        return False
    if user.id == owner_id and db.get_setting(token, "owner_bypass", "0") == "1":
        return False
    if tasks.verified_recently(token, user.id):
        return False

    cfg = tasks.config(token)
    state = await channel_status(client, cfg["channel"], user.id)
    if state == "ok":
        tasks.mark_verified(token, user.id)
        return False
    if state == "misconfig":
        # کاربر مقصر نیست ولی تأیید ممکن نیست؛ مالک هشدار می‌گیرد
        await _notify_owner_misconfig(client, token, owner_id, [cfg["channel"]])

    if btn is not None:
        _cache_store(_task_pending, (token, user.id), int(btn["id"]))
    try:
        await client.send_message(
            chat_id,
            tasks.render_text(token, user),
            reply_markup=tasks.keyboard(cfg["channel"]),
            disable_web_page_preview=True,
        )
    except RPCError as e:
        log.warning("ارسال پیام وظیفه ناموفق: %s", e)
    return True


# ───────────────────────────────────────── قابلیت‌های فایل
def pass_required(token: str) -> bool:
    """آیا پسورد فایل‌ها فعال است؟"""
    return bool(db.get_setting(token, "file_pass", "").strip())


def pass_ok(token: str, user_id: int) -> bool:
    """آیا کاربر رمز درست را قبلاً وارد کرده؟ (با رمزِ فعلی مقایسه می‌شود؛
    تغییر رمز توسط سازنده، همه را دوباره قفل می‌کند)"""
    if not pass_required(token):
        return True
    current = db.get_setting(token, "file_pass", "").strip()
    return db.user_get_state(token, user_id, "pass_ok") == current


def votes_keyboard(token: str, bid: int) -> InlineKeyboardMarkup | None:
    """کیبورد 👍/👎 زیر فایل‌ها (اگر قابلیت روشن باشد)."""
    if db.get_setting(token, "votes_enabled", "1") != "1":
        return None
    likes, dislikes = db.vote_counts(token, bid)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"👍 {likes}", callback_data=f"fv:{bid}:1"),
        InlineKeyboardButton(f"👎 {dislikes}", callback_data=f"fv:{bid}:0"),
    ]])


async def _autodel_task(client: Client, msgs: list, seconds: int) -> None:
    """بعد از seconds ثانیه پیام‌های محتوا را حذف می‌کند (حذف خودکار)."""
    try:
        await asyncio.sleep(max(1, int(seconds)))
    except asyncio.CancelledError:  # pragma: no cover
        raise
    for m in msgs:
        try:
            await m.delete()
        except Exception:  # noqa: BLE001
            pass


def schedule_autodel(token: str, msgs: list) -> None:
    """اگر «حذف خودکار» روشن باشد، حذف پیام‌ها را زمان‌بندی می‌کند."""
    try:
        secs = int(db.get_setting(token, "autodel", "0") or 0)
    except ValueError:
        secs = 0
    if secs > 0 and msgs:
        asyncio.create_task(_autodel_task(msgs[0].client, msgs, secs))


def search_buttons(token: str, query: str, limit: int = 15) -> list:
    """جستجوی فایل بر اساس عنوان و متن دکمه‌ها."""
    q = fa_to_en_digits(query).strip()
    if not q:
        return []
    like = ("%" + q.lower()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_") + "%")
    return db.fetchall(
        "SELECT * FROM buttons WHERE token=?"
        " AND (LOWER(COALESCE(title,'')) LIKE ? ESCAPE '\\'"
        "      OR LOWER(COALESCE(body,'')) LIKE ? ESCAPE '\\')"
        " ORDER BY position LIMIT ?",
        (token, like, like, limit),
    )


def random_pool(token: str, user_id: int) -> list:
    """دکمه‌های قابل ارسال رندوم — دکمه‌های قفل‌دارِ بازنشده حذف می‌شوند."""
    pool = []
    for b in db.buttons(token):
        if (referrals.button_gate(token, b)
                and not referrals.is_open(token, user_id, b)):
            continue
        pool.append(b)
    return pool


# ─────────────────────────────────────────────────────── منو و محتوا
def main_keyboard(token: str) -> ReplyKeyboardMarkup | None:
    titles = [b["title"] for b in db.buttons(token)]
    # قابلیت‌های اختیاری منو
    if db.get_setting(token, "rnd_enabled", "0") == "1":
        titles.append(RND_BTN)
    if db.get_setting(token, "search_enabled", "0") == "1":
        titles.append(SEARCH_BTN)
    if db.get_setting(token, "support", "1") == "1":
        titles.append(SUPPORT_BTN)
    if not titles:
        return None
    rows, row = [], []
    for t in titles:
        row.append(KeyboardButton(t))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def _send_button_content(client: Client, chat_id: int, btn, token: str,
                               with_stats: bool = False) -> list:
    """محتوای یک دکمه را می‌فرستد و پیام‌های ارسال‌شده را برمی‌گرداند.

    یک دکمه می‌تواند متن + چند رسانه داشته باشد. متن دقیقاً **یک بار** فرستاده
    می‌شود: یا به‌عنوان کپشن روی آیتمی که کاربر انتخاب کرده،
    یا اگر «جداگانه» انتخاب شده باشد، به‌صورت یک پیام مستقل قبل از رسانه‌ها.

    with_stats: ثبت بازدید + چسباندن دکمه‌های 👍/👎 روی آخرین پیام
    (پیش‌نمایشِ پنل ربات مادر این را False می‌فرستد تا آمار قاطی نشود).

    نکته: file_id ربات مادر برای این ربات بی‌اعتبار است، پس بار اول از روی
    دیسک آپلود می‌کنیم و file_id حاصل را کش می‌کنیم.
    """
    keys = btn.keys()
    text = btn["body"] or ""
    items = db.button_items(token, btn["id"])
    bid = int(btn["id"])

    fk = votes_keyboard(token, bid) if with_stats else None
    if with_stats:
        db.bump_views(token, bid)   # هر بار ارسال محتوا = یک بازدید

    sent_msgs: list = []

    # ── حالت قدیمی: دکمه‌ای که فقط یک محتوا دارد ──
    if not items:
        try:
            sent = await media.send_content(
                client,
                chat_id,
                kind=btn["kind"],
                text=text,
                file_path=btn["file_path"] if "file_path" in keys else None,
                token=token,
                cache_key=f"btn:{bid}",
                reply_markup=fk,
            )
            if sent is not None:
                sent_msgs.append(sent)
        except Exception as e:  # noqa: BLE001
            log.error("ارسال محتوای دکمه «%s» ناموفق بود: %s", btn["title"], e)
            await client.send_message(chat_id, "⚠️ ارسال این محتوا ممکن نشد.")
        return sent_msgs

    # ── حالت چندتایی ──
    target = btn["caption_target"] if "caption_target" in keys else -1
    if target is None:
        target = -1
    valid_ids = {it["id"] for it in items}
    if target not in valid_ids:
        target = -1  # آیتم هدف حذف شده → متن جداگانه فرستاده می‌شود

    text_sent = False
    if text and target == -1:
        try:
            await client.send_message(chat_id, text, disable_web_page_preview=True)
            text_sent = True
        except Exception as e:  # noqa: BLE001
            log.error("ارسال متن دکمه «%s» ناموفق: %s", btn["title"], e)

    for i, item in enumerate(items):
        caption = ""
        if text and not text_sent and item["id"] == target:
            caption = text
        # دکمه‌ی 👍/👎 فقط به آخرین آیتم می‌چسبد
        item_fk = fk if (fk is not None and i == len(items) - 1) else None
        try:
            sent = await media.send_content(
                client,
                chat_id,
                kind=item["kind"],
                text=caption,
                file_path=item["file_path"],
                token=token,
                cache_key=f"item:{item['id']}",
                reply_markup=item_fk,
            )
            if sent is not None:
                sent_msgs.append(sent)
            if caption and sent is not None:
                text_sent = True
        except Exception as e:  # noqa: BLE001
            log.error("ارسال آیتم %s دکمه «%s» ناموفق: %s",
                      item["id"], btn["title"], e)

    # اگر ارسالِ آیتمِ حاملِ متن شکست خورد، متن نباید گم شود
    if text and not text_sent:
        try:
            m = await client.send_message(chat_id, text,
                                          disable_web_page_preview=True,
                                          reply_markup=fk)
            sent_msgs.append(m)
        except Exception as e:  # noqa: BLE001
            log.error("ارسال متن جایگزین ناموفق: %s", e)

    return sent_msgs


async def send_footer(client: Client, chat_id: int, token: str, user=None) -> None:
    """پیام پایانی (اگر تنظیم شده باشد) بعد از محتوای هر دکمه."""
    footer = db.get_setting(token, "footer_text", "").strip()
    if not footer:
        return
    # fix: {name} escape می‌شود تا نام‌های حاوی < یا & پیام پایانی را نشکنند
    footer = (footer.replace("{name}", esc(getattr(user, "first_name", "")))
                    .replace("{id}", str(getattr(user, "id", ""))))
    try:
        await client.send_message(chat_id, footer, disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001
        log.error("ارسال پیام پایانی ناموفق: %s", e)


async def deliver_button(client: Client, chat_id: int, user, btn,
                         owner_id: int, token: str) -> list:
    """ارسال محتوای یک دکمه با تمام دروازه‌ها به ترتیب:

    ۰) کنسل خودکار پیام انتظار قبلی (انتخاب دکمه = بستن انتظار قبلی)
    ۱) وظیفه اجباری (چکِ «همیشه» سر راه هر کلیک + پنجره‌ی ۲ دقیقه)
    ۲) قفل توکن زیرمجموعه‌گیری (سوختن توکن فقط هنگام باز شدن اول)
    ۳) پسورد فایل

    خروجی: پیام‌های محتوای ارسال‌شده (اگر دروازه‌ای جلوی راه باشد، لیست خالی).
    """
    # ۰) تعویض دکمه: پیام انتظارِ قبلی خودکار کنسل می‌شود (توکن نمی‌سوزد؛
    #    برگشت به همان دکمه = ادامه از همان‌جا).
    await referrals.cancel_waiting(token, user.id)

    # ۱) وظیفه اجباری — طبق spec صاحب ربات چکِ وظیفه «همیشه» اول از همه
    #    انجام می‌شود؛ اگر همین حالا پیام وظیفه نمایش داده شد، محتوا پس
    #    از تأیید ارسال می‌شود.
    if await enforce_task(client, token, owner_id, chat_id, user, btn=btn):
        return []

    # ۲) قفل توکن — اگر توکن کافی نباشد پیام دعوت می‌آید و محتوا نمی‌آید
    if await referrals.enforce_button(client, token, owner_id, chat_id, user, btn):
        return []

    # ۳) پسورد فایل‌ها
    if not pass_ok(token, user.id):
        _cache_store(_pass_mode, (token, user.id), str(btn["id"]))
        try:
            await client.send_message(chat_id, PASS_PROMPT)
        except RPCError:
            pass
        return []

    msgs = await _send_button_content(client, chat_id, btn, token, with_stats=True)
    await send_footer(client, chat_id, token, user)
    schedule_autodel(token, msgs)
    return msgs


async def deliver_random(client: Client, chat_id: int, user,
                         owner_id: int, token: str) -> None:
    """🎲 ارسال یک فایل رندوم از بین فایل‌های قابل‌دسترس کاربر."""
    pool = random_pool(token, user.id)
    if not pool:
        await client.send_message(chat_id, "🎲 فعلاً فایلی برای ارسال رندوم نیست.")
        return
    btn = random.choice(pool)
    await deliver_button(client, chat_id, user, btn, owner_id, token)


# ────────────────────────────────────────────────────── ساخت کلاینت
def build_client(token: str, owner_id: int, name: str) -> Client:
    app = Client(
        name=name,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=token,
        workdir=str(config.SESSIONS_DIR),
        parse_mode=ParseMode.HTML,
    )

    async def send_welcome(client: Client, chat_id: int, user) -> None:
        welcome = db.get_setting(token, "welcome", "سلام!")
        # fix: {name} escape می‌شود تا نام‌های حاوی < یا & پیام را نشکنند
        welcome = welcome.replace("{name}", esc(user.first_name)).replace(
            "{id}", str(user.id)
        )
        await client.send_message(chat_id, welcome, reply_markup=main_keyboard(token))

    def _maybe_start_demo(user) -> None:
        """اگر «سن و جنسیت» روشن است و کاربر جدید هنوز پاسخ نداده، شروع کن.

        fix: کاربری که قبلاً «رد کردن» زده یا جواب داده، دیگر هرگز
        پرسیده نمی‌شود — فلگ demo_done در user_state ثبت می‌شود.
        """
        if db.get_setting(token, "demo_ask", "0") != "1":
            return
        if db.user_get_state(token, user.id, "demo_done") == "1":
            return
        row = db.get_bot_user(token, user.id)
        if row is None or (row["age"] is None and not row["gender"]):
            _cache_store(_demo_stage, (token, user.id), "age")

    # ---------------------------------------------------------- /start
    async def on_start(client: Client, message: Message):
        u = message.from_user
        is_new = db.track_user(token, u.id, u.first_name or "", u.username or "")

        # ── ثبت زیرمجموعه اگر با لینک دعوت (/start ref<id>) آمده باشد ──
        cmd = getattr(message, "command", None) or []
        if len(cmd) > 1 and is_new:
            m = re.fullmatch(r"ref(\d{3,20})", str(cmd[1]).strip())
            if m and referrals.register(token, u.id, int(m.group(1))):
                # اطلاع به دعوت‌کننده: یک توکن به استخرش اضافه شد
                inviter_id = int(m.group(1))
                try:
                    await client.send_message(
                        inviter_id,
                        f"🎉 {esc(u.first_name)} با لینک تو وارد ربات شد!\n"
                        f"👥 مجموع زیرمجموعه‌های تو: "
                        f"<b>{db.referral_count(token, inviter_id)}</b>\n"
                        "اگر دکمه‌ای در انتظار دعوت است، دوباره روی آن بزنید"
                        " تا با توکن‌هایت باز شود.",
                    )
                except RPCError:
                    pass

        if await enforce_all(client, token, owner_id, message):
            return

        await send_welcome(client, message.chat.id, u)

        # سن و جنسیت (اختیاری) — فقط برای کاربر جدیدی که هنوز پاسخ نداده
        _maybe_start_demo(u)
        if _demo_stage.get((token, u.id)) == "age":
            await client.send_message(
                u.id, DEMO_AGE_PROMPT,
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton(DEMO_SKIP)]], resize_keyboard=True),
            )

        if is_new:
            try:
                # fix: نام کاربر escape می‌شود تا پیام اطلاع‌رسانی به مالک نشکند
                await client.send_message(
                    owner_id,
                    f"🆕 کاربر جدید: {esc(u.first_name)} (<code>{u.id}</code>)\n"
                    f"مجموع کاربران: {db.bot_user_count(token)}",
                )
            except RPCError:
                pass

    # ------------------------------------------------- «عضو شدم» اینلاین
    async def on_checkjoin(client: Client, cq):
        _member_cache.pop((token, cq.from_user.id), None)  # کش را تازه کن
        state, missing, broken = await check_membership(
            client, token, cq.from_user.id, use_cache=False
        )
        if state == "misconfig":
            await _notify_owner_misconfig(client, token, owner_id, broken)
            await cq.answer("هنوز عضویت شما تأیید نشد ❌", show_alert=True)
            try:
                await cq.message.edit_text(
                    render_join_text(token, cq.from_user, missing + broken),
                    reply_markup=join_keyboard(missing + broken),
                    disable_web_page_preview=True,
                )
            except RPCError:
                pass
            return
        if state == "join":
            names = "، ".join(missing)
            await cq.answer(
                f"هنوز عضو نشده‌اید ❌\n{names}", show_alert=True
            )
            try:
                await cq.message.edit_text(
                    render_join_text(token, cq.from_user, missing),
                    reply_markup=join_keyboard(missing),
                    disable_web_page_preview=True,
                )
            except RPCError:
                pass
            return
        await cq.answer("عضویت تأیید شد ✅")
        try:
            await cq.message.delete()
        except RPCError:
            pass
        await send_welcome(client, cq.from_user.id, cq.from_user)

    # --------------------- «✅ عضو شدم» وظیفه اجباری (taskjoin)
    async def on_taskjoin(client: Client, cq):
        """تأیید وظیفه: چک واقعی عضویت در کانال خواسته.

        عضو بود → verified_at ثبت (پنجره‌ی ۲ دقیقه) + ارسال محتوای در
        انتظار (همان دکمه‌ای که کاربر خواسته). غیرعضو → پیام خطای صریح.
        """
        if not tasks.is_active(token):
            try:
                await cq.answer("وظیفه‌ای فعال نیست.", show_alert=True)
            except RPCError:
                pass
            return
        cfg = tasks.config(token)
        state = await channel_status(client, cfg["channel"], cq.from_user.id)
        if state == "ok":
            tasks.mark_verified(token, cq.from_user.id)
            try:
                await cq.answer("عضویت تأیید شد ✅")
            except RPCError:
                pass
            try:
                await cq.message.delete()
            except RPCError:
                pass
            bid = _task_pending.pop((token, cq.from_user.id), None)
            btn = db.button_by_id(token, bid) if bid else None
            if btn is not None:
                await deliver_button(client, cq.from_user.id, cq.from_user, btn,
                                     owner_id, token)
            return
        if state == "misconfig":
            await _notify_owner_misconfig(client, token, owner_id,
                                          [cfg["channel"]])
            try:
                await cq.answer("هنوز عضویت شما تأیید نشد ❌", show_alert=True)
            except RPCError:
                pass
            return
        try:
            await cq.answer("شما هنوز عضو کانال نشدید ❌", show_alert=True)
        except RPCError:
            pass

    # -------------------------------- بستن پیام انتظار زیرمجموعه
    async def on_refcancel(client: Client, cq):
        """«❌ کنسل کردن» پیام دعوت: فقط بستن پیام — توکنی نمی‌سوزد و
        دکمه‌ی بازشده هم قفل نمی‌شود (مدل توکن، کنسل را بی‌هزینه می‌کند)."""
        try:
            await cq.answer("کنسل شد — هر وقت خواستی دوباره دکمه را بزن.")
        except RPCError:
            pass
        try:
            await cq.message.delete()
        except RPCError:
            pass
        referrals.forget_waiting(token, cq.from_user.id)

    # ------------------------------------------------ 👍/👎 و دریافت فایل
    async def on_filevote(client: Client, cq):
        """کال‌بک لایک/دیسلایک: fv:<btn_id>:<1|0>

        رأیِ تکراری همان رأی قبلی را برمی‌دارد (toggle)؛ سپس شمارنده‌ها
        روی همان پیام به‌روز می‌شوند.
        """
        parts = (cq.data or "").split(":")
        if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("0", "1"):
            try:
                await cq.answer()
            except RPCError:
                pass
            return
        bid, val = int(parts[1]), int(parts[2])
        if db.button_by_id(token, bid) is None:
            try:
                await cq.answer("این فایل دیگر موجود نیست.", show_alert=True)
            except RPCError:
                pass
            return
        current = db.vote_of(token, bid, cq.from_user.id)
        if current == (1 if val else -1):
            db.del_vote(token, bid, cq.from_user.id)
            note = "رأی شما برداشته شد ♻️"
        else:
            db.set_vote(token, bid, cq.from_user.id, 1 if val else -1)
            note = "رأی شما ثبت شد ✅"
        try:
            await cq.answer(note)
        except RPCError:
            pass
        try:
            await cq.message.edit_reply_markup(votes_keyboard(token, bid))
        except RPCError:
            pass

    async def on_fget(client: Client, cq):
        """دریافت فایل از نتایج جستجو: fget:<btn_id> — با همه‌ی دروازه‌ها."""
        raw = (cq.data or "").split(":")
        btn = None
        if len(raw) == 2 and raw[1].isdigit():
            btn = db.button_by_id(token, int(raw[1]))
        try:
            await cq.answer()
        except RPCError:
            pass
        if btn is None:
            try:
                await cq.answer("این فایل دیگر موجود نیست.", show_alert=True)
            except RPCError:
                pass
            return
        await deliver_button(client, cq.from_user.id, cq.from_user, btn,
                             owner_id, token)

    # -------------------------------------------- پاسخ مالک به تیکت‌ها
    async def on_owner_reply(client: Client, message: Message):
        ticket = db.ticket_by_msg(token, message.reply_to_message.id)
        if not ticket:
            return
        try:
            await message.copy(ticket["user_id"])
            await message.reply("✅ پاسخ ارسال شد.")
        except RPCError as e:
            await message.reply(f"❌ ارسال ناموفق: {e}")
        # جلوگیری از اجرای on_message روی همین پیام (وگرنه مالک
        # پیام «از دکمه‌های منو استفاده کنید» یا درخواست عضویت می‌گرفت)
        raise StopPropagation

    # ------------------------------------------------ پیام‌های کاربران
    async def on_message(client: Client, message: Message):
        u = message.from_user
        db.track_user(token, u.id, u.first_name or "", u.username or "")

        text = (message.text or "").strip()
        chat_id = message.chat.id

        # انصراف باید همیشه کار کند و همه‌ی حالت‌ها را پاک کند
        if text == CANCEL_BTN:
            _support_mode.discard((token, u.id))
            _search_mode.discard((token, u.id))
            _pass_mode.pop((token, u.id), None)
            _demo_stage.pop((token, u.id), None)
            _task_pending.pop((token, u.id), None)
            return await message.reply(txt(token, "cancel_text"),
                                       reply_markup=main_keyboard(token))

        # ⚠️ بررسی روی «هر پیام» — نه فقط /start.
        # وگرنه کاربر با زدن دکمه‌ها همه‌ی شرط‌ها را دور می‌زند.
        if await enforce_all(client, token, owner_id, message):
            return

        # ── ۱) سن و جنسیت (اگر در حال پرسیدن باشیم) ──
        stage = _demo_stage.get((token, u.id))
        if stage:
            if stage == "age":
                if text == DEMO_SKIP:
                    _demo_stage.pop((token, u.id), None)
                    db.user_set_state(token, u.id, "demo_done", "1")
                    return await message.reply(txt(token, "menu_hint"),
                                               reply_markup=main_keyboard(token))
                num = fa_to_en_digits(text).strip()
                if num.isdigit() and 5 <= int(num) <= 120:
                    db.set_user_meta(token, u.id, age=int(num))
                    _cache_store(_demo_stage, (token, u.id), "gender")
                    return await message.reply(
                        DEMO_GENDER_PROMPT,
                        reply_markup=ReplyKeyboardMarkup(
                            [[KeyboardButton(DEMO_MALE), KeyboardButton(DEMO_FEMALE)],
                             [KeyboardButton(DEMO_SKIP)]], resize_keyboard=True),
                    )
                return await message.reply(
                    "❌ لطفاً سن را فقط با عدد بفرستید (۵ تا ۱۲۰)"
                    " یا «رد کردن» را بزنید.")
            # stage == "gender"
            if text == DEMO_SKIP:
                _demo_stage.pop((token, u.id), None)
                db.user_set_state(token, u.id, "demo_done", "1")
                return await message.reply(txt(token, "menu_hint"),
                                           reply_markup=main_keyboard(token))
            if text in (DEMO_MALE, DEMO_FEMALE):
                db.set_user_meta(token, u.id, gender="m" if text == DEMO_MALE else "f")
                _demo_stage.pop((token, u.id), None)
                db.user_set_state(token, u.id, "demo_done", "1")
                return await message.reply(DEMO_DONE,
                                           reply_markup=main_keyboard(token))
            return await message.reply(
                "❌ لطفاً از دکمه‌های زیر انتخاب کنید یا «رد کردن» را بزنید.")

        # ── ۲) انتظار رمز فایل‌ها ──
        pending = _pass_mode.get((token, u.id))
        if pending is not None:
            if text and text == db.get_setting(token, "file_pass", "").strip():
                db.user_set_state(token, u.id, "pass_ok", text)
                _pass_mode.pop((token, u.id), None)
                await message.reply(PASS_OK)
                if pending == "rnd":
                    return await deliver_random(client, chat_id, u, owner_id, token)
                if pending.isdigit():
                    btn = db.button_by_id(token, int(pending))
                    if btn:
                        return await deliver_button(client, chat_id, u, btn,
                                                    owner_id, token)
                return
            return await message.reply(PASS_WRONG)

        # ── ۳) حالت جستجوی فایل ──
        if (token, u.id) in _search_mode:
            _search_mode.discard((token, u.id))
            rows = search_buttons(token, text)
            if not rows:
                return await message.reply(SEARCH_EMPTY)
            kb = [[InlineKeyboardButton(f"📄 {r['title']}",
                                        callback_data=f"fget:{r['id']}")]
                  for r in rows]
            kb.append([InlineKeyboardButton("« بستن",
                                            callback_data="srchclose")])
            return await message.reply(
                f"🔍 <b>{len(rows)} نتیجه پیدا شد</b> — برای دریافت بزنید:",
                reply_markup=InlineKeyboardMarkup(kb))

        # ── ۴) دکمه‌های قابلیت‌ها ──
        if text == RND_BTN and db.get_setting(token, "rnd_enabled", "0") == "1":
            return await deliver_random(client, chat_id, u, owner_id, token)
        if text == SEARCH_BTN and db.get_setting(token, "search_enabled", "0") == "1":
            if len(_search_mode) >= CACHE_MAX:
                _search_mode.clear()
            _search_mode.add((token, u.id))
            return await message.reply(SEARCH_PROMPT)

        if text == SUPPORT_BTN and db.get_setting(token, "support", "1") == "1":
            if len(_support_mode) >= CACHE_MAX:
                _support_mode.clear()   # fix: سقف ایمنی برای مصرف حافظه
            _support_mode.add((token, u.id))
            return await message.reply(
                txt(token, "support_prompt"),
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton(CANCEL_BTN)]], resize_keyboard=True
                ),
            )

        btn = db.button_by_title(token, text) if text else None
        if btn:
            await deliver_button(client, chat_id, u, btn, owner_id, token)
            return

        if (token, u.id) in _support_mode:
            _support_mode.discard((token, u.id))
            delivered = False
            fail_reason = ""
            # مسیر ۱: خود ربات فرزند به مالکش (مالک باید یک‌بار ربات را استارت کرده باشد)
            try:
                header = await client.send_message(
                    owner_id,
                    f"📩 پیام جدید از {esc(u.first_name)} "
                    f"(@{u.username or '—'} | <code>{u.id}</code>)\n"
                    f"<i>برای پاسخ، روی همین پیام ریپلای کنید.</i>",
                )
                await message.copy(owner_id)
                db.add_ticket(token, u.id, header.id)
                delivered = True
            except RPCError as e:
                fail_reason = str(e)
                log.warning("ارسال تیکت با کلاینت فرزند ناموفق: %s", e)
            # مسیر ۲ (fallback): کلاینت مادر — مالک همیشه مادر را استارت کرده
            if not delivered:
                mclient = get_mother_client()
                if mclient is not None:
                    try:
                        header = await mclient.send_message(
                            owner_id,
                            "📩 <b>پیام پشتیبانی از ربات فرزند</b>\n"
                            f"🤖 ربات: <code>{token.split(':')[0]}</code>\n"
                            f"👤 کاربر: {esc(u.first_name)} "
                            f"(@{u.username or '—'} | <code>{u.id}</code>)\n"
                            "<i>برای پاسخ، روی همین پیام ریپلای کنید.</i>",
                        )
                        await mclient.send_message(owner_id, text or "«پیام بدون متن»")
                        db.add_ticket(token, u.id, header.id)
                        delivered = True
                    except RPCError as e:
                        fail_reason = str(e)
                        log.warning("ارسال تیکت با کلاینت مادر ناموفق: %s", e)
            if delivered:
                await message.reply(
                    txt(token, "support_sent"), reply_markup=main_keyboard(token)
                )
            else:
                log.error("تیکت پشتیبانی تحویل نشد (owner=%s): %s", owner_id, fail_reason)
                await message.reply(
                    "❌ پیام شما الان به پشتیبانی نرسید.\n"
                    "<i>مالک ربات هنوز این ربات را استارت نکرده است؛"
                    " کمی بعد دوباره تلاش کنید.</i>",
                    reply_markup=main_keyboard(token),
                )
            return

        await message.reply(txt(token, "menu_hint"),
                            reply_markup=main_keyboard(token))

    # --------------------------------------- بستن نتایج جستجو
    async def on_srchclose(client: Client, cq):
        try:
            await cq.answer()
        except RPCError:
            pass
        try:
            await cq.message.delete()
        except RPCError:
            pass

    app.add_handler(MessageHandler(on_start, filters.command("start") & filters.private))
    app.add_handler(CallbackQueryHandler(on_checkjoin, filters.regex("^checkjoin$")))
    app.add_handler(CallbackQueryHandler(on_taskjoin, filters.regex("^taskjoin$")))
    app.add_handler(CallbackQueryHandler(on_refcancel, filters.regex("^refcancel$")))
    app.add_handler(CallbackQueryHandler(on_filevote,
                                         filters.regex(r"^fv:\d+:[01]$")))
    app.add_handler(CallbackQueryHandler(on_fget, filters.regex(r"^fget:\d+$")))
    app.add_handler(CallbackQueryHandler(on_srchclose, filters.regex("^srchclose$")))
    app.add_handler(
        MessageHandler(
            on_owner_reply,
            filters.private & filters.user(owner_id) & filters.reply,
        ),
        group=1,
    )
    app.add_handler(
        MessageHandler(on_message, filters.private & ~filters.command("start")),
        group=2,
    )
    return app
