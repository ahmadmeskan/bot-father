"""پنل‌های تکمیلی ربات مادر: پیام پایانی، وظیفه اجباری، متن‌ها و کاربران."""
from __future__ import annotations

import compat  # noqa: F401

import html
import logging
from datetime import datetime

from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import db
import manager
import media
from child import referrals, tasks
from child.runtime import TEXTS, normalize_channel

log = logging.getLogger("panels")

CANCEL_BTN = "❌ انصراف"
CANCEL_KB = ReplyKeyboardMarkup([[KeyboardButton(CANCEL_BTN)]], resize_keyboard=True)

# متن‌های قابل ویرایش: (کلید, عنوان, راهنمای متغیرها)
EDITABLE_TEXTS: list[tuple[str, str, str]] = [
    ("welcome", "👋 پیام خوش‌آمد (استارت)", "{name} {id}"),
    ("join_text", "📢 پیام عضویت اجباری", "{name} {count} {channels} {links}"),
    ("task_text", "🤜 پیام وظیفه اجباری", "{name} {id} {channel}"),
    ("footer_text", "🏁 پیام پایانی", "{name} {id}"),
    ("blocked_text", "⛔️ پیام کاربر مسدود", "—"),
    ("menu_hint", "💬 پیام راهنمای منو", "—"),
    ("support_prompt", "☎️ پیام درخواست پشتیبانی", "—"),
    ("support_sent", "✅ پیام تأیید ارسال پشتیبانی", "—"),
]
TEXT_BY_INDEX = {str(i): t for i, t in enumerate(EDITABLE_TEXTS)}

ACTIONS = {
    "ftr", "ftredit", "ftrdel",
    # وظیفه اجباری (تأیید عضویت + پنجره‌ی ۲ دقیقه)
    "tsk", "tskch", "tsktxt", "tskon", "tskdel", "tskreset",
    "txts", "txt", "txtedit", "txtdel",
    "usr", "usrsrch", "usrblk", "ublk", "uunblk", "ushow",
    "udm", "dmsg",                                            # پیام به کاربر خاص
    "ref", "refon", "refn", "reftxt", "refphoto", "refphotodel",  # زیرمجموعه‌گیری
    # قفل توکن زیرمجموعه‌گیری به‌ازای هر دکمه
    "btnref", "btnrefon", "btnrefn",
    # آمار کامل + راستی‌آزمایی
    "stat", "statchk", "statlist",
    # قابلیت‌های ربات
    "feat", "autodel", "fpass", "fpassdel", "rndon", "srchon", "demon", "voteon",
}
STEPS = {
    "ftr_text", "tsk_channel", "tsk_text",
    "txt_edit", "usr_search", "usr_block",
    "usr_dm_pick", "dm_msg",                                  # پیام به کاربر خاص
    "ref_count", "ref_text", "ref_photo",                     # زیرمجموعه‌گیری
    "btn_ref_count",  # تعداد توکن لازم برای یک دکمه خاص
    "autodel_secs",   # ثانیه‌ی حذف خودکار
    "fpass_set",      # تنظیم پسورد فایل‌ها
}


def _default_text(key: str) -> str:
    """متن پیش‌فرض کارخانه‌ای یک کلید."""
    if key == "task_text":
        return tasks.DEFAULT_TASK_TEXT
    if key == "join_text":
        from child.runtime import DEFAULT_JOIN_TEXT

        return DEFAULT_JOIN_TEXT
    return db.DEFAULT_SETTINGS.get(key, "") or TEXTS.get(key, "")


def _is_custom(token: str, key: str) -> bool:
    """آیا متن توسط سازنده تغییر داده شده؟ (مقایسه با پیش‌فرض)"""
    cur = db.get_setting(token, key, "")
    return bool(cur) and cur != db.DEFAULT_SETTINGS.get(key, "")


