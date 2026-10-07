"""مدیریت چرخه‌ی حیات ربات‌های فرزند (اجرا/توقف بدون ری‌استارت پروژه)."""
from __future__ import annotations

import compat  # noqa: F401  ← باید قبل از pyrogram ایمپورت شود

import asyncio
import logging
import re

from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    RPCError,
    UserIsBlocked,
)

import config
import db
import media
from child.runtime import build_client

log = logging.getLogger("manager")

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")

_clients: dict[str, Client] = {}


def is_running(token: str) -> bool:
    return token in _clients


def running_count() -> int:
    return len(_clients)


def get_client(token: str) -> Client | None:
    return _clients.get(token)


async def validate_token(token: str) -> tuple[bool, str, int, str]:
    """اعتبارسنجی توکن با اتصال موقت. خروجی: (ok, پیام, bot_id, username)"""
    if not TOKEN_RE.match(token):
        return False, "فرمت توکن نامعتبر است.", 0, ""
    probe = Client(
        name=f"probe_{token.split(':')[0]}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=token,
        workdir=str(config.SESSIONS_DIR),
        in_memory=True,
        no_updates=True,
    )
    try:
        await probe.start()
        me = await probe.get_me()
        return True, "ok", me.id, me.username or ""
    except RPCError as e:
        return False, f"توکن پذیرفته نشد: {e}", 0, ""
    except Exception as e:  # noqa: BLE001
        return False, f"خطا در بررسی توکن: {e}", 0, ""
    finally:
        try:
            await probe.stop()
        except Exception:  # noqa: BLE001, S110
            pass


async def start_bot(token: str) -> tuple[bool, str]:
    if token in _clients:
        return True, "از قبل در حال اجراست."
    row = db.get_bot(token)
    if not row:
        return False, "این ربات در دیتابیس نیست."
    app = build_client(token, row["owner_id"], name=f"child_{row['bot_id']}")
    try:
        await app.start()
    except Exception as e:  # noqa: BLE001
        log.exception("اجرای ربات ناموفق بود")
        db.set_active(token, False)
        return False, f"اجرا نشد: {e}"
    _clients[token] = app
    db.set_active(token, True)
    log.info("ربات @%s اجرا شد", row["username"])
    return True, "اجرا شد."


async def stop_bot(token: str) -> None:
    app = _clients.pop(token, None)
    if app:
        try:
            await app.stop()
        except Exception:  # noqa: BLE001, S110
            pass
    db.set_active(token, False)


async def restart_bot(token: str) -> tuple[bool, str]:
    await stop_bot(token)
    await asyncio.sleep(0.5)
    return await start_bot(token)


async def start_all() -> None:
    rows = db.all_bots(active_only=True)
    log.info("در حال اجرای %d ربات ذخیره‌شده...", len(rows))
    for row in rows:
        ok, msg = await start_bot(row["token"])
        if not ok:
            log.warning("@%s: %s", row["username"], msg)
        await asyncio.sleep(0.3)


async def stop_all() -> None:
    for token in list(_clients):
        await stop_bot(token)


async def broadcast(token: str, payload: dict, progress_cb=None) -> tuple[int, int]:
    """ارسال یک «بسته‌ی محتوا» به همه کاربران ربات فرزند.

    ⚠️ مهم: ارسال باید با کلاینتِ خودِ ربات فرزند انجام شود، نه ربات مادر.
    ربات مادر اجازه‌ی پیام دادن به کاربرانی که آن را استارت نکرده‌اند ندارد
    (خطای PEER_ID_INVALID) — دلیل ارسال نشدن پیام همگانی همین بود.

    payload از media.build_payload می‌آید: {"kind", "text", "path"}
    """
    app = _clients.get(token)
    if not app:
        log.warning("پیام همگانی: ربات در حال اجرا نیست.")
        return 0, 0

    users = db.bot_user_ids(token)
    log.info("پیام همگانی برای %d کاربر آغاز شد.", len(users))
    cache_key = f"bc:{payload.get('path') or 'text'}"
    ok = fail = 0

    for i, uid in enumerate(users, 1):
        try:
            sent = await media.send_content(
                app,
                uid,
                kind=payload.get("kind", "text"),
                text=payload.get("text", ""),
                file_path=payload.get("path"),
                token=token,
                cache_key=cache_key,
            )
            if sent:
                ok += 1
            else:
                fail += 1
        except FloodWait as e:
            log.warning("FloodWait: %s ثانیه صبر می‌کنیم", e.value)
            await asyncio.sleep(e.value + 1)
            try:
                await media.send_content(
                    app, uid, kind=payload.get("kind", "text"),
                    text=payload.get("text", ""), file_path=payload.get("path"),
                    token=token, cache_key=cache_key,
                )
                ok += 1
            except Exception:  # noqa: BLE001
                fail += 1
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            db.mark_blocked(token, uid)
            fail += 1
        except RPCError as e:
            log.warning("ارسال به %s ناموفق: %s", uid, e)
            fail += 1
        except Exception as e:  # noqa: BLE001
            log.error("خطای غیرمنتظره در ارسال به %s: %s", uid, e)
            fail += 1

        if progress_cb and i % 20 == 0:
            await progress_cb(ok, fail)
        await asyncio.sleep(0.05)  # رعایت محدودیت نرخ تلگرام

    log.info("پیام همگانی تمام شد. موفق=%d ناموفق=%d", ok, fail)
    return ok, fail
