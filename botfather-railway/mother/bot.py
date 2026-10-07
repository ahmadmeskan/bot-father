"""ربات مادر — کاربران توکن می‌دهند و ربات فرزندشان ساخته و اجرا می‌شود."""
from __future__ import annotations

import compat  # noqa: F401  ← باید قبل از pyrogram ایمپورت شود

import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import RPCError, UserNotParticipant
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import config
import db
import manager
import media
from child.runtime import normalize_channel
from mother import panels, wizard

log = logging.getLogger("mother")

BTN_NEW = "➕ ساخت ربات جدید"
BTN_MINE = "🤖 ربات‌های من"
BTN_HELP = "ℹ️ راهنما"
BTN_SUPPORT = "☎️ پشتیبانی"
BTN_ADMIN = "🛠 پنل مدیریت"
BTN_CANCEL = "❌ انصراف"

# وضعیت گفتگوی کاربران: user_id -> dict
STATE: dict[int, dict] = {}

HELP_TEXT = """<b>راهنمای ربات‌ساز</b>

۱) در تلگرام به @BotFather بروید و دستور /newbot را بزنید.
۲) نام و یوزرنیم ربات را انتخاب کنید.
۳) توکنی که می‌دهد (مثل <code>123456:AAE...</code>) را کپی کنید.
۴) اینجا «➕ ساخت ربات جدید» را بزنید و توکن را بفرستید.

پس از ساخت می‌توانید برای ربات خود:
• پیام خوش‌آمد تنظیم کنید (<code>{name}</code> = نام کاربر)
• دکمه‌های منو با متن/عکس/فایل بسازید
• چند کانال عضویت اجباری بگذارید
• پیام همگانی بفرستید
• پیام‌های کاربران را در پشتیبانی دریافت و پاسخ دهید
"""


MOTHER_SCOPE = "mother"   # کلید تیکت‌های پشتیبانی ربات مادر


def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(BTN_NEW), KeyboardButton(BTN_MINE)],
            [KeyboardButton(BTN_HELP), KeyboardButton(BTN_SUPPORT)]]
    if user_id in config.ADMINS:
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


CANCEL_KB = ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True)

app = Client(
    name="mother",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.MOTHER_TOKEN,
    workdir=str(config.SESSIONS_DIR),
    parse_mode=ParseMode.HTML,
)


# --------------------------------------------------------------- کمکی‌ها
async def force_join_ok(client: Client, user_id: int) -> str | None:
    if not config.FORCE_CHANNEL:
        return None
    try:
        m = await client.get_chat_member(config.FORCE_CHANNEL, user_id)
        if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            return config.FORCE_CHANNEL
        return None
    except UserNotParticipant:
        return config.FORCE_CHANNEL
    except RPCError:
        return None


