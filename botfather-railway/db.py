"""لایه دیتابیس — SQLite بدون وابستگی اضافی."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Iterable

import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    token       TEXT PRIMARY KEY,
    bot_id      INTEGER,
    username    TEXT,
    owner_id    INTEGER NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    token   TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT,
    PRIMARY KEY (token, key)
);

CREATE TABLE IF NOT EXISTS buttons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'text',  -- text | photo | video | document | ...
    body        TEXT,                          -- متن یا کپشن
    file_id     TEXT,                          -- (منسوخ) file_id ربات مادر
    file_path   TEXT,                          -- مسیر فایل روی دیسک
    position    INTEGER NOT NULL DEFAULT 0,
    -- قفل زیرمجموعه‌گیری برای همین دکمه (مستقل از بقیه دکمه‌ها):
    ref_req     INTEGER NOT NULL DEFAULT 0,   -- 1 = باز کردن این دکمه نیاز به دعوت دارد
    ref_count   INTEGER NOT NULL DEFAULT 0    -- تعداد لازم برای این دکمه (۰ = همان تعداد کلی)
);

-- محتوای چندتایی هر دکمه: یک دکمه می‌تواند متن + چند عکس/ویدیو/فایل داشته باشد
CREATE TABLE IF NOT EXISTS button_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL,
    button_id   INTEGER NOT NULL,
    kind        TEXT NOT NULL,      -- photo | video | document | audio | voice | animation
    file_path   TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_items_button ON button_items(token, button_id);

-- آخرین باری که پیام وظیفه اجباری برای هر کاربر نمایش داده شده
CREATE TABLE IF NOT EXISTS task_state (
    token       TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    done_at     INTEGER NOT NULL,
    done_ms     INTEGER,
    PRIMARY KEY (token, user_id)
);

-- آمار بازدید هر دکمه (هر بار ارسال محتوا = یک بازدید)
CREATE TABLE IF NOT EXISTS file_stats (
    token       TEXT NOT NULL,
    button_id   INTEGER NOT NULL,
    views       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (token, button_id)
);

-- لایک/دیسلایک کاربران روی فایل‌ها (هر کاربر per دکمه یک رأی؛ ۱=لایک، -۱=دیسلایک)
CREATE TABLE IF NOT EXISTS file_votes (
    token       TEXT NOT NULL,
    button_id   INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    value       INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (token, button_id, user_id)
);

-- وضعیت‌های per-user (مثل «پسورد را درست وارد کرده») 
CREATE TABLE IF NOT EXISTS user_state (
    token       TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT,
    updated_at  INTEGER,
    PRIMARY KEY (token, user_id, key)
);

-- ری‌اکشن‌های نسخه‌ی قدیمی وظیفه — دیگر استفاده نمی‌شود؛ فقط برای
-- مهاجرتِ بی‌دردسر نگه داشته می‌شود (جدول‌های قدیمی پاک‌نشده)
CREATE TABLE IF NOT EXISTS reactions (
    token       TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    created_ms  INTEGER,
    PRIMARY KEY (token, user_id, chat_id, msg_id)
);

CREATE INDEX IF NOT EXISTS idx_reactions_user ON reactions(token, user_id, created_at);

-- پست‌های کانالِ نسخه‌ی قدیمی وظیفه — منسوخ (نگهداری برای سازگاری)
CREATE TABLE IF NOT EXISTS channel_posts (
    token       TEXT NOT NULL,
    chat_id     INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,
    date_ms     INTEGER NOT NULL,
    PRIMARY KEY (token, chat_id, msg_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_recent ON channel_posts(token, date_ms DESC);

-- کش file_id به‌ازای هر ربات؛ چون file_id بین ربات‌ها قابل استفاده نیست
CREATE TABLE IF NOT EXISTS file_cache (
    token       TEXT NOT NULL,
    key         TEXT NOT NULL,
    file_id     TEXT NOT NULL,
    PRIMARY KEY (token, key)
);

CREATE TABLE IF NOT EXISTS bot_users (
    token       TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    first_name  TEXT,
    username    TEXT,
    joined_at   INTEGER NOT NULL,
    blocked     INTEGER NOT NULL DEFAULT 0,
    age         INTEGER,                -- سن اعلام‌شده کاربر (اختیاری)
    gender      TEXT,                   -- 'm' | 'f' (اختیاری)
    PRIMARY KEY (token, user_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    owner_msg_id INTEGER,
    created_at  INTEGER NOT NULL
);

-- تیکت‌های پشتیبانی ربات مادر (ممکن است چند ادمین داشته باشیم،
-- پس کلید ترکیبی chat_id + msg_id لازم است)
CREATE TABLE IF NOT EXISTS dm_tickets (
    scope       TEXT NOT NULL,
    chat_id     INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (scope, chat_id, msg_id)
);

-- زیرمجموعه‌ها (مدل توکن): هر دعوت موفق = ۱ توکن در استخر کلی دعوت‌کننده.
-- used=0 یعنی توکن مصرف‌نشده (قابل خرج برای باز کردن هر دکمه قفل‌دار)،
-- used=1 یعنی سوخته (فقط در آمار می‌ماند).
CREATE TABLE IF NOT EXISTS referrals (
    token       TEXT NOT NULL,
    inviter_id  INTEGER NOT NULL,
    invited_id  INTEGER NOT NULL,
    joined_at   INTEGER NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    used_at     INTEGER,
    PRIMARY KEY (token, invited_id)
);

CREATE INDEX IF NOT EXISTS idx_ref_inviter ON referrals(token, inviter_id);

CREATE INDEX IF NOT EXISTS idx_buttons_token ON buttons(token);
CREATE INDEX IF NOT EXISTS idx_users_token ON bot_users(token);
CREATE INDEX IF NOT EXISTS idx_tickets_msg ON tickets(token, owner_msg_id);
"""

