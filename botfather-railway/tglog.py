"""tglog.py — ارسال خطاها و رویدادهای مهم به یک چت تلگرام (مستقل از Pyrogram).

چرا مستقل؟ چون وقتی خود ربات کرش کند یا در استارتاپ بمیرد، Pyrogram هم
مرده است؛ این ماژول فقط با urllib به Bot API وصل می‌شود و گزارش می‌فرستد.

نحوه فعال‌سازی (در .env):
    LOG_TOKEN=123456:AA...     ← توکن یک ربات گزارش‌گیر جدا (از @BotFather)
    LOG_CHAT=123456789         ← chat_id شما (به همان ربات /start بدهید)

اگر مقداردهی نشده باشد، بی‌صدا غیرفعال می‌ماند و چیزی نمی‌فرستد.
ویژگی‌ها:
    • tglog.error(exc, "context")   → پیام فوری خطا (+ ثبت در لاگ)
    • tglog.event("ربات اجرا شد")    → رویدادهای مهم (استارت/استاپ)
    • tglog.setup_root_logger()     → ERROR/CRITICAL همه‌ی لاگرها به تلگرام
    • tglog.check()                 → تست اتصال (برای deploy.sh / doctor.py)
    • محدودیت نرخ درون پروسه: متن یکسان حداکثر یک‌بار در ۳۰ ثانیه
    • صف پس‌زمینه + ارسال مجدد با backoff؛ خیلی سریع است، I/O را بلاک نمی‌کند
"""
from __future__ import annotations

import atexit
import datetime as dt
import json
import logging
import os
import queue
import threading
import time
import traceback
import urllib.parse
import urllib.request

BASE = "https://api.telegram.org/bot{}/{}"

# ── تنظیمات از محیط (فقط یک‌بار، هنگام import، خوانده می‌شود) ──
_TOKEN = os.getenv("LOG_TOKEN", "").strip() or None
_CHAT = os.getenv("LOG_CHAT", "").strip() or None

_MAX_LEN = 3500          # سقف طول پیام (حد تلگرام 4096)
_RATE_LIMIT_S = 30       # یک متن یکسان حداکثر یک‌بار در این فاصله
_QUEUE_MAX = 100         # سقف صف ارسال

_last_sent: dict[str, float] = {}
_queue: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=_QUEUE_MAX)
_stats = {"sent": 0, "dropped": 0, "fail": 0}
_lock = threading.Lock()
_worker_started = False


def is_enabled() -> bool:
    return bool(_TOKEN and _CHAT)


def _api_url(method: str) -> str:
    return BASE.format(_TOKEN, method)


def _post(method: str, params: dict) -> dict:
    """POST به Bot API؛ استثناها بالا می‌روند تا caller دوباره تلاش کند."""
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(_api_url(method), data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))
    if not body.get("ok"):
        raise RuntimeError(f"telegram api: {body}")
    return body


def _send_now(text: str) -> None:
    _post(
        "sendMessage",
        {
            "chat_id": _CHAT,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )


def _worker() -> None:
    """فرستنده‌ی پس‌زمینه: از صف برمی‌دارد و با backoff ارسال می‌کند."""
    while True:
        item = _queue.get()
        if item is None:  # دستور خروج
            return
        text = item
        for attempt in range(4):
            try:
                _send_now(text)
                with _lock:
                    _stats["sent"] += 1
                break
            except Exception:
                with _lock:
                    _stats["fail"] += 1
                time.sleep(2 ** attempt)  # 1, 2, 4 ثانیه
        else:
            with _lock:
                _stats["dropped"] += 1


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        threading.Thread(target=_worker, daemon=True).start()
        _worker_started = True


def _enqueue(text: str) -> None:
    if not is_enabled():
        return
    now = time.monotonic()
    with _lock:
        last = _last_sent.get(text, 0)
        if now - last < _RATE_LIMIT_S:   # ضد اسپم: تکراریِ تازه‌ارسال‌شده
            return
        _last_sent[text] = now
    try:
        _queue.put_nowait(text)
        _ensure_worker()
    except queue.Full:
        with _lock:
            _stats["dropped"] += 1


def _ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt_err(exc: BaseException | None, msg: str, title: str) -> str:
    lines = [f"<b>{title}</b>", f"🕐 {_ts()}"]
    if msg:
        lines.append(f"📌 {msg}")
    if exc is not None:
        tb = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).strip()
        lines.append(f"<pre>{tb[-3000:]}</pre>")
    return "\n".join(lines)[:_MAX_LEN]