def channels_kb(token: str, tid: str) -> InlineKeyboardMarkup:
    """منوی کانال‌های اجباری: هر کانال یک دکمه‌ی حذف مستقل دارد."""
    channels = db.get_channels(token)
    rows = [
        [InlineKeyboardButton(f"🗑 {ch}", callback_data=f"chdel:{tid}:{i}")]
        for i, ch in enumerate(channels)
    ]
    rows.append([InlineKeyboardButton("➕ افزودن کانال", callback_data=f"chadd:{tid}")])
    rows.append([InlineKeyboardButton("✏️ متن پیام عضویت",
                                      callback_data=f"chtxt:{tid}")])
    if channels:
        rows.append([InlineKeyboardButton("🧹 حذف همه کانال‌ها",
                                          callback_data=f"chclr:{tid}")])
    bypass = db.get_setting(token, "owner_bypass", "0") == "1"
    rows.append([InlineKeyboardButton(
        f"{'✅' if bypass else '❌'} معافیت خودم از عضویت",
        callback_data=f"chbyp:{tid}")])
    rows.append([InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")])
    return InlineKeyboardMarkup(rows)


def channels_text(token: str) -> str:
    channels = db.get_channels(token)
    if not channels:
        body = "هیچ کانال اجباری‌ای تنظیم نشده است."
    else:
        body = "کاربران باید در <b>همه‌ی</b> این کانال‌ها عضو باشند:\n\n" + "\n".join(
            f"{i + 1}. <code>{ch}</code>" for i, ch in enumerate(channels)
        ) + "\n\nبرای حذف، روی دکمه‌ی 🗑 همان کانال بزنید."
    from child.runtime import DEFAULT_JOIN_TEXT
    custom = db.get_setting(token, "join_text", "")
    msg_state = "سفارشی ✏️" if custom else "پیش‌فرض"
    ttl = db.get_setting(token, "check_ttl", "0")
    extra = (f"\n\n📝 متن پیام عضویت: <b>{msg_state}</b>"
             f"\n🔄 بررسی مجدد: {'هر بار' if ttl == '0' else ttl + ' ثانیه'}")
    return "📢 <b>کانال‌های عضویت اجباری</b>\n\n" + body + extra



def bot_panel_kb(token: str) -> InlineKeyboardMarkup:
    running = manager.is_running(token)
    tid = token.split(":")[0]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ پیام خوش‌آمد", callback_data=f"welcome:{tid}"),
             InlineKeyboardButton("🔘 دکمه‌ها", callback_data=f"btns:{tid}")],
            [InlineKeyboardButton("📢 کانال‌های اجباری", callback_data=f"chans:{tid}"),
             InlineKeyboardButton("☎️ پشتیبانی", callback_data=f"sup:{tid}")],
            [InlineKeyboardButton("🏁 پیام پایانی", callback_data=f"ftr:{tid}"),
             InlineKeyboardButton("🤜 وظیفه اجباری", callback_data=f"tsk:{tid}")],
            # قابلیت جدید: زیرمجموعه‌گیری با عکس و متن قابل تنظیم
            [InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data=f"ref:{tid}")],
            [InlineKeyboardButton("📝 متن‌های ربات", callback_data=f"txts:{tid}"),
             InlineKeyboardButton("👥 کاربران", callback_data=f"usr:{tid}")],
            [InlineKeyboardButton("📣 پیام همگانی", callback_data=f"bc:{tid}"),
             InlineKeyboardButton("📊 آمار", callback_data=f"stat:{tid}")],
            # قابلیت‌های جدید: حذف خودکار، پسورد فایل، رندوم، سرچ، دموگرافیک
            [InlineKeyboardButton("⚙️ قابلیت‌ها", callback_data=f"feat:{tid}")],
            [InlineKeyboardButton(
                "⏸ خاموش کردن" if running else "▶️ روشن کردن",
                callback_data=f"toggle:{tid}")],
            [InlineKeyboardButton("🗑 حذف ربات", callback_data=f"del:{tid}")],
            [InlineKeyboardButton("« بازگشت", callback_data="mybots")],
        ]
    )


def find_token(user_id: int, tid: str) -> str | None:
    for row in db.user_bots(user_id):
        if row["token"].split(":")[0] == tid:
            return row["token"]
    if user_id in config.ADMINS:
        for row in db.all_bots(active_only=False):
            if row["token"].split(":")[0] == tid:
                return row["token"]
    return None