DEFAULT_SETTINGS = {
    "welcome": "سلام {name} 👋\nبه ربات خوش آمدید.",
    "force_channels": "[]",   # لیست JSON از کانال‌های اجباری
    "force_channel": "",      # (منسوخ) فقط برای مهاجرت از نسخه‌های قبل
    "owner_bypass": "0",      # 1 = مالک ربات از عضویت اجباری معاف باشد
    "join_text": "",          # پیام عضویت اجباری (خالی = متن پیش‌فرض)
    "check_ttl": "0",         # ثانیه‌های کش بررسی عضویت (0 = هر بار بررسی شود)
    "support": "1",
    "footer_text": "",        # پیام پایانی بعد از هر محتوا (خالی = خاموش)
    "blocked_text": "⛔️ دسترسی شما به این ربات مسدود شده است.",
    # ── وظیفه اجباری (تأیید عضویت + پنجره‌ی ۲ دقیقه) ──
    "task_enabled": "0",
    "task_channel": "",
    "task_text": "",
    "task_completions": "0",   # مجموع دفعات تأیید وظیفه (آمار)
    # ── قابلیت‌های ربات ──
    "autodel": "0",           # حذف خودکار محتوا بعد از N ثانیه (۰ = خاموش)
    "file_pass": "",           # پسورد فایل‌ها (خالی = غیرفعال)
    "rnd_enabled": "0",       # دکمه «فایل رندوم» در منو
    "search_enabled": "0",    # دکمه «جستجوی فایل» در منو
    "demo_ask": "0",          # پرسیدن سن و جنسیت از کاربران جدید
    "votes_enabled": "1",     # دکمه لایک/دیسلایک زیر فایل‌ها
    # ── زیرمجموعه‌گیری ──
    "ref_enabled": "0",       # 1 = فعال
    "ref_count": "0",         # چند نفر باید دعوت شوند (۰ = هنوز تنظیم نشده)
    "ref_text": "",           # متن پیام دعوت (خالی = پیش‌فرض)
    "ref_photo_path": "",     # مسیر عکس پیام دعوت روی دیسک (خالی = بدون عکس)
}


def init() -> None:
    global _conn
    with _lock:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        # fix: حالت WAL خواندن/نوشتن هم‌زمان را بی‌قفل می‌کند و فشار دیسک
        # را در ربات‌های پرکاربر کم می‌کند؛ busy_timeout هم از خطای
        # «database is locked» در تداخل‌های لحظه‌ای جلوگیری می‌کند.
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.executescript(SCHEMA)
        _migrate()
        _conn.commit()


def _migrate() -> None:
    """ستون‌های جدید را به دیتابیس‌های قدیمی اضافه می‌کند (بدون از دست رفتن داده)."""
    assert _conn is not None
    cols = {r["name"] for r in _conn.execute("PRAGMA table_info(buttons)")}
    if "file_path" not in cols:
        _conn.execute("ALTER TABLE buttons ADD COLUMN file_path TEXT")
        print("[db] ستون file_path به جدول buttons اضافه شد.")
    ucols = {r["name"] for r in _conn.execute("PRAGMA table_info(bot_users)")}
    if "blocked_at" not in ucols:
        _conn.execute("ALTER TABLE bot_users ADD COLUMN blocked_at INTEGER")
        print("[db] ستون blocked_at به جدول bot_users اضافه شد.")
    if "blocked_by" not in ucols:
        _conn.execute("ALTER TABLE bot_users ADD COLUMN blocked_by INTEGER")
        print("[db] ستون blocked_by به جدول bot_users اضافه شد.")
    # fix: ستون‌های دموگرافیک برای آمار سن و جنسیت
    if "age" not in ucols:
        _conn.execute("ALTER TABLE bot_users ADD COLUMN age INTEGER")
        print("[db] ستون age به جدول bot_users اضافه شد.")
    if "gender" not in ucols:
        _conn.execute("ALTER TABLE bot_users ADD COLUMN gender TEXT")
        print("[db] ستون gender به جدول bot_users اضافه شد.")
    if "caption_target" not in cols:
        # -1 یعنی متن جداگانه ارسال شود، در غیر این صورت id آیتمی که
        # متن باید به‌عنوان کپشن به آن بچسبد.
        _conn.execute("ALTER TABLE buttons ADD COLUMN caption_target INTEGER DEFAULT -1")
        print("[db] ستون caption_target به جدول buttons اضافه شد.")
    # fix: قفل زیرمجموعه‌گیری به‌ازای هر دکمه (تعداد لازم هم قابل تنظیم است)
    if "ref_req" not in cols:
        _conn.execute("ALTER TABLE buttons ADD COLUMN ref_req INTEGER NOT NULL DEFAULT 0")
        print("[db] ستون ref_req به جدول buttons اضافه شد.")
    if "ref_count" not in cols:
        _conn.execute("ALTER TABLE buttons ADD COLUMN ref_count INTEGER NOT NULL DEFAULT 0")
        print("[db] ستون ref_count به جدول buttons اضافه شد.")

    # ── دقت میلی‌ثانیه برای ری‌اکشن‌ها و وظیفه ──
    rcols = {r["name"] for r in _conn.execute("PRAGMA table_info(reactions)")}
    if "created_ms" not in rcols:
        _conn.execute("ALTER TABLE reactions ADD COLUMN created_ms INTEGER")
        _conn.execute("UPDATE reactions SET created_ms = created_at * 1000"
                      " WHERE created_ms IS NULL")
        print("[db] ستون created_ms به جدول reactions اضافه شد.")
    tcols = {r["name"] for r in _conn.execute("PRAGMA table_info(task_state)")}
    if "done_ms" not in tcols:
        _conn.execute("ALTER TABLE task_state ADD COLUMN done_ms INTEGER")
        _conn.execute("UPDATE task_state SET done_ms = done_at * 1000"
                      " WHERE done_ms IS NULL")
        print("[db] ستون done_ms به جدول task_state اضافه شد.")

    # ── مدل توکن زیرمجموعه‌گیری: ستون used/used_at برای دعوت‌های قدیمی ──
    # دعوت‌های موجود همه «مصرف‌نشده» در نظر گرفته می‌شوند (هیچ داده‌ای نمی‌سوزد)
    rcols = {r["name"] for r in _conn.execute("PRAGMA table_info(referrals)")}
    if "used" not in rcols:
        _conn.execute("ALTER TABLE referrals ADD COLUMN"
                      " used INTEGER NOT NULL DEFAULT 0")
        print("[db] ستون used به جدول referrals اضافه شد (مدل توکن).")
    if "used_at" not in rcols:
        _conn.execute("ALTER TABLE referrals ADD COLUMN used_at INTEGER")
        print("[db] ستون used_at به جدول referrals اضافه شد.")