def _fa_date(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y/%m/%d %H:%M")


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _user_line(row) -> str:
    name = _esc(row["first_name"] or "بی‌نام")
    uname = f"@{row['username']}" if row["username"] else "—"
    return f"{name} | {uname} | <code>{row['user_id']}</code>"


def _forwarded_post(message: Message) -> tuple[int, int] | None:
    """اگر پیام فورواردیِ یک کانال/گروه باشد، (chat_id, msg_id) برمی‌گرداند.

    هر دو سبک را پشتیبانی می‌کند:
        • kurigram جدید: message.forward_origin (MessageOriginChannel)
        • فورک‌های قدیمی: message.forward_from_chat + forward_from_message_id
    """
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
        mid = int(getattr(origin, "message_id", 0) or 0)
        cid = int(getattr(chat, "id", 0) or 0) if chat is not None else 0
        if cid and mid:
            return cid, mid
        return None
    chat = getattr(message, "forward_from_chat", None)   # سازگاری با فورک قدیمی
    mid = int(getattr(message, "forward_from_message_id", 0) or 0)
    cid = int(getattr(chat, "id", 0) or 0) if chat is not None else 0
    if cid and mid:
        return cid, mid
    return None


# ══════════════════════════════════════════ ۱) پیام پایانی
def footer_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    current = db.get_setting(token, "footer_text", "")
    body = (f"متن فعلی:\n──────────\n{current}\n──────────"
            if current else "هنوز پیام پایانی تنظیم نشده است.")
    text = (
        "🏁 <b>پیام پایانی</b>\n\n"
        "این پیام بعد از محتوای <b>هر دکمه</b> برای کاربر ارسال می‌شود.\n"
        f"متغیرها: <code>{{name}}</code> <code>{{id}}</code>\n\n" + body
    )
    rows = [[InlineKeyboardButton("✏️ ویرایش متن", callback_data=f"ftredit:{tid}")]]
    if current:
        rows.append([InlineKeyboardButton("🗑 حذف پیام پایانی",
                                          callback_data=f"ftrdel:{tid}")])
    rows.append([InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")])
    return text, InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════ ۲) وظیفه اجباری
def task_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    """پنل وظیفه اجباری — مدل «تأیید عضویت + پنجره‌ی ۲ دقیقه‌ای»."""
    cfg = tasks.config(token)
    ready = bool(cfg["channel"])
    status = "🟢 روشن" if (cfg["enabled"] and ready) else "🔴 خاموش"

    text = (
        "🤜 <b>وظیفه اجباری</b>\n\n"
        "از این قسمت می‌توانید کاربر را مجبور کنید که برای دریافت فایل شما "
        "ابتدا در کانالِ خواسته عضو شود.\n\n"
        "توضیح رفتار:\n"
        "• کاربر با زدن هر دکمه‌ای، اگر در <b>۲ دقیقه‌ی اخیر</b> وظیفه را "
        "تأیید کرده باشد، مستقیم فایل را می‌گیرد.\n"
        "• در غیر این صورت عضویتش در کانال بررسی می‌شود؛ عضو بود → فایل "
        "می‌گیرد و تأییدش ۲ دقیقه اعتبار دارد.\n"
        "• عضو نبود → پیام وظیفه با دکمه‌ی «✅ عضو شدم» می‌بیند؛ بعد از "
        "عضویت واقعی، همان فایل برایش ارسال می‌شود.\n"
        "──────────────\n"
        f"وضعیت: <b>{status}</b>\n"
        f"کانال خواسته: <code>{cfg['channel'] or '—'}</code>\n"
        f"متن: {'سفارشی ✏️' if db.get_setting(token, 'task_text', '') else 'پیش‌فرض'}\n"
        f"تعداد تأیید وظیفه تا حالا: <b>{db.task_completions(token)}</b>\n"
        "──────────────\n"
        "⚠️ برای بررسی عضویت، این ربات فرزند باید <b>ادمین</b> کانال خواسته باشد."
    )
    rows = [
        [InlineKeyboardButton("📢 کانال خواسته", callback_data=f"tskch:{tid}")],
        [InlineKeyboardButton("✏️ متن پیام وظیفه", callback_data=f"tsktxt:{tid}")],
        [InlineKeyboardButton("🔴 خاموش کردن" if cfg["enabled"] else "🟢 روشن کردن",
                              callback_data=f"tskon:{tid}")],
        [InlineKeyboardButton("♻️ صفر کردن تأیید همه", callback_data=f"tskreset:{tid}")],
        [InlineKeyboardButton("🗑 حذف وظیفه", callback_data=f"tskdel:{tid}")],
        [InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")],
    ]
    return text, InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════ ۳) زیرمجموعه‌گیری
def ref_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    cfg = referrals.config(token)
    status = "🟢 فعال" if cfg["enabled"] else "🔴 غیرفعال"
    photo = "🖼 تنظیم شده" if cfg["photo"] else "—"
    t_total, t_used, t_unused = db.token_totals(token)
    text = (
        "👥 <b>زیرمجموعه‌گیری (مدل توکن)</b>\n\n"
        "هر زیرمجموعه‌ای که کاربر با لینک دعوتش بیاورد = <b>۱ توکن</b> در "
        "استخر کلی خودش (به هیچ دکمه‌ای گره نمی‌خورد).\n"
        "• باز کردن هر دکمه‌ی قفل‌دار به اندازه‌ی «تعداد لازم» همان دکمه "
        "توکن <b>مصرف‌شده</b> می‌کند (توکن سوخته برنمی‌گردد).\n"
        "• توکن کافی نباشد، دکمه در انتظار می‌ماند و چیزی نمی‌سوزد؛ با هر "
        "دعوت جدید، دوباره همان دکمه را بزند باز می‌شود.\n"
        "• دکمه‌ای که یک بار باز شده، برای همان کاربر باز می‌ماند.\n"
        "قفل کردن هر دکمه و تعداد لازمش از پنل «🔘 دکمه‌ها» (دکمه‌ی 🎁 هر "
        "دکمه) انجام می‌شود؛ این پنل <b>کلید اصلی</b> و <b>تعداد پیش‌فرض</b> "
        "را تعیین می‌کند.\n"
        "──────────────\n"
        f"وضعیت کلید اصلی: <b>{status}</b>\n"
        f"تعداد پیش‌فرض (برای دکمه‌های بدون تعداد جدا): <b>{cfg['count'] or '—'}</b>\n"
        f"عکس پیام دعوت: <b>{photo}</b>\n"
        f"متن: {'سفارشی ✏️' if db.get_setting(token, 'ref_text', '') else 'پیش‌فرض'}\n"
        "──────────────\n"
        "🪙 <b>استخر توکن کل ربات</b>\n"
        f"├─ مجموع: <b>{t_total}</b>\n"
        f"├─ 🔥 مصرف‌شده: <b>{t_used}</b>\n"
        f"└─ ♻️ مصرف‌نشده: <b>{t_unused}</b>\n"
        "──────────────\n"
        "ℹ️ هر کاربرِ <b>جدید</b> فقط برای اولین دعوت‌کننده‌اش شمرده می‌شود "
        "و دعوت‌کننده باید خودش ربات را استارت کرده باشد. کاربران فقط "
        "شمارش کلی زیرمجموعه‌شان را می‌بینند؛ تفکیک بالا فقط برای شماست."
    )
    rows = [
        [InlineKeyboardButton("🔢 تعداد پیش‌فرض", callback_data=f"refn:{tid}"),
         InlineKeyboardButton("✏️ متن", callback_data=f"reftxt:{tid}")],
        [InlineKeyboardButton("🖼 تنظیم عکس", callback_data=f"refphoto:{tid}"),
         InlineKeyboardButton("🗑 حذف عکس", callback_data=f"refphotodel:{tid}")],
        [InlineKeyboardButton("🔴 غیرفعال کن" if cfg["enabled"] else "🟢 فعال کن",
                              callback_data=f"refon:{tid}")],
        [InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")],
    ]
    return text, InlineKeyboardMarkup(rows)


# ═══════════════════ قفل توکن زیرمجموعه‌گیری یک دکمه‌ی خاص (per-button)
def btn_ref_view(token: str, tid: str, bid: int) -> tuple[str, InlineKeyboardMarkup]:
    """پنل قفل توکن برای یک دکمه: روشن/خاموش + تعداد لازم مخصوص همان دکمه."""
    back = [[InlineKeyboardButton("« دکمه‌ها", callback_data=f"btns:{tid}")]]
    btn = db.button_by_id(token, bid)
    if not btn:
        return ("این دکمه دیگر وجود ندارد.", InlineKeyboardMarkup(back))
    cfg = referrals.config(token)
    try:
        req = int(btn["ref_req"] or 0)
        own = int(btn["ref_count"] or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        req, own = 0, 0
    need = referrals.need_for(token, btn)
    if req != 1:
        status = "🔴 قفل خاموش — همه می‌توانند این دکمه را باز کنند"
    else:
        status = (f"🟢 قفل فعال — باز کردن این دکمه <b>{need}</b> توکنِ"
                  " مصرف‌نشده می‌سوزاند")
    master_note = ("✅ روشن" if cfg["enabled"] else
                   "🔴 خاموش — برای اینکه قفل‌ها کار کنند روشنش کنید"
                   " (با روشن‌کردن قفلِ همین دکمه خودکار روشن می‌شود)")
    text = (
        f"🎁 <b>قفل توکن دکمه «{_esc(btn['title'])}»</b>\n\n"
        "اگر قفل روشن باشد، باز کردن این دکمه به اندازه‌ی تعداد تعیین‌شده "
        "توکن مصرف‌نشده از استخر کلی کاربر می‌سوزاند؛ توکن‌ها بین همه‌ی "
        "دکمه‌ها مشترک‌اند و دکمه بعد از باز شدن برای همان کاربر باز می‌ماند.\n"
        "──────────────\n"
        f"وضعیت: <b>{status}</b>\n"
        f"تعداد لازم برای همین دکمه: <b>{own if own else '— (مثل تعداد کلی)'}</b>\n"
        f"کلید اصلی زیرمجموعه‌گیری: {master_note}\n"
        "──────────────\n"
        "برای قفل‌کردن دکمه‌های دیگر، در «🔘 دکمه‌ها» روی 🎁 همان دکمه بزنید."
    )
    rows = [
        [InlineKeyboardButton("🔓 خاموش کردن قفل" if req == 1 else "🔒 روشن کردن قفل",
                              callback_data=f"btnrefon:{tid}:{bid}")],
        [InlineKeyboardButton("🔢 تعداد لازم این دکمه",
                              callback_data=f"btnrefn:{tid}:{bid}")],
        back[0],
    ]
    return text, InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════ ۴) متن‌های ربات
def texts_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for i, (key, title, _) in enumerate(EDITABLE_TEXTS):
        mark = "✏️" if _is_custom(token, key) else "▫️"
        rows.append([InlineKeyboardButton(f"{mark} {title}",
                                          callback_data=f"txt:{tid}:{i}")])
    rows.append([InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")])
    return (
        "📝 <b>متن‌های ربات</b>\n\n"
        "✏️ = سفارشی‌شده     ▫️ = پیش‌فرض\n"
        "برای تغییر، روی هرکدام بزنید.",
        InlineKeyboardMarkup(rows),
    )


def text_detail(token: str, tid: str, idx: str) -> tuple[str, InlineKeyboardMarkup]:
    key, title, vars_ = TEXT_BY_INDEX[idx]
    custom = _is_custom(token, key)
    current = _esc(db.get_setting(token, key, "") if custom
                   else _default_text(key)) or "(خالی — این قابلیت خاموش است)"
    rows = [[InlineKeyboardButton("✏️ ویرایش", callback_data=f"txtedit:{tid}:{idx}")]]
    if custom:
        rows.append([InlineKeyboardButton("♻️ بازگشت به پیش‌فرض",
                                          callback_data=f"txtdel:{tid}:{idx}")])
    rows.append([InlineKeyboardButton("« متن‌ها", callback_data=f"txts:{tid}")])
    return (
        f"<b>{title}</b>\n\n"
        f"متغیرها: <code>{vars_}</code>\n"
        "──────────\n"
        f"{current}\n"
        "──────────",
        InlineKeyboardMarkup(rows),
    )


# ══════════════════════════════════════════ ۴) کاربران
def users_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    total = db.bot_user_count(token)
    blocked = db.blocked_count(token)
    text = (
        "👥 <b>مدیریت کاربران</b>\n"
        "──────────────\n"
        f"کل کاربران: <b>{total}</b>\n"
        f"مسدودشده: <b>{blocked}</b>\n"
        f"فعال: <b>{total - blocked}</b>\n"
        "──────────────"
    )
    rows = [
        [InlineKeyboardButton("🔍 جستجوی کاربر", callback_data=f"usrsrch:{tid}")],
        # قابلیت جدید: ارسال پیام مستقیم به یک کاربر مشخص
        [InlineKeyboardButton("✉️ پیام به کاربر خاص", callback_data=f"udm:{tid}")],
        [InlineKeyboardButton(f"⛔️ مسدودشده‌ها ({blocked})",
                              callback_data=f"usrblk:{tid}")],
        [InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")],
    ]
    return text, InlineKeyboardMarkup(rows)


def blocked_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    rows_db = db.blocked_users(token)
    if not rows_db:
        text = "⛔️ <b>کاربران مسدود</b>\n\nهیچ کاربری مسدود نیست."
    else:
        lines = []
        for i, r in enumerate(rows_db[:30], 1):
            lines.append(
                f"{i}. {_user_line(r)}\n"
                f"    📅 {_fa_date(r['blocked_at'])}"
                + (f" | توسط <code>{r['blocked_by']}</code>" if r["blocked_by"] else "")
            )
        text = ("⛔️ <b>کاربران مسدود</b> "
                f"({len(rows_db)})\n──────────────\n" + "\n".join(lines))
        if len(rows_db) > 30:
            text += f"\n\n… و {len(rows_db) - 30} کاربر دیگر"
    kb = [[InlineKeyboardButton(f"♻️ رفع مسدودی {r['user_id']}",
                                callback_data=f"uunblk:{tid}:{r['user_id']}")]
          for r in rows_db[:10]]
    kb.append([InlineKeyboardButton("« کاربران", callback_data=f"usr:{tid}")])
    return text, InlineKeyboardMarkup(kb)


def user_card(token: str, tid: str, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    row = db.get_bot_user(token, user_id)
    if not row:
        return "کاربر پیدا نشد.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("« کاربران", callback_data=f"usr:{tid}")]])
    # وظیفه‌ی جدید: زمانِ آخرین تأیید وظیفه (پنجره‌ی ۲ دقیقه‌ای)
    last_verified = db.task_verified_at(token, user_id)
    demo = f"{row['age'] or '—'} ساله" if row["age"] else "—"
    gender = {"m": "👨 مرد", "f": "👩 زن"}.get(row["gender"] or "", "—")
    t_total, t_used, t_unused = db.token_stats(token, user_id)
    text = (
        "👤 <b>پرونده کاربر</b>\n"
        "──────────────\n"
        f"نام: {_esc(row['first_name'])}\n"
        f"یوزرنیم: {'@' + row['username'] if row['username'] else '—'}\n"
        f"آیدی: <code>{row['user_id']}</code>\n"
        f"عضویت در ربات: {_fa_date(row['joined_at'])}\n"
        f"وضعیت: {'⛔️ مسدود از ' + _fa_date(row['blocked_at']) if row['blocked'] else '✅ فعال'}\n"
        f"سن/جنسیت: {demo} / {gender}\n"
        f"🪙 توکن‌ها — کل: <b>{t_total}</b> | 🔥 سوخته: <b>{t_used}</b>"
        f" | ♻️ آزاد: <b>{t_unused}</b>\n"
        f"آخرین تأیید وظیفه: {_fa_date(int(last_verified / 1000)) if last_verified else '—'}\n"
        "──────────────"
    )
    if row["blocked"]:
        act = InlineKeyboardButton("♻️ رفع مسدودی",
                                   callback_data=f"uunblk:{tid}:{user_id}")
    else:
        act = InlineKeyboardButton("⛔️ مسدود کردن",
                                   callback_data=f"ublk:{tid}:{user_id}")
    return text, InlineKeyboardMarkup([
        [act],
        # قابلیت جدید: ارسال پیام مستقیم مالک به همین کاربر
        [InlineKeyboardButton("✉️ ارسال پیام به این کاربر",
                              callback_data=f"dmsg:{tid}:{user_id}")],
        [InlineKeyboardButton("🔍 جستجوی دیگر", callback_data=f"usrsrch:{tid}")],
        [InlineKeyboardButton("« کاربران", callback_data=f"usr:{tid}")],
    ])


# ════════════════════════════════════════ ۵) آمار کامل ربات
def _onoff(v: bool, on: str = "✅ روشن", off: str = "🚫 خاموش") -> str:
    return on if v else off


def stats_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    """پنل آمار کامل — طراحی جدید با بلوک‌های خوانا و جداکننده‌های ظریف."""
    total, active, inactive = db.active_counts(token)
    jb = db.join_buckets(token)
    demo_on = db.get_setting(token, "demo_ask", "0") == "1"
    demo = db.demo_stats(token)
    files = len(db.buttons(token))
    views = db.views_total(token)
    likes, dislikes = db.votes_total(token)

    # ── دموگرافیک ──
    if not demo_on:
        demo_line = ("┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                     "🔕 <i>گزارش سن و جنسیت خاموش است —"
                     " از ⚙️ قابلیت‌ها فعالش کنید</i>")
    elif demo["asked"] == 0:
        demo_line = ("┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                     "⊲ هنوز پاسخی ثبت نشده — پس از اولین بازدید کاربران"
                     " کامل می‌شود ⊳")
    else:
        avg = f"{demo['avg_age']:.1f}".rstrip("0").rstrip(".")
        m, f = demo["male"], demo["female"]
        m_pct = round(m * 100 / (m + f), 1) if (m + f) else 0.0
        f_pct = round(100 - m_pct, 1) if (m + f) else 0.0
        # نوار پیشرفت جنسیت
        bar_len = 10
        m_blocks = round(m_pct / 100 * bar_len) if (m + f) else 0
        bar = "▮" * m_blocks + "▯" * (bar_len - m_blocks)
        demo_line = (
            f"🎂 میانگین سنی: <b>{avg}</b> سال\n"
            f"⚥ <b>{m_pct}٪</b> مرد ⁄ <b>{f_pct}٪</b> زن\n"
            f"<code>{bar}</code>\n"
            f"📋 <i>{m + f} پاسخ از {total} کاربر</i>"
        )

    # ── مشخصات ربات ──
    row = db.get_bot(token)
    bot_id = row["bot_id"] if row else "—"
    owner_id = row["owner_id"] if row else "—"
    running = manager.is_running(token)
    task_cfg = tasks.config(token)
    task_on = task_cfg["enabled"] and bool(task_cfg["channel"])
    try:
        autodel = int(db.get_setting(token, "autodel", "0") or 0)
    except ValueError:
        autodel = 0
    fpass = bool(db.get_setting(token, "file_pass", "").strip())
    rnd = db.get_setting(token, "rnd_enabled", "0") == "1"
    srch = db.get_setting(token, "search_enabled", "0") == "1"
    votes_on = db.get_setting(token, "votes_enabled", "1") == "1"

    def toggle(on: bool, extra: str = "") -> str:
        return ("🟢 " + (extra or "فعال")) if on else ("⚪️ " + (extra or "غیرفعال"))

    autodel_line = (
        f"{'🟢' if autodel > 0 else '⚪️'} حذف خودکار: "
        f"<b>{autodel} ثانیه</b>" if autodel > 0
        else f"{'⚪️'} حذف خودکار: <b>خاموش</b>"
    )

    text = (
        "📊 <b>آمار ربات</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "👥 <b>کاربران</b>\n"
        f"├─ مجموع: <b>{total}</b>\n"
        f"├─ 🟢 فعال: <b>{active}</b>\n"
        f"└─ 🔴 مسدود: <b>{inactive}</b>\n"
        "\n"
        "⏱ <b>ورود کاربران</b>\n"
        f"├─ ساعت: <b>{jb['hour']}</b>\n"
        f"├─ ۵ ساعت: <b>{jb['five_hours']}</b>\n"
        f"├─ روز: <b>{jb['day']}</b>\n"
        f"├─ هفته: <b>{jb['week']}</b>\n"
        f"└─ ماه: <b>{jb['month']}</b>\n"
        "\n"
        "🎂 <b>دموگرافیک</b>\n"
        f"{demo_line}\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        "📂 <b>فایل‌ها</b>\n"
        f"├─ تعداد: <b>{files}</b>\n"
        f"├─ 👁 بازدید: <b>{views}</b>\n"
        f"├─ 👍 لایک: <b>{likes}</b>\n"
        f"└─ 👎 دیسلایک: <b>{dislikes}</b>\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        "⚙️ <b>قابلیت‌ها</b>\n"
        f"{'🟢' if running else '🔴'} ربات: <b>{'روشن' if running else 'خاموش'}</b>\n"
        f"{autodel_line}\n"
        f"{'🟢' if fpass else '⚪️'} پسورد فایل‌ها: "
        f"<b>{'فعال' if fpass else 'خاموش'}</b>\n"
        f"{'🟢' if task_on else '⚪️'} وظیفه اجباری: "
        f"<b>{'فعال' if task_on else 'خاموش'}</b>"
        f" (<b>{db.task_completions(token)}</b> تأیید)\n"
        f"{'🟢' if rnd else '⚪️'} فایل رندوم: "
        f"<b>{'فعال' if rnd else 'خاموش'}</b>\n"
        f"{'🟢' if srch else '⚪️'} جستجوی فایل: "
        f"<b>{'فعال' if srch else 'خاموش'}</b>\n"
        f"{'🟢' if votes_on else '⚪️'} لایک/دیسلایک: "
        f"<b>{'فعال' if votes_on else 'خاموش'}</b>\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        "🤖 <b>مشخصات</b>\n"
        f"├─ 🆔 آیدی: <code>{bot_id}</code>\n"
        f"└─ 👑 مالک: <code>{owner_id}</code>\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    rows = [
        [InlineKeyboardButton("🔗 راستی‌آزمایی آمار", callback_data=f"statchk:{tid}")],
        [InlineKeyboardButton("🆕 جدیدترین", callback_data=f"statlist:{tid}:newest"),
         InlineKeyboardButton("👁 پربازدید", callback_data=f"statlist:{tid}:views")],
        [InlineKeyboardButton("👍 محبوب‌ترین", callback_data=f"statlist:{tid}:likes"),
         InlineKeyboardButton("👎 منفورترین", callback_data=f"statlist:{tid}:dislikes")],
        [InlineKeyboardButton("⚙️ قابلیت‌ها", callback_data=f"feat:{tid}"),
         InlineKeyboardButton("♻️ به‌روزرسانی", callback_data=f"stat:{tid}")],
        [InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")],
    ]
    return text, InlineKeyboardMarkup(rows)


def statlist_view(token: str, tid: str, mode: str) -> tuple[str, InlineKeyboardMarkup]:
    """لیست فایل‌ها با ترتیب دلخواه (جدیدترین/قدیمی‌ترین/پربازدید/…)."""
    titles = {"newest": "🆕 جدیدترین فایل‌ها", "oldest": "📜 قدیمی‌ترین فایل‌ها",
              "views": "👁 پربازدیدترین فایل‌ها", "likes": "👍 محبوب‌ترین فایل‌ها",
              "dislikes": "👎 منفورترین فایل‌ها"}
    rows_db = db.buttons_ranked(token, mode, limit=10)
    if not rows_db:
        body = "هنوز فایلی ثبت نشده است."
    else:
        lines = []
        for i, b in enumerate(rows_db, 1):
            extra = ""
            if mode == "views":
                extra = f" — 👁 {b['views']}"
            elif mode == "likes":
                extra = f" — 👍 {b['likes']}"
            elif mode == "dislikes":
                extra = f" — 👎 {b['dislikes']}"
            lines.append(f"{i}. {_esc(b['title'])}{extra}")
        body = "\n".join(lines)
    text = f"<b>{titles.get(mode, 'فایل‌ها')}</b>\n──────────────\n{body}"
    kb = [[InlineKeyboardButton("« آمار", callback_data=f"stat:{tid}")]]
    return text, InlineKeyboardMarkup(kb)


async def stats_verify(token: str, client: Client | None) -> str:
    """🔗 راستی‌آزمایی آمار — همه‌ی عددها مستقیم از دیتابیس دوباره شمرده
    می‌شوند و سازگاری‌شان با هم بررسی می‌شود تا مطمئن شویم آمارِ
    نمایش‌داده‌شده واقعی است (نه عددی از کار افتاده)."""
    problems: list[str] = []
    lines = ["🔗 <b>راستی‌آزمایی آمار</b>", "──────────────"]

    def ok(msg: str) -> None:
        lines.append(f"✅ {msg}")

    def bad(msg: str) -> None:
        problems.append(msg)
        lines.append(f"❌ {msg}")

    def warn(msg: str) -> None:
        lines.append(f"⚠️ {msg}")

    # ۱) سازگاری فعال/غیرفعال با کل
    total, active, inactive = db.active_counts(token)
    raw_total = db.bot_user_count(token)
    if total == active + inactive == raw_total:
        ok(f"کاربران: کل {total} = فعال {active} + غیرفعال {inactive}")
    else:
        bad(f"کاربران ناسازگارند: کل {total}، فعال {active}،"
            f" غیرفعال {inactive}، رکورد {raw_total}")

    # ۲) بازه‌های زمانی باید صعودی و داخل کل باشند
    jb = db.join_buckets(token)
    seq = [jb["hour"], jb["five_hours"], jb["day"], jb["week"], jb["month"]]
    if all(a <= b for a, b in zip(seq, seq[1:])) and jb["month"] <= total:
        ok(f"بازه‌های زمانی سازگارند (ماه: {jb['month']} ≤ کل: {total})")
    else:
        bad(f"بازه‌های زمانی ناسازگارند: {seq}")

    # ۳) دموگرافیک
    demo = db.demo_stats(token)
    if demo["male"] + demo["female"] == demo["asked"] and demo["asked"] <= total:
        if demo["asked"]:
            ok(f"دموگرافیک سازگار است ({demo['asked']} پاسخ از {total} کاربر)")
        else:
            warn("دموگرافیک هنوز داده‌ای ندارد (طبیعی است اگر تازه فعال شده)")
    else:
        bad("دموگرافیک ناسازگار است (مجموع جنسیت‌ها با تعداد پاسخ نمی‌خواند)")
    if demo["avg_age"] is not None and not (5 <= demo["avg_age"] <= 120):
        bad(f"میانگین سنی غیرمنطقی است: {demo['avg_age']:.1f}")

    # ۴) فایل‌ها: رأی‌ها و بازدیدها
    likes, dislikes = db.votes_total(token)
    votes_rows = db.fetchone(
        "SELECT COUNT(*) c FROM file_votes WHERE token=?", (token,))["c"]
    views = db.views_total(token)
    if likes + dislikes == votes_rows:
        ok(f"رأی‌ها سازگارند (👍{likes} + 👎{dislikes} = {votes_rows} رکورد)")
    else:
        bad("شمارش لایک/دیسلایک با رکوردهای دیتابیس نمی‌خواند")
    if votes_rows > views:
        warn(f"رأی‌ها ({votes_rows}) بیشتر از بازدیدها ({views}) است — "
             "اگر آمار تازه فعال شده طبیعی است")

    # ۵) وظیفه اجباری
    comp = db.task_completions(token)
    users_done = db.task_verified_users_count(token)
    if comp >= users_done:
        ok(f"شمارنده وظیفه درست است ({comp} تأیید، {users_done} کاربر)")
    else:
        bad("شمارنده «تعداد تأیید وظیفه» از تعداد کاربرانِ تأییدشده کمتر است")

    # ۶) زیرمجموعه‌ها: همه باید در جدول کاربران باشند
    orphans = db.fetchall(
        "SELECT COUNT(*) c FROM referrals r"
        " WHERE r.token=? AND (NOT EXISTS"
        "   (SELECT 1 FROM bot_users u WHERE u.token=r.token"
        "      AND u.user_id=r.inviter_id)"
        "  OR NOT EXISTS"
        "   (SELECT 1 FROM bot_users u WHERE u.token=r.token"
        "      AND u.user_id=r.invited_id))",
        (token,),
    )[0]["c"]
    if orphans == 0:
        ok(f"زیرمجموعه‌ها: {db.referral_total(token)} دعوت ثبت شده، بدون رکورد یتیم")
    else:
        bad(f"زیرمجموعه‌ها: {orphans} رکورد یتیم پیدا شد")

    # ۷) رکوردهای یتیم آمار فایل‌ها
    st_orphans = db.fetchone(
        "SELECT COUNT(*) c FROM file_stats s WHERE s.token=? AND NOT EXISTS"
        " (SELECT 1 FROM buttons b WHERE b.token=s.token AND b.id=s.button_id)",
        (token,))["c"]
    vt_orphans = db.fetchone(
        "SELECT COUNT(*) c FROM file_votes v WHERE v.token=? AND NOT EXISTS"
        " (SELECT 1 FROM buttons b WHERE b.token=v.token AND b.id=v.button_id)",
        (token,))["c"]
    if st_orphans + vt_orphans == 0:
        ok("آمار فایل‌ها بدون رکورد یتیم است")
    else:
        bad(f"رکورد یتیم آمار فایل‌ها (بازدید: {st_orphans}، رأی: {vt_orphans})")

    # ۸) سلامت تنظیمات
    cfg_t = tasks.config(token)
    cfg_r = referrals.config(token)
    if (not cfg_t["enabled"] or bool(cfg_t["channel"])
            and 0 <= cfg_r["count"] <= 100):
        ok("تنظیمات وظیفه/زیرمجموعه در محدوده‌ی مجازند")
    else:
        bad("یکی از تنظیمات وظیفه/زیرمجموعه خارج از محدوده است")

    # ۸-ب) استخر توکن‌ها: مجموع باید با کل دعوت‌ها بخواند
    t_total, t_used, t_unused = db.token_totals(token)
    if t_total == db.referral_total(token) and t_total == t_used + t_unused:
        ok(f"توکن‌ها سازگارند (کل {t_total} = سوخته {t_used} + آزاد {t_unused})")
    else:
        bad("شمارش توکن‌ها با رکوردهای دعوت نمی‌خواند")

    # ۹) سلامت فایل دیتابیس
    try:
        q = db.fetchone("PRAGMA quick_check", ())["quick_check"]
        if q == "ok":
            ok("دیتابیس: quick_check = ok")
        else:
            bad(f"دیتابیس: quick_check = {q}")
    except Exception:  # noqa: BLE001
        ok("دیتابیس قابل خواندن است")

    # ۱۰) بررسی زنده‌ی ربات فرزند
    if client is not None:
        try:
            me = await client.get_me()
            row = db.get_bot(token)
            if row and int(row["bot_id"] or 0) == int(me.id):
                ok(f"ربات فرزند روشن است و هویتش تأیید شد (@{me.username})")
            else:
                bad("کلاینتِ در حال اجرا با ربات ثبت‌شده یکی نیست!")
        except Exception as e:  # noqa: BLE001
            warn(f"بررسی زنده‌ی ربات ممکن نشد: {_esc(e)}")
    else:
        warn("ربات فرزند خاموش است؛ وضعیت «روشن» در آمار لحظه‌ای نیست")

    lines.append("──────────────")
    if problems:
        lines.append(f"نتیجه: ❌ {len(problems)} ناسازگاری پیدا شد"
                     " — موارد بالا را بررسی کنید.")
    else:
        lines.append("نتیجه: ✅ همه‌ی آمارها راستی‌آزمایی شدند و سالم‌اند.")
    return "\n".join(lines)


# ════════════════════════════════════════ ۶) قابلیت‌های ربات
def feat_view(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    """پنل مدیریت قابلیت‌ها: حذف خودکار، پسورد، رندوم، سرچ، دموگرافیک، رأی."""
    try:
        autodel = int(db.get_setting(token, "autodel", "0") or 0)
    except ValueError:
        autodel = 0
    fpass = bool(db.get_setting(token, "file_pass", "").strip())
    rnd = db.get_setting(token, "rnd_enabled", "0") == "1"
    srch = db.get_setting(token, "search_enabled", "0") == "1"
    demo = db.get_setting(token, "demo_ask", "0") == "1"
    votes = db.get_setting(token, "votes_enabled", "1") == "1"

    text = (
        "⚙️ <b>قابلیت‌های ربات</b>\n\n"
        "🗑️ <b>حذف خودکار</b>: "
        + (_onoff(True, f"✅ روشن — محتوا بعد از {autodel} ثانیه پاک می‌شود")
           if autodel > 0 else "🚫 خاموش") + "\n"
        "🔑 <b>پسورد فایل‌ها</b>: "
        + (_onoff(True, "✅ فعال — کاربر باید یک‌بار رمز بفرستد")
           if fpass else "🚫 غیرفعال") + "\n"
        f"🎲 <b>فایل رندوم</b>: {_onoff(rnd)} — دکمه‌ی ارسال فایل تصادفی در منو\n"
        f"🔍 <b>فایل با سرچ</b>: {_onoff(srch)} — دکمه‌ی جستجوی فایل در منو\n"
        "🎂 <b>سن و جنسیت</b>: " + _onoff(demo)
        + " — پرسیدن از کاربران جدید برای آمار دموگرافیک\n"
        "👍👎 <b>لایک/دیسلایک</b>: " + _onoff(votes)
        + " — دکمه‌ی رأی زیر فایل‌ها\n"
        "──────────────\n"
        "ℹ️ با فعال‌شدن رندوم/سرچ، دکمه‌های جدید در منوی کاربران از پیام بعدی"
        " دیده می‌شوند."
    )
    rows = [
        [InlineKeyboardButton("🗑 حذف خودکار: "
                              + (f"{autodel} ثانیه" if autodel else "خاموش"),
                              callback_data=f"autodel:{tid}"),
         InlineKeyboardButton("🔑 پسورد: " + ("روشن" if fpass else "خاموش"),
                              callback_data=f"fpass:{tid}")],
        [InlineKeyboardButton("🎲 فایل رندوم: " + ("روشن ✅" if rnd else "خاموش 🚫"),
                              callback_data=f"rndon:{tid}"),
         InlineKeyboardButton("🔍 سرچ فایل: " + ("روشن ✅" if srch else "خاموش 🚫"),
                              callback_data=f"srchon:{tid}")],
        [InlineKeyboardButton("🎂 سن و جنسیت: " + ("روشن ✅" if demo else "خاموش 🚫"),
                              callback_data=f"demon:{tid}"),
         InlineKeyboardButton("👍👎 لایک: " + ("روشن ✅" if votes else "خاموش 🚫"),
                              callback_data=f"voteon:{tid}")],
        [InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")],
    ]
    return text, InlineKeyboardMarkup(rows)


# ══════════════════════════════════════ مدیریت کال‌بک‌ها
async def handle_callback(client: Client, cq: CallbackQuery, token: str, tid: str,
                          extra: str, state_store: dict) -> bool:
    action = (cq.data or "").split(":")[0]
    uid = cq.from_user.id

    async def edit(pair):
        text, kb = pair
        # fix: اگر کال‌بک قبلاً جواب داده شده باشد (مثلاً با هشدار «حذف شد»)،
        # جوابِ دوم خطای QUERY_ID_INVALID می‌داد و پنل اصلاً رفرش نمی‌شد.
        try:
            await cq.answer()
        except RPCError:
            pass
        try:
            await cq.message.edit_text(text, reply_markup=kb,
                                       disable_web_page_preview=True)
        except Exception:  # noqa: BLE001
            await cq.message.reply(text, reply_markup=kb,
                                   disable_web_page_preview=True)

    # ── پیام پایانی ──
    if action == "ftr":
        await edit(footer_view(token, tid))
        return True
    if action == "ftredit":
        state_store[uid] = {"step": "ftr_text", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "متن پیام پایانی را بفرستید.\n"
            "متغیرها: <code>{name}</code> <code>{id}</code>",
            reply_markup=CANCEL_KB)
        return True
    if action == "ftrdel":
        db.set_setting(token, "footer_text", "")
        await cq.answer("پیام پایانی حذف شد 🗑")
        await edit(footer_view(token, tid))
        return True

    # ── وظیفه اجباری ──
    if action == "tsk":
        await edit(task_view(token, tid))
        return True
    if action == "tskch":
        state_store[uid] = {"step": "tsk_channel", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "لینک یا یوزرنیم کانالِ «خواسته» را بفرستید"
            " (مثل <code>@mychannel</code>).\n\n"
            "عضویت کاربران در این کانال بررسی می‌شود؛ عضو که شد، فایل را "
            "می‌گیرد و تأییدش ۲ دقیقه اعتبار دارد.\n"
            "⚠️ ربات فرزند باید <b>ادمین</b> این کانال باشد.",
            reply_markup=CANCEL_KB)
        return True
    if action == "tsktxt":
        state_store[uid] = {"step": "tsk_text", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "متن پیام وظیفه را بفرستید.\n"
            "متغیرها: <code>{name} {id} {channel}</code>\n"
            "برای بازگشت به پیش‌فرض <code>پیش‌فرض</code> بفرستید.",
            reply_markup=CANCEL_KB)
        return True
    if action == "tskon":
        cfg = tasks.config(token)
        if not cfg["enabled"]:
            if not cfg["channel"]:
                await cq.answer("اول «کانال خواسته» را تنظیم کنید.", show_alert=True)
                return True
        db.set_setting(token, "task_enabled", "0" if cfg["enabled"] else "1")
        await cq.answer("تغییر کرد ✅")
        await edit(task_view(token, tid))
        return True

    if action == "tskreset":
        db.reset_tasks(token)
        await cq.answer("تأیید همه کاربران صفر شد ♻️")
        await edit(task_view(token, tid))
        return True
    if action == "tskdel":
        for k, v in (("task_enabled", "0"), ("task_channel", ""),
                     ("task_channel_id", ""), ("task_text", ""),
                     ("task_completions", "0")):
            db.set_setting(token, k, v)
        db.reset_tasks(token)
        await cq.answer("وظیفه حذف شد 🗑")
        await edit(task_view(token, tid))
        return True

    # ── متن‌ها ──
    if action == "txts":
        await edit(texts_view(token, tid))
        return True
    if action == "txt":
        if extra not in TEXT_BY_INDEX:
            await cq.answer("نامعتبر")
            return True
        await edit(text_detail(token, tid, extra))
        return True
    if action == "txtedit":
        key, title, vars_ = TEXT_BY_INDEX[extra]
        state_store[uid] = {"step": "txt_edit", "token": token, "tid": tid, "key": key}
        await cq.answer()
        await cq.message.reply(
            f"متن جدید برای «{title}» را بفرستید.\n"
            f"متغیرها: <code>{vars_}</code>\n"
            "برای بازگشت به پیش‌فرض <code>پیش‌فرض</code> بفرستید.",
            reply_markup=CANCEL_KB)
        return True
    if action == "txtdel":
        key = TEXT_BY_INDEX[extra][0]
        db.set_setting(token, key, db.DEFAULT_SETTINGS.get(key, ""))
        await cq.answer("به پیش‌فرض برگشت ♻️")
        await edit(text_detail(token, tid, extra))
        return True

    # ── کاربران ──
    if action == "usr":
        await edit(users_view(token, tid))
        return True
    if action == "usrsrch":
        state_store[uid] = {"step": "usr_search", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "🔍 آیدی عددی، یوزرنیم یا بخشی از نام کاربر را بفرستید:",
            reply_markup=CANCEL_KB)
        return True
    if action == "usrblk":
        await edit(blocked_view(token, tid))
        return True
    if action == "ushow":
        await edit(user_card(token, tid, int(extra)))
        return True
    if action == "ublk":
        target = int(extra)
        if db.block_user(token, target, uid):
            await cq.answer("کاربر مسدود شد ⛔️")
        else:
            await cq.answer("کاربر پیدا نشد.", show_alert=True)
        await edit(user_card(token, tid, target))
        return True
    if action == "uunblk":
        target = int(extra)
        db.unblock_user(token, target)
        await cq.answer("رفع مسدودی شد ♻️")
        await edit(user_card(token, tid, target))
        return True

    # ── پیام به کاربر خاص ──
    if action == "udm":
        state_store[uid] = {"step": "usr_dm_pick", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "✉️ آیدی عددی کاربر را بفرستید "
            "(یا از «🔍 جستجوی کاربر» استفاده کنید):",
            reply_markup=CANCEL_KB)
        return True
    if action == "dmsg":
        try:
            target = int(extra)
        except ValueError:
            await cq.answer("کاربر نامعتبر است.", show_alert=True)
            return True
        if not db.get_bot_user(token, target):
            await cq.answer("این کاربر در ربات شما پیدا نشد.", show_alert=True)
            return True
        state_store[uid] = {"step": "dm_msg", "token": token,
                            "tid": tid, "target": target}
        await cq.answer()
        await cq.message.reply(
            f"✉️ محتوای پیام برای کاربر <code>{target}</code> را بفرستید\n"
            "(متن، عکس، ویدیو یا فایل):",
            reply_markup=CANCEL_KB)
        return True

    # ── زیرمجموعه‌گیری ──
    if action == "ref":
        await edit(ref_view(token, tid))
        return True
    if action == "refon":
        cfg = referrals.config(token)
        if not cfg["enabled"]:
            if cfg["count"] <= 0:
                await cq.answer("اول تعداد دعوت را تنظیم کنید.", show_alert=True)
                return True
        else:
            # fix (باگ گزارش‌شده): خاموش‌کردن کلید اصلی همه‌ی قفل‌ها را
            # بی‌اثر می‌کرد بدون هیچ هشداری؛ حالا با تأییدِ دومرحله‌ای است.
            locked = [b for b in db.buttons(token)
                      if int(b["ref_req"] or 0) == 1]
            if locked and not state_store.get(uid, {}).get("ref_off_ok"):
                state_store.setdefault(uid, {})["ref_off_ok"] = True
                await cq.answer(
                    f"⚠️ با خاموش‌کردن کلید اصلی، قفل {len(locked)} دکمه‌ی"
                    " قفل‌دار هم بی‌اثر می‌شود!\n"
                    "اگر مطمئنید، دکمه را دوباره بزنید.", show_alert=True)
                return True
        if uid in state_store:
            state_store[uid].pop("ref_off_ok", None)
        db.set_setting(token, "ref_enabled", "0" if cfg["enabled"] else "1")
        await cq.answer("تغییر کرد ✅")
        await edit(ref_view(token, tid))
        return True
    if action == "refn":
        state_store[uid] = {"step": "ref_count", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "چند نفر باید دعوت شوند؟ یک عدد بفرستید (۱ تا ۱۰۰):",
            reply_markup=CANCEL_KB)
        return True
    if action == "reftxt":
        state_store[uid] = {"step": "ref_text", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "متن پیام زیرمجموعه‌گیری را بفرستید.\n"
            "متغیرها: <code>{name} {id} {link} {button} {count} {done} {left}</code>\n"
            "(<code>{button}</code> = عنوان دکمه‌ای که کاربر خواسته؛"
            " <code>{done}</code> = شمارش کلی زیرمجموعه‌های کاربر)\n"
            "برای بازگشت به پیش‌فرض <code>پیش‌فرض</code> بفرستید.",
            reply_markup=CANCEL_KB)
        return True
    if action == "refphoto":
        state_store[uid] = {"step": "ref_photo", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "عکس پیام زیرمجموعه‌گیری را بفرستید.\n"
            "این عکس بالای متن دعوت همه‌ی کاربران می‌رود.\n"
            "برای حذف عکس فعلی، <code>حذف</code> بفرستید.",
            reply_markup=CANCEL_KB)
        return True
    if action == "refphotodel":
        media.unlink_media(db.get_setting(token, "ref_photo_path", ""))
        db.set_setting(token, "ref_photo_path", "")
        await cq.answer("عکس حذف شد 🗑")
        await edit(ref_view(token, tid))
        return True

    # ── قفل زیرمجموعه‌گیری هر دکمه ──
    if action == "btnref":
        try:
            bid = int(extra)
        except ValueError:
            bid = -1
        await edit(btn_ref_view(token, tid, bid))
        return True
    if action == "btnrefon":
        try:
            bid = int(extra)
        except ValueError:
            await cq.answer("دکمه پیدا نشد.", show_alert=True)
            return True
        btn = db.button_by_id(token, bid)
        if not btn:
            await cq.answer("دکمه پیدا نشد.", show_alert=True)
            return True
        new = 0 if int(btn["ref_req"] or 0) == 1 else 1
        db.set_button_ref(token, bid, ref_req=new)
        note = ""
        if new == 1:
            # fix (باگ گزارش‌شده): قبلاً اگر «کلید اصلی» خاموش بود، قفلِ دکمه
            # بی‌اثر می‌شد و کاربر بدون اخطار محتوا می‌گرفت. حالا موقع
            # قفل‌کردن، کلید اصلی خودکار روشن می‌شود تا 🔒 همیشه یعنی قفلِ واقعی.
            if db.get_setting(token, "ref_enabled", "0") != "1":
                db.set_setting(token, "ref_enabled", "1")
                note = "\n⚙️ کلید اصلی زیرمجموعه‌گیری خودکار روشن شد."
            # و اگر هیچ تعدادی تنظیم نشده باشد، پیش‌فرض «۱ توکن» گذاشته می‌شود
            if referrals.need_for(token, btn) < 1:
                db.set_button_ref(token, bid, ref_count=1)
                note += "\n🔢 تعداد لازم همین دکمه روی ۱ توکن تنظیم شد."
            await cq.answer("قفل این دکمه روشن شد 🔒" + note, show_alert=bool(note))
        else:
            await cq.answer("قفل این دکمه خاموش شد 🔓")
        await edit(btn_ref_view(token, tid, bid))
        return True
    if action == "btnrefn":
        try:
            bid = int(extra)
        except ValueError:
            await cq.answer("دکمه پیدا نشد.", show_alert=True)
            return True
        if not db.button_by_id(token, bid):
            await cq.answer("دکمه پیدا نشد.", show_alert=True)
            return True
        state_store[uid] = {"step": "btn_ref_count", "token": token,
                            "tid": tid, "bid": bid}
        await cq.answer()
        await cq.message.reply(
            "باز کردن این دکمه چند توکن مصرف‌نشده بسوزاند؟ یک عدد بفرستید (۰ تا ۱۰۰).\n"
            "<code>۰</code> یعنی همان «تعداد پیش‌فرض» پنل زیرمجموعه‌گیری ملاک باشد.",
            reply_markup=CANCEL_KB)
        return True

    # ── آمار کامل ──
    if action == "stat":
        await edit(stats_view(token, tid))
        return True
    if action == "statlist":
        await edit(statlist_view(token, tid, extra))
        return True
    if action == "statchk":
        await cq.answer("⏳ در حال شمردن دوباره‌ی همه‌ی آمارها...")
        child = manager.get_client(token)
        try:
            report = await stats_verify(token, child)
        except Exception as e:  # noqa: BLE001
            report = f"❌ راستی‌آزمایی ناموفق: <code>{_esc(e)}</code>"
        try:
            await cq.message.reply(report, disable_web_page_preview=True)
        except RPCError:
            pass
        return True

    # ── قابلیت‌های ربات ──
    if action == "feat":
        await edit(feat_view(token, tid))
        return True
    if action == "autodel":
        state_store[uid] = {"step": "autodel_secs", "token": token, "tid": tid}
        await cq.answer()
        await cq.message.reply(
            "🗑️ محتوا چند ثانیه بعد از ارسال، خودکار حذف شود؟\n"
            "یک عدد ثانیه بفرستید (۵ تا ۸۶۴۰۰).\n"
            "برای خاموش‌کردن <code>۰</code> بفرستید.",
            reply_markup=CANCEL_KB)
        return True
    if action == "fpass":
        state_store[uid] = {"step": "fpass_set", "token": token, "tid": tid}
        await cq.answer()
        cur = db.get_setting(token, "file_pass", "")
        hint = (f"رمز فعلی: <code>{_esc(cur)}</code>\n"
                if cur else "پسورد فعلاً خاموش است.\n")
        await cq.message.reply(
            "🔑 رمز فایل‌ها را بفرستید؛ از این به بعد کاربر باید یک‌بار رمز را "
            "بفرستد تا محتوا برایش باز شود.\n" + hint +
            "برای غیرفعال‌کردن <code>حذف</code> بفرستید.",
            reply_markup=CANCEL_KB)
        return True
    for act, key, label in (
        ("rndon", "rnd_enabled", "فایل رندوم"),
        ("srchon", "search_enabled", "جستجوی فایل"),
        ("demon", "demo_ask", "سن و جنسیت"),
        ("voteon", "votes_enabled", "لایک/دیسلایک"),
    ):
        if action == act:
            new = "0" if db.get_setting(token, key, "0" if key != "votes_enabled" else "1") == "1" else "1"
            db.set_setting(token, key, new)
            await cq.answer(f"{label} " + ("روشن شد ✅" if new == "1" else "خاموش شد 🚫"))
            await edit(feat_view(token, tid))
            return True

    return False


# ══════════════════════════════════════ مدیریت مراحل متنی
async def handle_step(client: Client, message: Message, state: dict,
                      state_store: dict, main_menu) -> bool:
    step = state["step"]
    token, tid = state["token"], state.get("tid", "")
    uid = message.from_user.id
    text = (message.text or "").strip()

    def done(msg, **kw):
        state_store.pop(uid, None)
        return message.reply(msg, reply_markup=main_menu(uid), **kw)

    if step == "ftr_text":
        value = "" if text in ("پیش‌فرض", "حذف", "-") else media.get_text(message)
        db.set_setting(token, "footer_text", value)
        return await done("✅ پیام پایانی حذف شد." if not value
                          else f"✅ پیام پایانی ذخیره شد:\n\n{value}")

    if step == "tsk_channel":
        # کانال خواسته — عضویت کاربران در همین کانال بررسی می‌شود
        channel = normalize_channel(text)
        if not channel:
            return await done(
                "❌ یوزرنیم نامعتبر بود. مثل <code>@mychannel</code> بفرستید.")
        db.set_setting(token, "task_channel", channel)
        db.set_setting(token, "task_channel_id", "")
        return await done(
            f"✅ کانال خواسته روی {channel} تنظیم شد.\n"
            f"حالا وظیفه را از دکمه‌ی «🟢 روشن کردن» فعال کنید.\n"
            "⚠️ یادت باشد ربات فرزند را ادمین این کانال کنی.")

    if step == "tsk_text":
        value = "" if text in ("پیش‌فرض", "پیشفرض", "-") else media.get_text(message)
        db.set_setting(token, "task_text", value)
        if not value:
            return await done("✅ متن وظیفه به پیش‌فرض برگشت.")
        preview = tasks.render_text(token, message.from_user)
        return await done(f"✅ ذخیره شد.\n\n<b>پیش‌نمایش:</b>\n──────────\n{preview}")

    # ── حذف خودکار محتوا ──
    if step == "autodel_secs":
        num = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).strip()
        if num in ("حذف", "خاموش", "0", "۰"):
            db.set_setting(token, "autodel", "0")
            return await done("✅ حذف خودکار خاموش شد.")
        if not num.isdigit() or not (5 <= int(num) <= 86400):
            return await done("❌ عدد ثانیه بین ۵ تا ۸۶۴۰۰ بفرستید (یا ۰ = خاموش).")
        db.set_setting(token, "autodel", num)
        return await done(f"✅ محتوا بعد از {num} ثانیه خودکار حذف می‌شود.")

    # ── پسورد فایل‌ها ──
    if step == "fpass_set":
        if text in ("حذف", "خاموش", "-", "پیش‌فرض"):
            db.set_setting(token, "file_pass", "")
            return await done("✅ پسورد فایل‌ها غیرفعال شد.")
        if len(text) < 1 or len(text) > 60:
            return await done("❌ رمز باید بین ۱ تا ۶۰ کاراکتر باشد.")
        db.set_setting(token, "file_pass", text)
        return await done(
            "✅ پسورد فایل‌ها فعال شد.\n"
            "از این به بعد کاربر باید یک‌بار رمز را بفرستد تا محتواها باز شود."
            "\n⚠️ تغییر رمز = همه باید رمز جدید را وارد کنند.")

    if step == "txt_edit":
        key = state["key"]
        reset = text in ("پیش‌فرض", "پیشفرض", "-")
        value = db.DEFAULT_SETTINGS.get(key, "") if reset else media.get_text(message)
        db.set_setting(token, key, value)
        return await done("✅ به پیش‌فرض برگشت." if reset
                          else f"✅ ذخیره شد:\n\n{_esc(value)}")

    if step == "usr_search":
        rows = db.search_users(token, text)
        state_store.pop(uid, None)
        if not rows:
            return await message.reply("کاربری پیدا نشد.",
                                       reply_markup=main_menu(uid))
        if len(rows) == 1:
            body, kb = user_card(token, tid, rows[0]["user_id"])
            return await message.reply(body, reply_markup=kb)
        kb = [[InlineKeyboardButton(
            f"{'⛔️ ' if r['blocked'] else ''}{r['first_name'] or r['user_id']}"
            f" | {r['user_id']}",
            callback_data=f"ushow:{tid}:{r['user_id']}")] for r in rows[:15]]
        kb.append([InlineKeyboardButton("« کاربران", callback_data=f"usr:{tid}")])
        return await message.reply(
            f"🔍 <b>{len(rows)} نتیجه</b> — یکی را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(kb))

    # ── پیام به کاربر خاص ──
    if step == "usr_dm_pick":
        if not text.isdigit():
            return await message.reply(
                "❌ آیدی عددی معتبر نیست. دوباره بفرستید یا انصراف بزنید.")
        target = int(text)
        if not db.get_bot_user(token, target):
            return await message.reply(
                "❌ کاربری با این آیدی در این ربات نیست."
                " دوباره تلاش کنید یا انصراف بزنید.")
        state_store.pop(uid, None)
        body, kb = user_card(token, tid, target)
        return await message.reply(body, reply_markup=kb)

    if step == "dm_msg":
        state_store.pop(uid, None)
        target = state.get("target")
        child = manager.get_client(token)
        if not child:
            return await done("❌ ربات فرزند خاموش است؛ اول آن را روشن کنید.")
        # پیام مالک به «بسته‌ی محتوا» تبدیل می‌شود تا با کلاینتِ خودِ ربات
        # فرزند (نه ربات مادر) برای کاربر ارسال شود.
        payload = await media.build_payload(client, message, subdir=tid)
        try:
            sent = await media.send_content(
                child, target,
                kind=payload["kind"], text=payload["text"],
                file_path=payload["path"],
                token=token, cache_key=f"dm:{target}",
            )
        except Exception:  # noqa: BLE001
            sent = None
        if sent is not None:
            return await done(f"✅ پیام به <code>{target}</code> ارسال شد.")
        return await done(
            f"❌ ارسال به <code>{target}</code> ناموفق بود."
            " احتمالاً کاربر ربات را بلاک کرده یا پیام خالی است.")

    # ── زیرمجموعه‌گیری ──
    if step == "ref_count":
        if not text.isdigit() or not (1 <= int(text) <= 100):
            return await done("❌ عدد بین ۱ تا ۱۰۰ بفرستید.")
        db.set_setting(token, "ref_count", text)
        return await done(f"✅ تعداد پیش‌فرض دعوت: {text}")

    # ── تعداد توکن لازم برای یک دکمه‌ی خاص ──
    if step == "btn_ref_count":
        if not text.isdigit() or not (0 <= int(text) <= 100):
            return await done("❌ عدد بین ۰ تا ۱۰۰ بفرستید.")
        bid = int(state.get("bid", 0))
        db.set_button_ref(token, bid, ref_count=int(text))
        extra = " (مثل تعداد کلی پنل)" if int(text) == 0 else ""
        return await done(f"✅ تعداد لازم برای این دکمه: {text}{extra}")

    if step == "ref_text":
        value = "" if text in ("پیش‌فرض", "پیشفرض", "-") else media.get_text(message)
        db.set_setting(token, "ref_text", value)
        if not value:
            return await done("✅ متن زیرمجموعه‌گیری به پیش‌فرض برگشت.")
        preview = referrals.render_preview(token, message.from_user)
        return await done(
            f"✅ ذخیره شد.\n\n<b>پیش‌نمایش:</b>\n──────────\n{preview}")

    if step == "ref_photo":
        if text in ("حذف", "پیش‌فرض", "-"):
            media.unlink_media(db.get_setting(token, "ref_photo_path", ""))
            db.set_setting(token, "ref_photo_path", "")
            return await done("✅ عکس پیام دعوت حذف شد.")
        if media.detect_kind(message) != "photo":
            return await message.reply("❌ فقط عکس بفرستید یا «حذف» را بنویسید.")
        path = await media.save_media(client, message, subdir=tid)
        if not path:
            return await done("❌ ذخیره‌ی عکس ناموفق بود؛ دوباره تلاش کنید.")
        old = db.get_setting(token, "ref_photo_path", "")
        if old and old != path:
            media.unlink_media(old)   # عکس قبلی از دیسک پاک شود
        db.set_setting(token, "ref_photo_path", path)
        return await done("✅ عکس پیام زیرمجموعه‌گیری ذخیره شد.")

    return False
