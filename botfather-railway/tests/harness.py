"""زیرساخت مشترک تست‌ها: محیط ایزوله، کلاینت جعلی و توابع کمکی."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

# ---- محیط تست ----
_TMP = tempfile.mkdtemp(prefix="botfather_test_")
os.environ.update(
    API_ID="12345",
    API_HASH="a" * 32,
    MOTHER_TOKEN="111111111:AA" + "m" * 33,
    ADMINS="900,901",
    MAX_BOTS_PER_USER="3",
)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import compat  # noqa: E402  ← قبل از pyrogram
import config  # noqa: E402

config.DB_PATH = __import__("pathlib").Path(_TMP) / "test.db"
config.SESSIONS_DIR = __import__("pathlib").Path(_TMP) / "sessions"
config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

import db  # noqa: E402
import media  # noqa: E402

media.MEDIA_DIR = __import__("pathlib").Path(_TMP) / "media"
media.MEDIA_DIR.mkdir(parents=True, exist_ok=True)

import manager  # noqa: E402
from child import runtime  # noqa: E402
from tests.fake_telegram import (  # noqa: E402
    FakeCallbackQuery,
    FakeClient,
    FakeMessage,
    FakeUser,
    dispatch,
)

CHILD_TOKEN = "222222222:AA" + "c" * 33
OWNER = 500
USER = 777
ADMIN = 900

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    print(f"  {'✅' if condition else '❌'} {name}" + (f"  → {detail}" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n{'─' * 60}\n▶ {title}\n{'─' * 60}")


def reset_db() -> None:
    runtime._member_cache.clear()
    runtime._misconfig_notified.clear()
    runtime._support_mode.clear()
    runtime._search_mode.clear()
    runtime._pass_mode.clear()
    runtime._demo_stage.clear()
    db.delete_bot(CHILD_TOKEN)
    db.add_bot(CHILD_TOKEN, 222222222, "child_bot", OWNER)
