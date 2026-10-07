"""ویزارد ساخت دکمه‌ی چندمحتوایی برای ربات مادر.

یک دکمه می‌تواند هم‌زمان متن، چند عکس، چند ویدیو، فایل و صوت داشته باشد.
همه‌ی مراحل روی **یک پیام واحد** انجام می‌شود که خودش را ویرایش می‌کند،
تا چت شلوغ نشود.
"""
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import db
import media

from child.runtime import esc

log = logging.getLogger("wizard")

# ترتیب سؤال‌ها: (نوع, برچسب, راهنمای ارسال)
STAGES: list[tuple[str, str, str]] = [
    ("text", "📝 متن", "متن دکمه را بفرستید:"),
    ("photo", "🖼 عکس", "عکس را بفرستید:"),
    ("video", "🎬 ویدیو", "ویدیو را بفرستید:"),
    ("document", "📎 فایل", "فایل را بفرستید:"),
    ("audio", "🎵 صوت", "فایل صوتی را بفرستید:"),
]
STAGE_LABEL = {k: lbl for k, lbl, _ in STAGES}
STAGE_PROMPT = {k: p for k, _, p in STAGES}
ORDER = [k for k, _, _ in STAGES]

CANCEL_BTN = "❌ انصراف"
CANCEL_KB = ReplyKeyboardMarkup([[KeyboardButton(CANCEL_BTN)]], resize_keyboard=True)


# ───────────────────────────────────────────────────── ساخت پنل
def basket_lines(state: dict) -> str:
    """خلاصه‌ی چیزهایی که تا الان به دکمه اضافه شده."""
    lines = []
    txt = state.get("text")
    preview = (txt[:28] + "…") if txt and len(txt) > 28 else txt
    lines.append(f"📝 متن: {'«' + preview + '»' if txt else '—'}")
    for kind, label, _ in STAGES[1:]:
        n = sum(1 for i in state["items"] if i["kind"] == kind)
        lines.append(f"{label}: {n if n else '—'}")
    return "\n".join(lines)


def panel_text(state: dict, question: str) -> str:
    # fix: عنوان دکمه ورودیِ آزادِ سازنده است؛ escape نمی‌شد و کاراکترهای
    # HTML (مثل <) پنل ویزارد را می‌شکست.
    return (
        f"🧺 <b>ساخت دکمه «{esc(state['title'])}»</b>\n"
        f"──────────────\n"
        f"{basket_lines(state)}\n"
        f"──────────────\n\n"
        f"{question}"
    )


def yes_no_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله", callback_data=f"wz:{prefix}y"),
         InlineKeyboardButton("❌ خیر", callback_data=f"wz:{prefix}n")],
        [InlineKeyboardButton("✖️ انصراف", callback_data="wz:x")],
    ])


def caption_kb(state: dict) -> InlineKeyboardMarkup:
    rows = []
    counters: dict[str, int] = {}
    for idx, item in enumerate(state["items"]):
        counters[item["kind"]] = counters.get(item["kind"], 0) + 1
        label = f"{STAGE_LABEL[item['kind']]} {counters[item['kind']]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"wz:cap:{idx}")])
    rows.append([InlineKeyboardButton("📄 جداگانه ارسال شود",
                                      callback_data="wz:cap:s")])
    rows.append([InlineKeyboardButton("✖️ انصراف", callback_data="wz:x")])
    return InlineKeyboardMarkup(rows)


async def show_panel(client: Client, state: dict, question: str,
                     keyboard: InlineKeyboardMarkup) -> None:
    """پنل را ویرایش می‌کند؛ اگر نشد، پیام تازه می‌فرستد."""
    text = panel_text(state, question)
    if state.get("panel_id"):
        try:
            await client.edit_message_text(
                state["chat_id"], state["panel_id"], text, reply_markup=keyboard
            )
            return
        except RPCError as e:
            log.debug("ویرایش پنل ممکن نشد: %s", e)
    msg = await client.send_message(state["chat_id"], text, reply_markup=keyboard)
    state["panel_id"] = msg.id


# ───────────────────────────────────────────────── حرکت بین مراحل
def next_stage(state: dict) -> str | None:
    """مرحله‌ی بعدی را برمی‌گرداند (یا None اگر تمام شده)."""
    current = state.get("stage")
    idx = ORDER.index(current) if current in ORDER else -1
    return ORDER[idx + 1] if idx + 1 < len(ORDER) else None