# fix: ساخت پنل دکمه‌ها به تابع مستقل منتقل شد تا هم «btns» و هم «delbtn»
# از همان کد استفاده کنند و نیاز به اجرای مجدد کل on_cb نباشد.
def _btns_panel(token: str, tid: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = db.buttons(token)
    kb = []
    for b in rows:
        items = db.button_items(token, b["id"])
        icons = "".join(dict.fromkeys(
            {"photo": "🖼", "video": "🎬", "document": "📎",
             "audio": "🎵", "voice": "🎤", "animation": "🎞"}.get(i["kind"], "📄")
            for i in items))
        if b["body"]:
            icons = "📝" + icons
        if not items and not b["body"]:
            icons = "📄"
        # fix: 🎁 = قفل زیرمجموعه‌گیری مخصوص همین دکمه (روشن/خاموش + تعداد جدا)؛
        # وقتی قفل روشن باشد آیکون 🔒 نشان داده می‌شود.
        locked = "🔒" if int(b["ref_req"] or 0) == 1 else "🎁"
        kb.append([
            InlineKeyboardButton(f"{icons} {b['title']}",
                                 callback_data=f"btnprev:{tid}:{b['id']}"),
            InlineKeyboardButton(locked, callback_data=f"btnref:{tid}:{b['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"delbtn:{tid}:{b['id']}"),
        ])
    kb.append([InlineKeyboardButton("➕ افزودن دکمه", callback_data=f"addbtn:{tid}")])
    kb.append([InlineKeyboardButton("« بازگشت", callback_data=f"bot:{tid}")])
    return ("🔘 <b>دکمه‌های منوی ربات</b>\n"
            + ("برای پیش‌نمایش روی نام دکمه، برای قفل زیرمجموعه‌گیری روی 🎁 "
               "و برای حذف روی 🗑 بزنید (🔒 = قفل دعوت روشن)."
               if rows else "هنوز دکمه‌ای ندارید.")), InlineKeyboardMarkup(kb)


async def show_my_bots(user_id: int, edit: Message | None = None, msg: Message | None = None):
    rows = db.user_bots(user_id)
    if not rows:
        text = "هنوز رباتی نساخته‌اید. «➕ ساخت ربات جدید» را بزنید."
        kb = None
    else:
        text = f"<b>ربات‌های شما ({len(rows)}/{config.MAX_BOTS_PER_USER})</b>\nیکی را انتخاب کنید:"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{'🟢' if manager.is_running(r['token']) else '🔴'} @{r['username']} "
                f"— {db.bot_user_count(r['token'])} کاربر",
                callback_data=f"bot:{r['token'].split(':')[0]}")]
            for r in rows
        ])
    if edit:
        await edit.edit_text(text, reply_markup=kb)
    elif msg:
        await msg.reply(text, reply_markup=kb)


# --------------------------------------------------------------- دستورات
@app.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, message: Message):
    STATE.pop(message.from_user.id, None)
    channel = await force_join_ok(client, message.from_user.id)
    if channel:
        return await message.reply(
            "برای استفاده از ربات ابتدا عضو کانال شوید:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📢 عضویت", url=f"https://t.me/{channel.lstrip('@')}")]]
            ),
        )
    await message.reply(
        f"سلام {message.from_user.first_name} 👋\n"
        "با این ربات می‌توانید ربات تلگرامی اختصاصی خودتان را بسازید.\n"
        "برای شروع «➕ ساخت ربات جدید» را بزنید.",
        reply_markup=main_menu(message.from_user.id),
    )


@app.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(_, message: Message):
    STATE.pop(message.from_user.id, None)
    await message.reply("لغو شد.", reply_markup=main_menu(message.from_user.id))


@app.on_message(filters.command("stats") & filters.private & filters.user(config.ADMINS or [0]))
async def cmd_stats(_, message: Message):
    s = db.stats()
    await message.reply(
        f"📊 <b>آمار کلی</b>\n"
        f"ربات‌های ساخته‌شده: {s['bots']}\n"
        f"در حال اجرا: {manager.running_count()}\n"
        f"سازندگان: {s['owners']}\n"
        f"مجموع کاربران ربات‌ها: {s['users']}"
    )


