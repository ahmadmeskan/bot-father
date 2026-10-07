"""compat.py — لایه سازگاری برای پایتون ۳.۱۲+ (مخصوصاً ۳.۱۴ در ترموکس).

⚠️ این ماژول باید **قبل از هر import مربوط به pyrogram** ایمپورت شود.

چرا لازم است؟
    از پایتون ۳.۱۴ تابع asyncio.get_event_loop() دیگر به‌صورت خودکار لوپ نمی‌سازد
    و RuntimeError می‌دهد. Pyrogram 2.0.106 در سه جا از آن استفاده می‌کند:
        • pyrogram/sync.py:31        → موقع import  (همان خطای اولیه)
        • pyrogram/client.py:299     → self.loop = get_event_loop()
        • pyrogram/dispatcher.py:58  → self.loop = get_event_loop()

    اگر فقط خطای اول را با set_event_loop() رفع کنیم ولی بعداً برنامه را با
    asyncio.run() اجرا کنیم، یک لوپ *دیگر* ساخته می‌شود؛ آن‌وقت Client روی
    لوپِ اول قفل شده و دیسپچر هیچ آپدیتی را پردازش نمی‌کند →
    ربات بالا می‌آید، لاگ تمیز است، ولی به /start جواب نمی‌دهد.

راه‌حل: یک لوپ می‌سازیم، آن را لوپ پیش‌فرض می‌کنیم و *کل برنامه* را
روی همان یک لوپ اجرا می‌کنیم (به‌جای asyncio.run).
"""
from __future__ import annotations

import asyncio
import signal
import sys

# --- یک لوپ واحد برای کل عمر برنامه ---
try:
    LOOP = asyncio.get_running_loop()          # اگر از قبل لوپی در حال اجراست
except RuntimeError:
    LOOP = asyncio.new_event_loop()

asyncio.set_event_loop(LOOP)

# --- تور ایمنی ---
# اگر جایی (حتی کتابخانه‌ای دیگر) بیرون از یک لوپِ در حال اجرا
# asyncio.get_event_loop() را صدا بزند، در پایتون ۳.۱۴ خطا می‌دهد.
# اینجا وادارش می‌کنیم همان LOOP بالا را برگرداند تا همه‌ی اجزا روی یک لوپ بمانند.
_original_get_event_loop = asyncio.get_event_loop


def _safe_get_event_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return LOOP


asyncio.get_event_loop = _safe_get_event_loop


def run(coro):
    """جایگزین asyncio.run — روی همان لوپی اجرا می‌کند که pyrogram می‌شناسد."""
    try:
        return LOOP.run_until_complete(coro)
    finally:
        try:
            pending = asyncio.all_tasks(LOOP)
            for task in pending:
                task.cancel()
            if pending:
                LOOP.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:  # noqa: BLE001, S110
            pass


async def idle() -> None:
    """جایگزین pyrogram.idle بدون وابستگی به pyrogram.sync.

    تا رسیدن Ctrl+C یا SIGTERM منتظر می‌ماند.
    """
    stop = asyncio.Event()

    def _signal_handler(*_):
        stop.set()

    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGABRT)
    for s in signals:
        try:
            LOOP.add_signal_handler(s, _signal_handler)
        except (NotImplementedError, RuntimeError, AttributeError):
            # ویندوز یا محیط‌هایی که add_signal_handler ندارند
            try:
                signal.signal(s, _signal_handler)
            except Exception:  # noqa: BLE001, S110
                pass

    await stop.wait()

    for s in signals:
        try:
            LOOP.remove_signal_handler(s)
        except Exception:  # noqa: BLE001, S110
            pass


def report() -> None:
    print(
        f"[compat] python={sys.version.split()[0]}  loop={id(LOOP)}  "
        f"running={LOOP.is_running()}"
    )