# ── API عمومی ──

def event(msg: str) -> None:
    """رویداد مهم (استارت/استاپ/ری‌استارت)."""
    _enqueue(f"ℹ️ <b>رویداد</b>\n🕐 {_ts()}\n{msg}")


def error(exc: BaseException | None = None, msg: str = "") -> None:
    """خطای مهم — هم به تلگرام می‌رود هم به لاگ استاندارد (journald)."""
    text = _fmt_err(exc, msg, "🚨 خطا")
    logging.getLogger("tglog").exception("tglog: %s", msg or exc) if exc else \
        logging.getLogger("tglog").error("tglog: %s", msg)
    _enqueue(text)


def warning(msg: str) -> None:
    """هشدار — کم‌اهمیت‌تر از error ولی ارزش اطلاع دارد."""
    logging.getLogger("tglog").warning("%s", msg)
    _enqueue(f"⚠️ <b>هشدار</b>\n🕐 {_ts()}\n{msg}")


def stats() -> dict:
    """آمار گزارش‌گر: sent / dropped / fail."""
    with _lock:
        return dict(_stats)


def flush(timeout: float = 3.0) -> None:
    """ارسال هم‌زمانِ پیام‌های باقیمانده در صف (حداکثر `timeout` ثانیه).

    قبل از خروج/کرش صدا زده می‌شود تا گزارش‌ها گم نشوند.
    """
    if not is_enabled():
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            text = _queue.get_nowait()
        except queue.Empty:
            return
        if text is None:
            continue
        try:
            _send_now(text)
            with _lock:
                _stats["sent"] += 1
        except Exception:
            break


# ── اتصال به سیستم logging پایتون ──

class TelegramHandler(logging.Handler):
    """رکوردهای ERROR+ لاگر ریشه را به تلگرام می‌فرستد."""

    def __init__(self, level=logging.ERROR):
        super().__init__(level=level)
        self.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            exc = record.exc_info[1] if record.exc_info else None
            _enqueue(_fmt_err(exc, msg, "🚨 خطا (لاگر)"))
        except Exception:
            self.handleError(record)


def setup_root_logger() -> None:
    """ERROR/CRITICAL همه‌ی لاگرها به تلگرام می‌رود (فقط اگر تنظیم شده)."""
    if is_enabled():
        logging.getLogger().addHandler(TelegramHandler())


@atexit.register
def _flush_on_exit() -> None:
    """خروج تمیز: تا ۵ پیامِ باقیمانده در صف را هم‌زمان می‌فرستد."""
    if not is_enabled():
        return
    for _ in range(5):
        try:
            text = _queue.get_nowait()
        except queue.Empty:
            break
        if text is None:
            continue
        try:
            _send_now(text)
        except Exception:
            break


def check() -> tuple[bool, str]:
    """اعتبارسنجی توکن/چت — پیام تست واقعی می‌فرستد."""
    if not _TOKEN:
        return False, "LOG_TOKEN تنظیم نشده"
    if not _CHAT:
        return False, "LOG_CHAT تنظیم نشده"
    try:
        body = _post("getMe", {})
        name = body.get("result", {}).get("username", "?")
        _post(
            "sendMessage",
            {"chat_id": _CHAT, "text": "✅ تست اتصال لاگ‌گیر"},
        )
        return True, f"ربات لاگ @{name} به چت {_CHAT} وصل است"
    except Exception as e:
        return False, f"خطا در اتصال: {e}"