def _q(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    assert _conn is not None, "db.init() فراخوانی نشده است"
    with _lock:
        cur = _conn.execute(sql, tuple(params))
        _conn.commit()
        return cur


def fetchone(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return _q(sql, params).fetchone()


def fetchall(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return _q(sql, params).fetchall()


# ---------------------------------------------------------------- ربات‌ها
def add_bot(token: str, bot_id: int, username: str, owner_id: int) -> None:
    _q(
        "INSERT OR REPLACE INTO bots (token, bot_id, username, owner_id, active, created_at)"
        " VALUES (?,?,?,?,1,?)",
        (token, bot_id, username, owner_id, int(time.time())),
    )
    for k, v in DEFAULT_SETTINGS.items():
        _q(
            "INSERT OR IGNORE INTO settings (token, key, value) VALUES (?,?,?)",
            (token, k, v),
        )


def delete_bot(token: str) -> None:
    for table in ("bots", "settings", "buttons", "button_items", "bot_users",
                  "tickets", "file_cache", "reactions", "task_state",
                  "channel_posts", "referrals", "file_stats", "file_votes",
                  "user_state"):
        _q(f"DELETE FROM {table} WHERE token = ?", (token,))


def get_bot(token: str) -> sqlite3.Row | None:
    return fetchone("SELECT * FROM bots WHERE token = ?", (token,))


def user_bots(owner_id: int) -> list[sqlite3.Row]:
    return fetchall(
        "SELECT * FROM bots WHERE owner_id = ? ORDER BY created_at", (owner_id,)
    )


def all_bots(active_only: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM bots"
    if active_only:
        sql += " WHERE active = 1"
    return fetchall(sql)


def set_active(token: str, active: bool) -> None:
    _q("UPDATE bots SET active = ? WHERE token = ?", (int(active), token))


# ---------------------------------------------------------------- تنظیمات
def get_setting(token: str, key: str, default: str = "") -> str:
    row = fetchone("SELECT value FROM settings WHERE token=? AND key=?", (token, key))
    return row["value"] if row and row["value"] is not None else default


def set_setting(token: str, key: str, value: str) -> None:
    _q(
        "INSERT INTO settings (token, key, value) VALUES (?,?,?)"
        " ON CONFLICT(token, key) DO UPDATE SET value = excluded.value",
        (token, key, value),
    )


# --------------------------------------------- کانال‌های عضویت اجباری
def get_channels(token: str) -> list[str]:
    """لیست کانال‌های اجباری. از تنظیم قدیمی تک‌کاناله هم مهاجرت می‌کند."""
    raw = get_setting(token, "force_channels", "").strip()
    channels: list[str] = []
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                channels = [str(c).strip() for c in data if str(c).strip()]
        except (ValueError, TypeError):
            channels = []

    # مهاجرت خودکار از نسخه‌ی قدیمی (تک‌کاناله)
    legacy = get_setting(token, "force_channel", "").strip()
    if legacy:
        if legacy not in channels:
            channels.append(legacy)
        set_setting(token, "force_channel", "")
        set_channels(token, channels)

    return channels


def set_channels(token: str, channels: list[str]) -> None:
    seen, unique = set(), []
    for c in channels:
        c = str(c).strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            unique.append(c)
    set_setting(token, "force_channels", json.dumps(unique, ensure_ascii=False))


def add_channel(token: str, channel: str) -> bool:
    """کانال را اضافه می‌کند. False یعنی از قبل وجود داشت."""
    channels = get_channels(token)
    if any(c.lower() == channel.lower() for c in channels):
        return False
    channels.append(channel)
    set_channels(token, channels)
    return True


def remove_channel(token: str, index: int) -> str | None:
    """کانال با شماره‌ی داده‌شده را حذف و نامش را برمی‌گرداند."""
    channels = get_channels(token)
    if 0 <= index < len(channels):
        removed = channels.pop(index)
        set_channels(token, channels)
        return removed
    return None


def clear_channels(token: str) -> int:
    n = len(get_channels(token))
    set_channels(token, [])
    set_setting(token, "force_channel", "")
    return n


# ---------------------------------------------------------------- دکمه‌ها
def add_button(
    token: str,
    title: str,
    kind: str,
    body: str,
    file_id: str | None = None,
    file_path: str | None = None,
) -> int:
    row = fetchone("SELECT COALESCE(MAX(position), 0) AS p FROM buttons WHERE token=?", (token,))
    pos = (row["p"] if row else 0) + 1
    cur = _q(
        "INSERT INTO buttons (token, title, kind, body, file_id, file_path, position)"
        " VALUES (?,?,?,?,?,?,?)",
        (token, title, kind, body, file_id, file_path, pos),
    )
    return int(cur.lastrowid)


# ------------------------------------------------- کش file_id هر ربات
def get_cached_file(token: str, key: str) -> str | None:
    row = fetchone("SELECT file_id FROM file_cache WHERE token=? AND key=?", (token, key))
    return row["file_id"] if row else None


def set_cached_file(token: str, key: str, file_id: str) -> None:
    _q(
        "INSERT INTO file_cache (token, key, file_id) VALUES (?,?,?)"
        " ON CONFLICT(token, key) DO UPDATE SET file_id = excluded.file_id",
        (token, key, file_id),
    )


def clear_cached_file(token: str, key: str) -> None:
    _q("DELETE FROM file_cache WHERE token=? AND key=?", (token, key))


def buttons(token: str) -> list[sqlite3.Row]:
    return fetchall("SELECT * FROM buttons WHERE token=? ORDER BY position", (token,))


def button_by_title(token: str, title: str) -> sqlite3.Row | None:
    return fetchone("SELECT * FROM buttons WHERE token=? AND title=?", (token, title))


def button_by_id(token: str, button_id: int) -> sqlite3.Row | None:
    """دکمه با آیدی عددی (برای پنل قفل توکن و دریافت محتوا)."""
    return fetchone("SELECT * FROM buttons WHERE token=? AND id=?",
                    (token, int(button_id)))


def set_button_ref(token: str, button_id: int, ref_req: int | None = None,
                   ref_count: int | None = None) -> None:
    """تنظیم قفل زیرمجموعه‌گیری یک دکمه به‌صورت جداگانه.

    ref_req  : ۱ = باز کردن دکمه نیاز به دعوت دارد، ۰ = بدون قفل
    ref_count: تعداد دعوت لازم فقط برای این دکمه (۰ = استفاده از تعداد کلی)
    """
    cur = fetchone("SELECT ref_req, ref_count FROM buttons WHERE token=? AND id=?",
                   (token, int(button_id)))
    if not cur:
        return
    req = cur["ref_req"] if ref_req is None else int(ref_req)
    cnt = cur["ref_count"] if ref_count is None else max(0, int(ref_count))
    _q("UPDATE buttons SET ref_req=?, ref_count=? WHERE token=? AND id=?",
       (int(bool(req)), cnt, token, int(button_id)))


def delete_button(token: str, button_id: int) -> None:
    for item in button_items(token, button_id):
        clear_cached_file(token, f"item:{item['id']}")
    _q("DELETE FROM button_items WHERE token=? AND button_id=?", (token, button_id))
    _q("DELETE FROM buttons WHERE token=? AND id=?", (token, button_id))
    clear_cached_file(token, f"btn:{button_id}")
    delete_button_stats(token, button_id)   # fix: آمار و رأی‌های دکمه هم پاک شود


# --------------------------------------- آیتم‌های محتوای یک دکمه
def add_button_item(token: str, button_id: int, kind: str, file_path: str) -> int:
    row = fetchone(
        "SELECT COALESCE(MAX(position), 0) AS p FROM button_items"
        " WHERE token=? AND button_id=?",
        (token, button_id),
    )
    pos = (row["p"] if row else 0) + 1
    cur = _q(
        "INSERT INTO button_items (token, button_id, kind, file_path, position)"
        " VALUES (?,?,?,?,?)",
        (token, button_id, kind, file_path, pos),
    )
    return int(cur.lastrowid)


def button_items(token: str, button_id: int) -> list[sqlite3.Row]:
    return fetchall(
        "SELECT * FROM button_items WHERE token=? AND button_id=? ORDER BY position",
        (token, button_id),
    )


def set_caption_target(token: str, button_id: int, target: int) -> None:
    _q("UPDATE buttons SET caption_target=? WHERE token=? AND id=?",
       (target, token, button_id))


# ---------------------------------------------------------- کاربران ربات
def track_user(token: str, user_id: int, first_name: str, username: str) -> bool:
    """ثبت کاربر؛ True یعنی کاربر جدید بود."""
    exists = fetchone(
        "SELECT 1 FROM bot_users WHERE token=? AND user_id=?", (token, user_id)
    )
    _q(
        "INSERT INTO bot_users (token, user_id, first_name, username, joined_at)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(token, user_id) DO UPDATE SET first_name=excluded.first_name,"
        " username=excluded.username",
        (token, user_id, first_name, username, int(time.time())),
    )
    return exists is None


def bot_user_ids(token: str) -> list[int]:
    return [r["user_id"] for r in fetchall(
        "SELECT user_id FROM bot_users WHERE token=? AND blocked=0", (token,)
    )]


def bot_user_count(token: str) -> int:
    row = fetchone("SELECT COUNT(*) AS c FROM bot_users WHERE token=?", (token,))
    return int(row["c"]) if row else 0


def get_bot_user(token: str, user_id: int) -> sqlite3.Row | None:
    return fetchone(
        "SELECT * FROM bot_users WHERE token=? AND user_id=?", (token, user_id)
    )


def is_blocked(token: str, user_id: int) -> bool:
    row = get_bot_user(token, user_id)
    return bool(row and row["blocked"])


def block_user(token: str, user_id: int, by: int) -> bool:
    """کاربر را مسدود می‌کند. False یعنی کاربر پیدا نشد."""
    if not get_bot_user(token, user_id):
        return False
    _q(
        "UPDATE bot_users SET blocked=1, blocked_at=?, blocked_by=?"
        " WHERE token=? AND user_id=?",
        (int(time.time()), by, token, user_id),
    )
    return True


def unblock_user(token: str, user_id: int) -> bool:
    if not get_bot_user(token, user_id):
        return False
    _q(
        "UPDATE bot_users SET blocked=0, blocked_at=NULL, blocked_by=NULL"
        " WHERE token=? AND user_id=?",
        (token, user_id),
    )
    return True


def blocked_users(token: str) -> list[sqlite3.Row]:
    return fetchall(
        "SELECT * FROM bot_users WHERE token=? AND blocked=1"
        " ORDER BY blocked_at DESC",
        (token,),
    )


def blocked_count(token: str) -> int:
    row = fetchone(
        "SELECT COUNT(*) c FROM bot_users WHERE token=? AND blocked=1", (token,)
    )
    return int(row["c"]) if row else 0


def search_users(token: str, query: str, limit: int = 20) -> list[sqlite3.Row]:
    """جستجوی کاربر با آیدی عددی، یوزرنیم یا نام."""
    q = query.strip().lstrip("@")
    if not q:
        return []
    if q.isdigit():
        rows = fetchall(
            "SELECT * FROM bot_users WHERE token=? AND user_id=?", (token, int(q))
        )
        if rows:
            return rows
    # fix: کاراکترهای % و _ مثل وایلدکارد SQL تفسیر می‌شدند؛ escape شدند
    like = ("%" + q.lower()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_") + "%")
    return fetchall(
        "SELECT * FROM bot_users WHERE token=?"
        " AND (LOWER(COALESCE(username,'')) LIKE ? ESCAPE '\\'"
        "      OR LOWER(COALESCE(first_name,'')) LIKE ? ESCAPE '\\'"
        "      OR CAST(user_id AS TEXT) LIKE ? ESCAPE '\\')"
        " ORDER BY joined_at DESC LIMIT ?",
        (token, like, like, like, limit),
    )


# ------------------------- وظیفه اجباری (تأیید عضویت + پنجره‌ی ۲ دقیقه)
def now_ms() -> int:
    """زمان جاری با دقت میلی‌ثانیه."""
    return int(time.time() * 1000)


TASK_VERIFY_KEY = "task_verified_at"   # کلید user_state برای زمان آخرین تأیید


def task_verified_at(token: str, user_id: int) -> int:
    """زمان آخرین تأیید وظیفه‌ی کاربر با دقت میلی‌ثانیه (۰ = هرگز)."""
    raw = user_get_state(token, user_id, TASK_VERIFY_KEY)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def set_task_verified(token: str, user_id: int, ts_ms: int | None = None) -> None:
    """ثبت تأیید وظیفه برای کاربر + یک واحد به شمارنده‌ی «تعداد تأیید»."""
    ts_ms = now_ms() if ts_ms is None else int(ts_ms)
    user_set_state(token, user_id, TASK_VERIFY_KEY, str(ts_ms))
    _q(
        "INSERT INTO settings (token, key, value) VALUES (?, 'task_completions', '1')"
        " ON CONFLICT(token, key) DO UPDATE"
        " SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)",
        (token,),
    )


def task_completions(token: str) -> int:
    """مجموع دفعات تأیید وظیفه (آمار پنل)."""
    try:
        return int(get_setting(token, "task_completions", "0") or 0)
    except ValueError:
        return 0


def task_verified_users_count(token: str) -> int:
    """تعداد کاربرانی که حداقل یک بار وظیفه را تأیید کرده‌اند."""
    row = fetchone(
        "SELECT COUNT(DISTINCT user_id) c FROM user_state"
        " WHERE token=? AND key=?",
        (token, TASK_VERIFY_KEY),
    )
    return int(row["c"]) if row else 0


def reset_tasks(token: str) -> None:
    """پاک کردن وضعیت تأیید وظیفه‌ی همه‌ی کاربران (و رکوردهای نسخه‌ی قدیمی)."""
    _q("DELETE FROM task_state WHERE token=?", (token,))
    _q("DELETE FROM user_state WHERE token=? AND key=?", (token, TASK_VERIFY_KEY))
    set_setting(token, "task_completions", "0")


# ---------------------------------------------------- آمار کاربران
def join_buckets(token: str) -> dict[str, int]:
    """تعداد کاربران جدید در بازه‌های زمانی (ساعت، ۵ ساعت، روز، هفته، ماه)."""
    now = int(time.time())
    spans = {"hour": 3600, "five_hours": 5 * 3600, "day": 86400,
             "week": 7 * 86400, "month": 30 * 86400}
    out: dict[str, int] = {}
    for name, sec in spans.items():
        row = fetchone(
            "SELECT COUNT(*) c FROM bot_users WHERE token=? AND joined_at>=?",
            (token, now - sec),
        )
        out[name] = int(row["c"]) if row else 0
    return out


def active_counts(token: str) -> tuple[int, int, int]:
    """(کل، فعال، غیرفعال) — غیرفعال = مسدودشده (معمولاً بعد از بلاک‌کردن ربات)."""
    row = fetchone(
        "SELECT COUNT(*) total,"
        " SUM(CASE WHEN blocked=0 THEN 1 ELSE 0 END) act,"
        " SUM(CASE WHEN blocked=1 THEN 1 ELSE 0 END) inact"
        " FROM bot_users WHERE token=?",
        (token,),
    )
    if not row or row["total"] is None:
        return 0, 0, 0
    return int(row["total"]), int(row["act"] or 0), int(row["inact"] or 0)


# -------------------------------------------------- آمار دموگرافیک
def set_user_meta(token: str, user_id: int,
                  age: int | None = None, gender: str | None = None) -> None:
    """ثبت سن و/یا جنسیت اعلام‌شده کاربر."""
    sets, params = [], [token, user_id]
    if age is not None:
        sets.append("age=?")
        params.extend([int(age), token, user_id])
    if gender is not None:
        sets.append("gender=?")
        params.extend([str(gender), token, user_id])
    if not sets:
        return
    # ترتیب پارامترهای SET قبل از WHERE است؛ کوئری جدا ساخته می‌شود
    flat: list = []
    if age is not None:
        flat.append(int(age))
    if gender is not None:
        flat.append(str(gender))
    _q(
        f"UPDATE bot_users SET {', '.join(sets)} WHERE token=? AND user_id=?",
        (*flat, token, user_id),
    )


def demo_stats(token: str) -> dict:
    """آمار دموگرافیک: میانگین سنی و توزیع جنسیتی.

    خروجی: {"avg_age": float|None, "male": int, "female": int, "asked": int}
    asked = تعداد کاربرانی که دست‌کم به یکی از دو سؤال پاسخ داده‌اند.
    """
    a = fetchone(
        "SELECT AVG(age) a, COUNT(age) n FROM bot_users"
        " WHERE token=? AND age IS NOT NULL",
        (token,),
    )
    g = fetchone(
        "SELECT"
        " SUM(CASE WHEN gender='m' THEN 1 ELSE 0 END) m,"
        " SUM(CASE WHEN gender='f' THEN 1 ELSE 0 END) f,"
        " COUNT(*) n"
        " FROM bot_users"
        " WHERE token=? AND (gender IN ('m','f') OR age IS NOT NULL)",
        (token,),
    )
    male = int(g["m"] or 0) if g else 0
    female = int(g["f"] or 0) if g else 0
    avg = float(a["a"]) if a and a["a"] is not None else None
    asked = int(g["n"]) if g and g["n"] else 0
    return {"avg_age": avg, "male": male, "female": female, "asked": asked}


# ------------------------------------------------------ آمار فایل‌ها
def bump_views(token: str, button_id: int) -> None:
    """یک بازدید برای دکمه ثبت می‌کند (هر بار ارسال محتوا)."""
    _q(
        "INSERT INTO file_stats (token, button_id, views) VALUES (?,?,1)"
        " ON CONFLICT(token, button_id) DO UPDATE SET views = views + 1",
        (token, int(button_id)),
    )


def views_of(token: str, button_id: int) -> int:
    row = fetchone(
        "SELECT views FROM file_stats WHERE token=? AND button_id=?",
        (token, int(button_id)),
    )
    return int(row["views"]) if row else 0


def views_total(token: str) -> int:
    row = fetchone("SELECT COALESCE(SUM(views),0) v FROM file_stats WHERE token=?",
                   (token,))
    return int(row["v"]) if row else 0


def vote_of(token: str, button_id: int, user_id: int) -> int | None:
    """رأی فعلی کاربر روی یک دکمه (۱ لایک، -۱ دیسلایک، None بدون رأی)."""
    row = fetchone(
        "SELECT value FROM file_votes"
        " WHERE token=? AND button_id=? AND user_id=?",
        (token, int(button_id), int(user_id)),
    )
    return int(row["value"]) if row else None


def set_vote(token: str, button_id: int, user_id: int, value: int) -> None:
    _q(
        "INSERT INTO file_votes (token, button_id, user_id, value, updated_at)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(token, button_id, user_id)"
        " DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (token, int(button_id), int(user_id), int(value), int(time.time())),
    )


def del_vote(token: str, button_id: int, user_id: int) -> None:
    _q(
        "DELETE FROM file_votes WHERE token=? AND button_id=? AND user_id=?",
        (token, int(button_id), int(user_id)),
    )


def vote_counts(token: str, button_id: int) -> tuple[int, int]:
    """(لایک، دیسلایک) یک دکمه."""
    row = fetchone(
        "SELECT SUM(CASE WHEN value=1 THEN 1 ELSE 0 END) l,"
        " SUM(CASE WHEN value=-1 THEN 1 ELSE 0 END) d"
        " FROM file_votes WHERE token=? AND button_id=?",
        (token, int(button_id)),
    )
    if not row:
        return 0, 0
    return int(row["l"] or 0), int(row["d"] or 0)


def votes_total(token: str) -> tuple[int, int]:
    """(مجموع لایک‌ها، مجموع دیسلایک‌ها) کل ربات."""
    row = fetchone(
        "SELECT SUM(CASE WHEN value=1 THEN 1 ELSE 0 END) l,"
        " SUM(CASE WHEN value=-1 THEN 1 ELSE 0 END) d"
        " FROM file_votes WHERE token=?",
        (token,),
    )
    if not row:
        return 0, 0
    return int(row["l"] or 0), int(row["d"] or 0)


def delete_button_stats(token: str, button_id: int) -> None:
    """آمار و رأی‌های یک دکمه هنگام حذف دکمه پاک شوند."""
    _q("DELETE FROM file_stats WHERE token=? AND button_id=?", (token, int(button_id)))
    _q("DELETE FROM file_votes WHERE token=? AND button_id=?", (token, int(button_id)))


def delete_user_data(token: str, user_id: int) -> None:
    """داده‌های per-user هنگام حذف ربات پاک شوند."""
    _q("DELETE FROM user_state WHERE token=? AND user_id=?", (token, int(user_id)))


# ------------------------------------------------------- وضعیت کاربر
def user_get_state(token: str, user_id: int, key: str,
                   default: str | None = None) -> str | None:
    row = fetchone(
        "SELECT value FROM user_state WHERE token=? AND user_id=? AND key=?",
        (token, int(user_id), key),
    )
    return row["value"] if row and row["value"] is not None else default


def user_set_state(token: str, user_id: int, key: str, value: str) -> None:
    _q(
        "INSERT INTO user_state (token, user_id, key, value, updated_at)"
        " VALUES (?,?,?,?,?)"
        " ON CONFLICT(token, user_id, key)"
        " DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (token, int(user_id), key, value, int(time.time())),
    )


def user_del_state(token: str, user_id: int, key: str) -> None:
    _q(
        "DELETE FROM user_state WHERE token=? AND user_id=? AND key=?",
        (token, int(user_id), key),
    )


# ------------------------------------------------ مرتب‌سازی فایل‌ها
def buttons_ranked(token: str, mode: str, limit: int = 10) -> list[sqlite3.Row]:
    """فایل‌های مرتب‌شده برای آمار: newest/oldest/views/likes/dislikes."""
    order = {
        "newest": "b.id DESC",
        "oldest": "b.id ASC",
        "views": "COALESCE(fs.views,0) DESC, b.id ASC",
        "likes": "likes DESC, b.id ASC",
        "dislikes": "dislikes DESC, b.id ASC",
    }.get(mode, "b.id ASC")
    sql = (
        "SELECT b.*, COALESCE(fs.views,0) AS views,"
        " COALESCE(v.likes,0) AS likes, COALESCE(v.dislikes,0) AS dislikes"
        " FROM buttons b"
        " LEFT JOIN file_stats fs ON fs.token=b.token AND fs.button_id=b.id"
        " LEFT JOIN (SELECT button_id,"
        "   SUM(CASE WHEN value=1 THEN 1 ELSE 0 END) likes,"
        "   SUM(CASE WHEN value=-1 THEN 1 ELSE 0 END) dislikes"
        "   FROM file_votes WHERE token=? GROUP BY button_id) v"
        "   ON v.button_id=b.id"
        " WHERE b.token=?"
        f" ORDER BY {order} LIMIT ?"
    )
    return fetchall(sql, (token, token, int(limit)))


def mark_blocked(token: str, user_id: int) -> None:
    _q("UPDATE bot_users SET blocked=1 WHERE token=? AND user_id=?", (token, user_id))


# ---------------------------------------------------------------- تیکت‌ها
def add_ticket(token: str, user_id: int, owner_msg_id: int) -> None:
    _q(
        "INSERT INTO tickets (token, user_id, owner_msg_id, created_at) VALUES (?,?,?,?)",
        (token, user_id, owner_msg_id, int(time.time())),
    )


def ticket_by_msg(token: str, owner_msg_id: int) -> sqlite3.Row | None:
    return fetchone(
        "SELECT * FROM tickets WHERE token=? AND owner_msg_id=?", (token, owner_msg_id)
    )


# ------------------------------------------- تیکت‌های پشتیبانی ربات مادر
def add_dm_ticket(scope: str, chat_id: int, msg_id: int, user_id: int) -> None:
    _q(
        "INSERT OR REPLACE INTO dm_tickets (scope, chat_id, msg_id, user_id, created_at)"
        " VALUES (?,?,?,?,?)",
        (scope, chat_id, msg_id, user_id, int(time.time())),
    )


def get_dm_ticket(scope: str, chat_id: int, msg_id: int) -> sqlite3.Row | None:
    return fetchone(
        "SELECT * FROM dm_tickets WHERE scope=? AND chat_id=? AND msg_id=?",
        (scope, chat_id, msg_id),
    )


# ---------------------------------------------------- زیرمجموعه‌گیری
def add_referral(token: str, inviter_id: int, invited_id: int) -> None:
    """دعوت را ثبت می‌کند؛ هر کاربرِ دعوت‌شده فقط یک بار ثبت می‌شود."""
    _q(
        "INSERT OR IGNORE INTO referrals (token, inviter_id, invited_id, joined_at)"
        " VALUES (?,?,?,?)",
        (token, inviter_id, invited_id, int(time.time())),
    )


def referrer_of(token: str, invited_id: int) -> int | None:
    """دعوت‌کنندهٔ یک کاربر (اگر با لینک آمده باشد)."""
    row = fetchone(
        "SELECT inviter_id FROM referrals WHERE token=? AND invited_id=?",
        (token, invited_id),
    )
    return int(row["inviter_id"]) if row else None


def referral_count(token: str, inviter_id: int) -> int:
    """تعداد دعوت‌های موفق یک کاربر."""
    row = fetchone(
        "SELECT COUNT(*) c FROM referrals WHERE token=? AND inviter_id=?",
        (token, inviter_id),
    )
    return int(row["c"]) if row else 0


def referral_total(token: str) -> int:
    """مجموع دعوت‌های ثبت‌شدهٔ ربات (برای آمار پنل)."""
    row = fetchone("SELECT COUNT(*) c FROM referrals WHERE token=?", (token,))
    return int(row["c"]) if row else 0


# ------------------------- استخر توکن (هر دعوت = ۱ توکن مصرف‌نشده)
def unused_tokens(token: str, inviter_id: int) -> int:
    """تعداد توکن‌های مصرف‌نشده‌ی یک کاربر (قابل خرج برای باز کردن دکمه)."""
    row = fetchone(
        "SELECT COUNT(*) c FROM referrals"
        " WHERE token=? AND inviter_id=? AND used=0",
        (token, int(inviter_id)),
    )
    return int(row["c"]) if row else 0


def burn_tokens(token: str, inviter_id: int, n: int) -> int:
    """سوزاندن n توکنِ مصرف‌نشده (قدیمی‌ترین اول). تعداد واقعیِ سوزانده‌شده برمی‌گردد."""
    n = max(0, int(n))
    if n == 0:
        return 0
    with _lock:
        rows = fetchall(
            "SELECT invited_id FROM referrals"
            " WHERE token=? AND inviter_id=? AND used=0"
            " ORDER BY joined_at ASC, invited_id ASC LIMIT ?",
            (token, int(inviter_id), n),
        )
        if not rows:
            return 0
        marks = [(int(time.time()), token, int(inviter_id), int(r["invited_id"]))
                 for r in rows]
        _conn.executemany(
            "UPDATE referrals SET used=1, used_at=?"
            " WHERE token=? AND inviter_id=? AND invited_id=?",
            marks,
        )
        _conn.commit()
        return len(marks)


def token_stats(token: str, inviter_id: int) -> tuple[int, int, int]:
    """(مجموع، مصرف‌شده، مصرف‌نشده) توکن‌های یک کاربر."""
    row = fetchone(
        "SELECT COUNT(*) t, SUM(CASE WHEN used=1 THEN 1 ELSE 0 END) u"
        " FROM referrals WHERE token=? AND inviter_id=?",
        (token, int(inviter_id)),
    )
    if not row or row["t"] is None:
        return 0, 0, 0
    total, used = int(row["t"]), int(row["u"] or 0)
    return total, used, total - used


def token_totals(token: str) -> tuple[int, int, int]:
    """(مجموع، مصرف‌شده، مصرف‌نشده) توکن‌های کل ربات (برای پنل مالک)."""
    row = fetchone(
        "SELECT COUNT(*) t, SUM(CASE WHEN used=1 THEN 1 ELSE 0 END) u"
        " FROM referrals WHERE token=?",
        (token,),
    )
    if not row or row["t"] is None:
        return 0, 0, 0
    total, used = int(row["t"]), int(row["u"] or 0)
    return total, used, total - used


# ---------------------------------------------------------------- آمار کلی
def stats() -> dict[str, int]:
    b = fetchone("SELECT COUNT(*) c FROM bots")
    a = fetchone("SELECT COUNT(*) c FROM bots WHERE active=1")
    o = fetchone("SELECT COUNT(DISTINCT owner_id) c FROM bots")
    u = fetchone("SELECT COUNT(*) c FROM bot_users")
    return {
        "bots": b["c"] if b else 0,
        "active": a["c"] if a else 0,
        "owners": o["c"] if o else 0,
        "users": u["c"] if u else 0,
    }