async def ask_stage(client: Client, state: dict, stage: str) -> None:
    state["stage"] = stage
    state["step"] = "wz_ask"
    label = STAGE_LABEL[stage].split(" ", 1)[1]
    have = sum(1 for i in state["items"] if i["kind"] == stage)
    q = (f"آیا می‌خواهید {label} <b>دیگری</b> اضافه کنید؟"
         if have else f"آیا می‌خواهید {label} اضافه کنید؟")
    await show_panel(client, state, q, yes_no_kb(""))


async def advance(client: Client, state: dict) -> None:
    """به مرحله‌ی بعد می‌رود یا وارد مرحله‌ی پایانی می‌شود."""
    nxt = next_stage(state)
    if nxt:
        return await ask_stage(client, state, nxt)
    await finish_stage(client, state)


async def finish_stage(client: Client, state: dict) -> None:
    """پایان جمع‌آوری: پرسیدن محل چسبیدن متن یا ذخیره‌ی مستقیم."""
    if state.get("text") and state["items"]:
        state["step"] = "wz_caption"
        return await show_panel(
            client, state,
            "متن به کدام مورد بچسبد؟\n"
            "<i>متن فقط یک بار ارسال می‌شود.</i>",
            caption_kb(state),
        )
    await save(client, state)


# ─────────────────────────────────────────────────────── ذخیره
async def save(client: Client, state: dict, target_index: int = -1) -> None:
    token, title = state["token"], state["title"]
    text = state.get("text") or ""
    items = state["items"]

    if not text and not items:
        state["step"] = "done"
        return await show_panel(
            client, state, "❌ دکمه‌ی خالی ذخیره نشد.",
            InlineKeyboardMarkup([[InlineKeyboardButton(
                "« بازگشت به دکمه‌ها",
                callback_data=f"btns:{token.split(':')[0]}")]]),
        )

    first_kind = items[0]["kind"] if items else "text"
    button_id = db.add_button(
        token, title, first_kind if not text or items else "text", text,
        file_path=None,
    )

    item_ids = [
        db.add_button_item(token, button_id, it["kind"], it["path"])
        for it in items
    ]
    target_id = item_ids[target_index] if 0 <= target_index < len(item_ids) else -1
    db.set_caption_target(token, button_id, target_id)

    state["step"] = "done"
    where = "جداگانه"
    if target_id != -1:
        where = f"روی {STAGE_LABEL[items[target_index]['kind']]}"
    summary = (
        f"✅ <b>دکمه «{esc(title)}» ساخته شد</b>\n"
        f"──────────────\n"
        f"{basket_lines(state)}\n"
        f"محل متن: {where}\n"
        f"──────────────"
    )
    tid = token.split(":")[0]
    await show_panel(
        client, state, summary,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("👁 پیش‌نمایش", callback_data=f"btnprev:{tid}:{button_id}")],
            [InlineKeyboardButton("➕ دکمه دیگر", callback_data=f"addbtn:{tid}"),
             InlineKeyboardButton("« دکمه‌ها", callback_data=f"btns:{tid}")],
        ]),
    )


# ───────────────────────────────────────────── دریافت محتوای کاربر
async def collect(client: Client, state: dict, message: Message) -> bool:
    """محتوای فرستاده‌شده را در سبد می‌گذارد. False = نوع اشتباه بود."""
    stage = state["stage"]

    if stage == "text":
        txt = media.get_text(message)
        if not txt.strip():
            return False
        state["text"] = txt
        await advance(client, state)
        return True

    kind = media.detect_kind(message)
    obj = getattr(message, kind, None) if kind != "text" else None
    mime = getattr(obj, "mime_type", "") or ""
    # fix: کامنت با کد هماهنگ شد — رسانه‌ای که به‌صورت «فایل» فرستاده شده
    # هم پذیرفته می‌شود: تصویر (mime تصویری) در مرحلهٔ عکس، و هر رسانه‌ای
    # در مرحلهٔ فایل. بقیهٔ مراحل فقط نوع دقیق خودشان را می‌پذیرند.
    if stage == "photo" and kind == "document" and mime.startswith("image/"):
        kind = "photo"
    if kind != stage and not (stage == "document" and kind != "text"):
        return False

    path = await media.save_media(client, message, subdir=state["token"].split(":")[0])
    if not path:
        return False

    state["items"].append({"kind": stage, "path": path})
    # کپشن رسانه، اگر هنوز متنی نداریم، به‌عنوان متن دکمه در نظر گرفته می‌شود
    caption = media.get_text(message)
    if caption and not state.get("text"):
        state["text"] = caption

    await ask_stage(client, state, stage)   # «مورد دیگری اضافه شود؟»
    return True
