"""نقطه شروع پروژه: اجرای ربات مادر + همه ربات‌های فرزند ذخیره‌شده.

⚠️ ترتیب import ها مهم است: compat باید قبل از pyrogram بیاید.
"""
from __future__ import annotations

import compat  # noqa: F401  ← حتماً اولین import باشد (سازگاری پایتون ۳.۱۴)

import asyncio
import logging
from logging.handlers import RotatingFileHandler

import config  # noqa: F401  ← .env را بارگذاری می‌کند
import tglog  # ← بعد از config: LOG_TOKEN/LOG_CHAT از .env خوانده شود
import db
import manager

# --- لاگ: هم روی کنسول (journald) هم فایل چرخشی ---
_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
config.SESSIONS_DIR.parent.mkdir(parents=True, exist_ok=True)
_logs_dir = config.BASE_DIR / "data" / "logs"
_logs_dir.mkdir(parents=True, exist_ok=True)

_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter(_FMT, datefmt="%H:%M:%S"))
_file = RotatingFileHandler(
    _logs_dir / "bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_file.setFormatter(logging.Formatter(_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
logging.basicConfig(level=logging.INFO, handlers=[_console, _file])
logging.getLogger("pyrogram").setLevel(logging.WARNING)

# --- خطاهای ERROR/CRITICAL همه‌ی ماژول‌ها به تلگرام می‌رود ---
tglog.setup_root_logger()

log = logging.getLogger("main")


async def main() -> None:
    config.validate()
    db.init()

    from mother.bot import app as mother_app  # پس از اعتبارسنجی کانفیگ

    # --- بررسی سلامت لوپ: اگر این هشدار را دیدید یعنی ربات ساکت خواهد ماند ---
    running = asyncio.get_running_loop()
    if getattr(mother_app, "loop", running) is not running:
        log.error(
            "ناسازگاری event loop! Client روی لوپ دیگری ساخته شده است. "
            "مطمئن شوید main.py را اجرا می‌کنید و compat اولین import است."
        )
        tglog.warning("ناسازگاری event loop — در حال اصلاح خودکار")
        mother_app.loop = running  # اصلاح در لحظه

    await mother_app.start()
    me = await mother_app.get_me()
    log.info("ربات مادر @%s اجرا شد. (loop=%s)", me.username, id(running))
    tglog.event(f"🤖 ربات مادر <b>@{me.username}</b> اجرا شد")

    # کلاینت مادر را در اختیار فرزندان بگذار (fallback تیکت پشتیبانی)
    from child.runtime import set_mother_client
    set_mother_client(mother_app)

    await manager.start_all()
    log.info("آماده. تعداد ربات‌های فعال: %d", manager.running_count())
    tglog.event(f"✅ همه آماده — {manager.running_count()} ربات فرزند فعال")

    await compat.idle()

    log.info("در حال خاموش کردن...")
    await manager.stop_all()
    await mother_app.stop()
    tglog.event("👋 خاموشی تمیز (سیگنال استاپ)")


if __name__ == "__main__":
    exit_code = 0
    try:
        compat.run(main())
    except KeyboardInterrupt:
        pass
    except BaseException as exc:  # noqa: BLE001 — کرش باید گزارش شود
        log.critical("کرش قطعی: %s", exc, exc_info=exc)
        tglog.error(exc, "💥 کرش ربات — systemd ظرف ۱۰ ثانیه دوباره اجرا می‌کند")
        tglog.flush()
        exit_code = 1
    tglog.flush()
    raise SystemExit(exit_code)