# ------------------------------------------------------- پیام‌های متنی
@app.on_message(filters.private & ~filters.command(["start", "cancel", "stats"]))
async def on_text(client: Client, message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    state = STATE.get(uid)

    if text == BTN_CANCEL:
        STATE.pop(uid, None)
        return await message.reply("لغو شد.", reply_markup=main_menu(uid))

    # ---------- پاسخ ادمین به تیکت (ریپلای روی پیام کاربر) ----------
    if uid in config.ADMINS and message.reply_to_message:
        ticket = db.get_dm_ticket(MOTHER_SCOPE, uid, message.reply_to_message.id)
        if ticket:
            try:
                await message.copy(ticket["user_id"])
                await message.reply("✅ پاسخ برای کاربر ارسال شد.")
            except RPCError as e:
                await message.reply(f"❌ ارسال ناموفق: {e}")
            return

    # ---------- مراحل گفتگو ----------
    if state:
        step = state["step"]

        if step in panels.STEPS:
            handled = await panels.handle_step(client, message, state, STATE, main_menu)
            if handled is not False:
                return

        if step == "token":
            await message.reply("⏳ در حال بررسی توکن...")
            ok, msg, bot_id, username = await manager.validate_token(text)
            if not ok:
                return await message.reply(f"❌ {msg}\nدوباره تلاش کنید یا انصراف بزنید.")
            if db.get_bot(text):
                STATE.pop(uid, None)
                return await message.reply("این ربات قبلاً ثبت شده است.",
                                           reply_markup=main_menu(uid))
            db.add_bot(text, bot_id, username, uid)
            started, smsg = await manager.start_bot(text)
            STATE.pop(uid, None)
            if not started:
                return await message.reply(f"ربات ثبت شد ولی اجرا نشد: {smsg}",
                                           reply_markup=main_menu(uid))
            return await message.reply(
                f"✅ ربات شما ساخته و اجرا شد!\n\n"
                f"🤖 @{username}\n"
                f"از «🤖 ربات‌های من» می‌توانید آن را مدیریت کنید.",
                reply_markup=main_menu(uid),
            )

        if step == "support_msg":
            STATE.pop(uid, None)
            if not config.ADMINS:
                return await message.reply("پشتیبانی در دسترس نیست.",
                                           reply_markup=main_menu(uid))
            delivered = 0
            for admin_id in config.ADMINS:
                try:
                    header = await client.send_message(
                        admin_id,
                        f"📩 <b>پیام پشتیبانی</b>\n"
                        f"از: {html.escape(message.from_user.first_name or '')} "
                        f"(@{message.from_user.username or '—'} | <code>{uid}</code>)\n"
                        f"<i>برای پاسخ، روی همین پیام ریپلای کنید.</i>",
                    )
                    await message.copy(admin_id)
                    db.add_dm_ticket(MOTHER_SCOPE, admin_id, header.id, uid)
                    delivered += 1
                except RPCError as e:
                    log.warning("ارسال تیکت به ادمین %s ناموفق: %s", admin_id, e)
            if delivered:
                return await message.reply("✅ پیام شما برای پشتیبانی ارسال شد.",
                                           reply_markup=main_menu(uid))
            return await message.reply(
                "❌ ارسال پیام ممکن نشد.\n"
                "<i>(ادمین باید یک‌بار ربات را استارت کرده باشد)</i>",
                reply_markup=main_menu(uid),
            )

        if step == "welcome":
            db.set_setting(state["token"], "welcome", media.get_text(message) or "")
            STATE.pop(uid, None)
            return await message.reply("✅ پیام خوش‌آمد ذخیره شد.", reply_markup=main_menu(uid))

        if step == "join_text":
            token = state["token"]
            STATE.pop(uid, None)
            if text in ("پیش‌فرض", "پیشفرض", "default", "-"):
                db.set_setting(token, "join_text", "")
                return await message.reply("✅ متن پیام عضویت به حالت پیش‌فرض برگشت.",
                                           reply_markup=main_menu(uid))
            new_text = media.get_text(message)
            if not new_text.strip():
                return await message.reply("❌ متن خالی است.", reply_markup=main_menu(uid))
            db.set_setting(token, "join_text", new_text)
            from child.runtime import render_join_text
            preview = render_join_text(token, message.from_user,
                                       db.get_channels(token) or ["@example"])
            return await message.reply(
                "✅ متن پیام عضویت ذخیره شد.\n\n"
                "<b>پیش‌نمایش:</b>\n──────────\n" + preview,
                reply_markup=main_menu(uid),
                disable_web_page_preview=True,
            )

        if step == "chan_add":
            token = state["token"]
            STATE.pop(uid, None)
            channel = normalize_channel(text)
            if not channel:
                return await message.reply(
                    "❌ فرمت نامعتبر.\n"
                    "یوزرنیم عمومی کانال را بفرستید، مثل <code>@mychannel</code>\n"
                    "<i>لینک دعوت خصوصی (+ABC) پشتیبانی نمی‌شود.</i>",
                    reply_markup=main_menu(uid),
                )

            child = manager.get_client(token)
            if child:
                await message.reply("⏳ در حال بررسی دسترسی ربات به کانال...")
                try:
                    me = await child.get_me()
                    member = await child.get_chat_member(channel, me.id)
                    if member.status not in (ChatMemberStatus.ADMINISTRATOR,
                                             ChatMemberStatus.OWNER):
                        raise ValueError("ربات ادمین نیست")
                except Exception as e:  # noqa: BLE001
                    log.warning("بررسی کانال %s ناموفق: %s", channel, e)
                    return await message.reply(
                        f"❌ ربات شما به کانال {channel} دسترسی ندارد.\n\n"
                        "<b>راه‌حل:</b>\n"
                        "۱) به کانال بروید → مدیران → افزودن مدیر\n"
                        "۲) <b>ربات فرزند</b> را ادمین کنید (نه ربات مادر)\n"
                        "۳) دوباره تلاش کنید",
                        reply_markup=main_menu(uid),
                    )

            added = db.add_channel(token, channel)
            note = "" if child else "\n⚠️ ربات خاموش است؛ دسترسی بررسی نشد."
            return await message.reply(
                (f"✅ کانال {channel} اضافه شد." if added
                 else f"ℹ️ کانال {channel} از قبل در لیست بود.") + note,
                reply_markup=main_menu(uid),
            )

        if step == "btn_title":
            if not text:
                return await message.reply("عنوان باید متن باشد.")
            if db.button_by_title(state["token"], text):
                return await message.reply("این عنوان تکراری است، عنوان دیگری بفرستید.")
            STATE[uid] = {
                "step": "wz_ask", "token": state["token"], "title": text,
                "text": None, "items": [], "stage": None,
                "chat_id": message.chat.id, "panel_id": None,
            }
            await wizard.ask_stage(client, STATE[uid], "text")
            return

        if step == "wz_collect":
            ok = await wizard.collect(client, state, message)
            if not ok:
                label = wizard.STAGE_LABEL.get(state.get("stage"), "محتوا")
                return await message.reply(
                    f"❌ این مورد {label} نبود. دوباره بفرستید یا انصراف بزنید."
                )
            if state.get("step") == "done":
                STATE.pop(uid, None)
            return

        if step == "broadcast":
            token = state["token"]
            STATE.pop(uid, None)
            total = len(db.bot_user_ids(token))
            if total == 0:
                return await message.reply("هیچ کاربری در این ربات ثبت نشده است.",
                                           reply_markup=main_menu(uid))
            status = await message.reply(f"⏳ آماده‌سازی و ارسال به {total} کاربر...")
            # پیام را به «بسته‌ی محتوا» تبدیل می‌کنیم تا ربات فرزند بتواند
            # خودش آن را بفرستد (ربات مادر اجازه‌ی پیام به این کاربران را ندارد).
            payload = await media.build_payload(client, message, subdir=token.split(":")[0])

            async def progress(ok, fail):
                try:
                    await status.edit_text(f"⏳ ارسال شد: {ok} | ناموفق: {fail}")
                except RPCError:
                    pass

            ok, fail = await manager.broadcast(token, payload, progress)
            return await status.edit_text(
                f"📣 پایان ارسال\n✅ موفق: {ok}\n❌ ناموفق: {fail}"
            )

    # ---------- منوی اصلی ----------
    if text == BTN_NEW:
        if len(db.user_bots(uid)) >= config.MAX_BOTS_PER_USER and uid not in config.ADMINS:
            return await message.reply(
                f"شما به سقف {config.MAX_BOTS_PER_USER} ربات رسیده‌اید."
            )
        STATE[uid] = {"step": "token"}
        return await message.reply(
            "توکن ربات خود را بفرستید.\n\n"
            "آن را از @BotFather با دستور /newbot بگیرید.\n"
            "<code>123456789:AAF...</code>",
            reply_markup=CANCEL_KB,
        )

    if text == BTN_MINE:
        return await show_my_bots(uid, msg=message)

    if text == BTN_HELP:
        return await message.reply(HELP_TEXT, reply_markup=main_menu(uid))

    if text == BTN_SUPPORT:
        if not config.ADMINS:
            return await message.reply("پشتیبانی در دسترس نیست.")
        STATE[uid] = {"step": "support_msg"}
        return await message.reply(
            "پیام خود را بنویسید (متن، عکس یا فایل).\n"
            "پاسخ همین‌جا به شما داده می‌شود.",
            reply_markup=CANCEL_KB,
        )

    if text == BTN_ADMIN and uid in config.ADMINS:
        s = db.stats()
        return await message.reply(
            f"🛠 <b>پنل مدیریت</b>\n"
            f"ربات‌ها: {s['bots']} (فعال: {manager.running_count()})\n"
            f"سازندگان: {s['owners']}\n"
            f"کاربران: {s['users']}",
            reply_markup=main_menu(uid),
        )

    await message.reply("از منوی زیر انتخاب کنید 👇", reply_markup=main_menu(uid))


# ------------------------------------------------------------- اینلاین‌ها
@app.on_callback_query()
async def on_cb(client: Client, cq: CallbackQuery):
    uid = cq.from_user.id
    data = cq.data or ""
    # ⚠️ باگ قبلی: partition فقط یک بار جدا می‌کرد، پس برای «delbtn:<tid>:<bid>»
    # مقدار tid برابر «<tid>:<bid>» می‌شد و find_token شکست می‌خورد →
    # پیام اشتباه «این ربات متعلق به شما نیست».
    parts = data.split(":")
    action = parts[0]
    tid = parts[1] if len(parts) > 1 else ""
    extra = parts[2] if len(parts) > 2 else ""

    # ── ویزارد ساخت دکمه: وضعیتش در STATE است، نه در callback_data ──
    if action == "wz":
        state = STATE.get(uid)
        if not state or "items" not in state:
            return await cq.answer("این ویزارد منقضی شده است.", show_alert=True)

        if tid == "x":
            STATE.pop(uid, None)
            await cq.answer("لغو شد")
            return await cq.message.edit_text(
                "ساخت دکمه لغو شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "« دکمه‌ها",
                    callback_data=f"btns:{state['token'].split(':')[0]}")]]),
            )

        if tid == "y":
            state["step"] = "wz_collect"
            await cq.answer()
            return await wizard.show_panel(
                client, state,
                wizard.STAGE_PROMPT[state["stage"]],
                InlineKeyboardMarkup([[InlineKeyboardButton(
                    "✖️ انصراف", callback_data="wz:x")]]),
            )

        if tid == "n":
            await cq.answer()
            await wizard.advance(client, state)
            if state.get("step") == "done":     # ذخیره‌ی خودکار انجام شد
                STATE.pop(uid, None)
            return

        if tid == "cap":
            await cq.answer()
            idx = -1 if extra == "s" else int(extra)
            await wizard.save(client, state, idx)
            STATE.pop(uid, None)
            return

        return await cq.answer()

    if action == "mybots":
        await cq.answer()
        return await show_my_bots(uid, edit=cq.message)

    token = find_token(uid, tid) if tid else None
    if tid and not token:
        return await cq.answer("این ربات متعلق به شما نیست.", show_alert=True)

    # پنل‌های تکمیلی (پیام پایانی، وظیفه، متن‌ها، کاربران)
    if action in panels.ACTIONS or action == "txtedit":
        if await panels.handle_callback(client, cq, token, tid, extra, STATE):
            return

    if action == "bot":
        row = db.get_bot(token)
        await cq.answer()
        return await cq.message.edit_text(
            f"🤖 <b>@{row['username']}</b>\n"
            f"وضعیت: {'🟢 روشن' if manager.is_running(token) else '🔴 خاموش'}\n"
            f"کاربران: {db.bot_user_count(token)}\n"
            f"دکمه‌ها: {len(db.buttons(token))}",
            reply_markup=bot_panel_kb(token),
        )

    if action == "welcome":
        STATE[uid] = {"step": "welcome", "token": token}
        await cq.answer()
        return await cq.message.reply(
            "پیام خوش‌آمد جدید را بفرستید.\n"
            "می‌توانید از <code>{name}</code> و <code>{id}</code> استفاده کنید.",
            reply_markup=CANCEL_KB,
        )

    if action == "chans":
        await cq.answer()
        return await cq.message.edit_text(channels_text(token),
                                          reply_markup=channels_kb(token, tid))

    if action == "chadd":
        STATE[uid] = {"step": "chan_add", "token": token}
        await cq.answer()
        return await cq.message.reply(
            "یوزرنیم کانال را بفرستید، مثل <code>@mychannel</code>\n\n"
            "<b>یادآوری:</b> ربات فرزند باید در آن کانال ادمین باشد.",
            reply_markup=CANCEL_KB,
        )

    if action == "chtxt":
        STATE[uid] = {"step": "join_text", "token": token}
        await cq.answer()
        from child.runtime import DEFAULT_JOIN_TEXT
        current = db.get_setting(token, "join_text", "") or DEFAULT_JOIN_TEXT
        return await cq.message.reply(
            "متن فعلی:\n"
            "──────────\n"
            f"{current}\n"
            "──────────\n\n"
            "متن جدید پیام عضویت اجباری را بفرستید.\n\n"
            "<b>متغیرهای قابل استفاده:</b>\n"
            "<code>{name}</code> نام کاربر\n"
            "<code>{id}</code> آیدی عددی کاربر\n"
            "<code>{count}</code> تعداد کانال‌ها\n"
            "<code>{channels}</code> لیست کانال‌ها\n"
            "<code>{links}</code> لیست کانال‌ها به‌صورت لینک\n\n"
            "برای بازگشت به متن پیش‌فرض، <code>پیش‌فرض</code> بفرستید.\n"
            "<i>دکمه‌های ورود به کانال به‌صورت خودکار زیر پیام اضافه می‌شوند.</i>",
            reply_markup=CANCEL_KB,
        )

    if action == "chdel":
        # fix: اگر extra غیرعددی بود (کال‌بک دستکاری‌شده)، کل هندلر نچشد
        try:
            idx = int(extra)
        except ValueError:
            idx = -1
        removed = db.remove_channel(token, idx)
        await cq.answer(f"{removed} حذف شد 🗑" if removed else "پیدا نشد")
        return await cq.message.edit_text(channels_text(token),
                                          reply_markup=channels_kb(token, tid))

    if action == "chclr":
        n = db.clear_channels(token)
        await cq.answer(f"{n} کانال حذف شد 🧹")
        return await cq.message.edit_text(channels_text(token),
                                          reply_markup=channels_kb(token, tid))

    if action == "chbyp":
        new = "0" if db.get_setting(token, "owner_bypass", "0") == "1" else "1"
        db.set_setting(token, "owner_bypass", new)
        await cq.answer("شما از عضویت اجباری معاف شدید ✅" if new == "1"
                        else "معافیت شما لغو شد — حالا خودتان هم باید عضو باشید ❌",
                        show_alert=True)
        return await cq.message.edit_text(channels_text(token),
                                          reply_markup=channels_kb(token, tid))

    if action == "sup":
        new = "0" if db.get_setting(token, "support", "1") == "1" else "1"
        db.set_setting(token, "support", new)
        await cq.answer("پشتیبانی " + ("فعال شد ✅" if new == "1" else "غیرفعال شد ❌"),
                        show_alert=True)
        return

    if action == "bc":
        if not manager.is_running(token):
            return await cq.answer("ابتدا ربات را روشن کنید.", show_alert=True)
        STATE[uid] = {"step": "broadcast", "token": token}
        await cq.answer()
        return await cq.message.reply(
            "پیامی که می‌خواهید برای همه کاربران ربات ارسال شود را بفرستید:",
            reply_markup=CANCEL_KB,
        )

    if action == "toggle":
        if manager.is_running(token):
            await manager.stop_bot(token)
            await cq.answer("ربات خاموش شد ⏸")
        else:
            ok, msg = await manager.start_bot(token)
            await cq.answer("ربات روشن شد ▶️" if ok else msg, show_alert=not ok)
        row = db.get_bot(token)
        return await cq.message.edit_text(
            f"🤖 <b>@{row['username']}</b>\n"
            f"وضعیت: {'🟢 روشن' if manager.is_running(token) else '🔴 خاموش'}\n"
            f"کاربران: {db.bot_user_count(token)}",
            reply_markup=bot_panel_kb(token),
        )

    if action == "del":
        await cq.answer()
        return await cq.message.edit_text(
            "آیا از حذف این ربات مطمئن هستید؟ همه تنظیمات و کاربران پاک می‌شود.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"delyes:{tid}"),
                 InlineKeyboardButton("« انصراف", callback_data=f"bot:{tid}")]
            ]),
        )

    if action == "delyes":
        await manager.stop_bot(token)
        media.delete_bot_files(token)   # fix: فایل‌های رسانهٔ ربات هم پاک شوند
        db.delete_bot(token)
        await cq.answer("حذف شد 🗑")
        return await show_my_bots(uid, edit=cq.message)

    # ---------- مدیریت دکمه‌ها ----------
    if action == "btns":
        text, kb = _btns_panel(token, tid)
        await cq.answer()
        return await cq.message.edit_text(text, reply_markup=kb)

    if action == "addbtn":
        STATE[uid] = {"step": "btn_title", "token": token}
        await cq.answer()
        return await cq.message.reply("عنوان دکمه را بفرستید:", reply_markup=CANCEL_KB)

    if action == "btnprev":
        try:
            bid = int(extra)
        except ValueError:
            bid = -1
        btn = db.fetchone("SELECT * FROM buttons WHERE token=? AND id=?",
                          (token, bid))
        if not btn:
            return await cq.answer("این دکمه دیگر وجود ندارد.", show_alert=True)
        await cq.answer("در حال ارسال پیش‌نمایش…")
        from child.runtime import _send_button_content
        # fix: عنوان دکمه قبل از قرارگرفتن در پیام HTML escape می‌شود
        await cq.message.reply(
            f"👁 <b>پیش‌نمایش دکمه «{html.escape(btn['title'])}»</b>")
        await _send_button_content(client, cq.message.chat.id, btn, token)
        return

    if action == "delbtn":
        try:
            bid = int(extra)
        except ValueError:
            return await cq.answer("پیدا نشد", show_alert=True)
        media.delete_button_files(token, bid)   # fix: فایل‌های رسانهٔ دکمه پاک شوند
        db.delete_button(token, bid)
        await cq.answer("حذف شد 🗑")
        # fix: قبلاً با اجرای مجدد on_cb و cq.answer() دوم، تلگرام خطای
        # QUERY_ID_INVALID می‌داد و لیست رفرش نمی‌شد. حالا بدون جوابِ دوم،
        # همان پیام مستقیم ویرایش می‌شود.
        text, kb = _btns_panel(token, tid)
        try:
            return await cq.message.edit_text(text, reply_markup=kb)
        except RPCError:
            return await cq.message.reply(text, reply_markup=kb)

    await cq.answer()
