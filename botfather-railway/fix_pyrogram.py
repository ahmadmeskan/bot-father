"""fix_pyrogram.py — وصله‌ی دائمی Pyrogram برای پایتون ۳.۱۲+ / ۳.۱۴

مشکل:
    Pyrogram 2.0.106 در چند فایل از asyncio.get_event_loop() استفاده می‌کند.
    در پایتون ۳.۱۴ این تابع دیگر لوپ نمی‌سازد و RuntimeError می‌دهد:
        RuntimeError: There is no current event loop in thread 'MainThread'

راه‌حل:
    این اسکریپت خودِ فایل‌های نصب‌شده‌ی pyrogram را اصلاح می‌کند.
    بعد از اجرای آن، «هر جا و به هر ترتیبی» pyrogram را ایمپورت کنید کار می‌کند.

استفاده:
    python fix_pyrogram.py            # اعمال وصله
    python fix_pyrogram.py --restore  # برگرداندن فایل‌های اصلی
"""
from __future__ import annotations

import os
import re
import shutil
import sys

HELPER = '''
# ---- termux/python3.14 event-loop fix (توسط fix_pyrogram.py اضافه شد) ----
import asyncio as _aio_fix


def _pyro_get_event_loop():
    """جایگزین امن asyncio.get_event_loop() برای پایتون ۳.۱۲+"""
    try:
        return _aio_fix.get_running_loop()
    except RuntimeError:
        try:
            _loop = _aio_fix.get_event_loop_policy().get_event_loop()
            if not _loop.is_closed():
                return _loop
        except Exception:
            pass
        _loop = _aio_fix.new_event_loop()
        _aio_fix.set_event_loop(_loop)
        return _loop
# ---- end fix ----
'''

MARKER = "_pyro_get_event_loop"
PATTERN = re.compile(r"asyncio\.get_event_loop\(\)")


def find_pyrogram() -> str:
    try:
        import importlib.util

        spec = importlib.util.find_spec("pyrogram")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"❌ pyrogram پیدا نشد: {e}")
    if not spec or not spec.origin:
        sys.exit("❌ پکیج pyrogram نصب نیست. اول: pip install pyrogram")
    return os.path.dirname(spec.origin)


def insert_helper(text: str) -> str:
    """هِلپر را بعد از خطوط __future__ و قبل از اولین import واقعی می‌گذارد."""
    lines = text.splitlines(keepends=True)
    idx = 0
    in_doc = False
    doc_q = ""
    for i, line in enumerate(lines):
        s = line.strip()
        if in_doc:
            if doc_q in s:
                in_doc = False
            idx = i + 1
            continue
        if not s or s.startswith("#"):
            idx = i + 1
            continue
        if s.startswith(('"""', "'''")):
            doc_q = s[:3]
            if not (len(s) > 3 and s.endswith(doc_q)):
                in_doc = True
            idx = i + 1
            continue
        if s.startswith("from __future__"):
            idx = i + 1
            continue
        idx = i
        break
    lines.insert(idx, HELPER)
    return "".join(lines)


def patch(restore: bool = False) -> None:
    root = find_pyrogram()
    print(f"📦 مسیر pyrogram: {root}\n")
    changed = 0

    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(dirpath, fname)
            backup = path + ".orig"

            if restore:
                if os.path.exists(backup):
                    shutil.move(backup, path)
                    print(f"↩️  بازگردانی: {os.path.relpath(path, root)}")
                    changed += 1
                continue

            try:
                text = open(path, encoding="utf-8").read()
            except Exception:  # noqa: BLE001
                continue

            if MARKER in text or not PATTERN.search(text):
                continue

            if not os.path.exists(backup):
                shutil.copy2(path, backup)

            n = len(PATTERN.findall(text))
            new_text = PATTERN.sub("_pyro_get_event_loop()", text)
            new_text = insert_helper(new_text)

            # اطمینان از سالم بودن سینتکس قبل از نوشتن
            try:
                compile(new_text, path, "exec")
            except SyntaxError as e:
                print(f"⚠️  رد شد (سینتکس): {os.path.relpath(path, root)} → {e}")
                continue

            open(path, "w", encoding="utf-8").write(new_text)
            print(f"✅ وصله شد ({n} مورد): {os.path.relpath(path, root)}")
            changed += 1

    print()
    if restore:
        print(f"↩️  {changed} فایل به حالت اول برگشت.")
        return
    if not changed:
        print("ℹ️  چیزی برای وصله کردن نبود (احتمالاً قبلاً وصله شده).")
    else:
        print(f"🎉 {changed} فایل وصله شد.")

    print("\n🔍 تست نهایی...")
    os.system(
        f'{sys.executable} -c "import pyrogram; '
        f"print('✅ import pyrogram موفق بود — نسخه', pyrogram.__version__)\""
    )


if __name__ == "__main__":
    patch(restore="--restore" in sys.argv)
