"""تست جامع پروژه — همه‌ی جریان‌های اصلی بدون اتصال واقعی به تلگرام.

اجرا:  python tests/test_all.py
"""
from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.harness import (  # noqa: E402
    ADMIN,
    CHILD_TOKEN,
    FAIL,
    FakeCallbackQuery,
    FakeClient,
    FakeMessage,
    FakeUser,
    OWNER,
    PASS,
    USER,
    _TMP,
    check,
    compat,
    config,
    db,
    dispatch,
    manager,
    media,
    reset_db,
    runtime,
    section,
)
from tests import test_features  # noqa: E402
from tests import test_new_features  # noqa: E402
from tests import test_stats_features  # noqa: E402




# ══════════════════════════════════════════════ ۱) نرمال‌سازی کانال
def test_normalize():
    section("۱) نرمال‌سازی ورودی کانال")
    cases = {
        "@mychannel": "@mychannel",
        "mychannel": "@mychannel",
        "t.me/mychannel": "@mychannel",
        "https://t.me/mychannel": "@mychannel",
        "https://t.me/mychannel/": "@mychannel",
        "  @MyChannel  ": "@MyChannel",
        "-1001234567890": "-1001234567890",
        "https://t.me/+AbCdEfGh": "",
        "t.me/joinchat/XYZ": "",
        "ab": "",
        "": "",
    }
    for raw, want in cases.items():
        got = runtime.normalize_channel(raw)
        check(f"{raw!r} → {got!r}", got == want, f"انتظار {want!r}")


# ══════════════════════════════════════════ ۲) چند کانال در دیتابیس
def test_channels_db():
    section("۲) مدیریت چند کانال در دیتابیس")
    reset_db()
    check("در ابتدا خالی است", db.get_channels(CHILD_TOKEN) == [])
    check("افزودن اول", db.add_channel(CHILD_TOKEN, "@ch1") is True)
    check("افزودن دوم", db.add_channel(CHILD_TOKEN, "@ch2") is True)
    check("تکراری رد می‌شود", db.add_channel(CHILD_TOKEN, "@CH1") is False)
    check("لیست درست است", db.get_channels(CHILD_TOKEN) == ["@ch1", "@ch2"])

    removed = db.remove_channel(CHILD_TOKEN, 0)
    check("حذف تکی کار می‌کند", removed == "@ch1" and db.get_channels(CHILD_TOKEN) == ["@ch2"])
    check("ایندکس نامعتبر امن است", db.remove_channel(CHILD_TOKEN, 99) is None)

    db.add_channel(CHILD_TOKEN, "@ch3")
    n = db.clear_channels(CHILD_TOKEN)
    check("حذف همه", n == 2 and db.get_channels(CHILD_TOKEN) == [])

    # مهاجرت از تنظیم تک‌کاناله‌ی قدیمی
    db.set_setting(CHILD_TOKEN, "force_channels", "[]")
    db.set_setting(CHILD_TOKEN, "force_channel", "@legacy")
    check("مهاجرت از نسخه قدیمی", db.get_channels(CHILD_TOKEN) == ["@legacy"])
    check("تنظیم قدیمی پاک شد", db.get_setting(CHILD_TOKEN, "force_channel") == "")
    db.clear_channels(CHILD_TOKEN)


# ═══════════════════════════════════ ۳) اعمال عضویت اجباری (باگ اصلی)
def test_force_join():
    section("۳) عضویت اجباری در ربات فرزند")
    reset_db()
    db.add_channel(CHILD_TOKEN, "@ch1")
    db.add_channel(CHILD_TOKEN, "@ch2")
    db.add_button(CHILD_TOKEN, "درباره ما", "text", "ما تیم تست هستیم")

    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_child")
    user = FakeUser(USER, "علی", "ali")

    # --- کاربر عضو هیچ کانالی نیست ---
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": set(), "@ch2": set()})
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "/start")))
    texts = " ".join(cl.sent_texts())
    check("/start بدون عضویت → پیام عضویت", "عضو شوید" in texts)
    check("/start بدون عضویت → پیام خوش‌آمد نمی‌آید", "خوش آمدید" not in texts)
    kb = cl.last("send_message")["reply_markup"]
    n_btn = sum(len(r) for r in kb.inline_keyboard)
    check("دکمه برای هر کانال + دکمه بررسی", n_btn == 3, f"تعداد={n_btn}")

    # --- زدن دکمه‌ی منو بدون عضویت (باگ گزارش‌شده) ---
    cl.clear()
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "درباره ما")))
    texts = " ".join(cl.sent_texts())
    check("کلیک روی دکمه بدون عضویت → مسدود", "عضو شوید" in texts)
    check("محتوای دکمه لو نمی‌رود", "تیم تست" not in texts)

    # --- عضو یک کانال، نه هر دو ---
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": {USER}, "@ch2": set()})
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "درباره ما")))
    check("عضویت ناقص هم مسدود می‌شود", "عضو شوید" in " ".join(cl.sent_texts()))
    kb = cl.last("send_message")["reply_markup"]
    check("فقط کانال ناقص نمایش داده می‌شود",
          sum(len(r) for r in kb.inline_keyboard) == 2)

    # --- عضو هر دو کانال ---
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": {USER}, "@ch2": {USER}})
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "درباره ما")))
    check("با عضویت کامل، محتوا ارسال می‌شود",
          "تیم تست" in " ".join(cl.sent_texts()))

    # --- مالک ربات: پیش‌فرض معاف نیست (باگ گزارش‌شده) ---
    owner = FakeUser(OWNER, "مالک")
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": set(), "@ch2": set()})
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, owner, "درباره ما")))
    check("مالک هم به‌صورت پیش‌فرض باید عضو شود",
          "عضو شوید" in " ".join(cl.sent_texts(OWNER)))

    # --- با روشن کردن معافیت ---
    db.set_setting(CHILD_TOKEN, "owner_bypass", "1")
    cl.clear()
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, owner, "درباره ما")))
    check("با فعال کردن معافیت، مالک رد می‌شود",
          "تیم تست" in " ".join(cl.sent_texts()))
    db.set_setting(CHILD_TOKEN, "owner_bypass", "0")

    # --- ربات ادمین کانال نیست (fail-closed) ---
    from pyrogram.errors import ChatAdminRequired
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": {USER}},
                    raise_for={"@ch2": ChatAdminRequired()})
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "درباره ما")))
    check("خطای دسترسی → پیام عضویت (نه پیام گنگ «در دسترس نیست»)",
          "عضو شوید" in " ".join(cl.sent_texts(USER))
          and "در دسترس نیست" not in " ".join(cl.sent_texts(USER)))
    check("کانال خراب هم در لیست عضویت نمایش داده می‌شود",
          "@ch2" in " ".join(cl.sent_texts(USER)))
    check("به مالک هشدار پیکربندی می‌رود",
          any("کار نمی‌کند" in t for t in cl.sent_texts(OWNER)))

    # --- دکمه «عضو شدم» ---
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": {USER}, "@ch2": {USER}})
    runtime._member_cache.clear()
    msg = FakeMessage(cl, user, "پیام عضویت")
    cq = FakeCallbackQuery(cl, user, "checkjoin", msg)
    compat.run(dispatch(app, cl, cq, kind="callback"))
    check("«عضو شدم» با عضویت کامل → تأیید",
          any(e["action"] == "answer" and "تأیید" in e["text"] for e in cl.log))
    check("پس از تأیید، خوش‌آمد ارسال می‌شود",
          any("خوش آمدید" in t for t in cl.sent_texts()))

    cl = FakeClient(bot_id=222222222, memberships={"@ch1": set(), "@ch2": set()})
    runtime._member_cache.clear()
    cq = FakeCallbackQuery(cl, user, "checkjoin", FakeMessage(cl, user, "x"))
    compat.run(dispatch(app, cl, cq, kind="callback"))
    check("«عضو شدم» بدون عضویت → هشدار",
          any(e["action"] == "answer" and "هنوز" in e["text"] for e in cl.log))

    # --- بدون کانال اجباری ---
    db.clear_channels(CHILD_TOKEN)
    runtime._member_cache.clear()
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "درباره ما")))
    check("بدون کانال اجباری، همه‌چیز عادی کار می‌کند",
          "تیم تست" in " ".join(cl.sent_texts()))


# ═══════════════════════════════════════════ ۴) دکمه‌های رسانه‌ای
def test_media_buttons():
    section("۴) دکمه‌های عکس/ویدیو/فایل")
    reset_db()
    vid = media.MEDIA_DIR / "demo.mp4"
    vid.write_bytes(b"\x00" * 1024)
    bid = db.add_button(CHILD_TOKEN, "ویدیو", "video", "<b>کپشن</b>",
                        file_path=str(vid))

    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_child2")
    user = FakeUser(USER)
    cl = FakeClient(bot_id=222222222)

    compat.run(dispatch(app, cl, FakeMessage(cl, user, "ویدیو")))
    check("بار اول از روی دیسک آپلود می‌شود",
          cl.last("send_video") is not None and str(vid) in cl.uploads)
    check("کپشن حفظ می‌شود", cl.last("send_video")["caption"] == "<b>کپشن</b>")

    cached = db.get_cached_file(CHILD_TOKEN, f"btn:{bid}")
    check("file_id مخصوص ربات فرزند کش می‌شود", cached is not None)

    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "ویدیو")))
    check("بار دوم از کش استفاده می‌شود (بدون آپلود مجدد)",
          cl.last("send_video")["source"] == cached)

    # فایل حذف‌شده نباید ربات را بترکاند
    db.clear_cached_file(CHILD_TOKEN, f"btn:{bid}")
    vid.unlink()
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "ویدیو")))
    check("نبودن فایل روی دیسک → پیام خطای مؤدبانه",
          any("در دسترس نیست" in t for t in cl.sent_texts()))


# ═════════════════════════════════════════════ ۵) پشتیبانی ربات فرزند
def test_child_support():
    section("۵) پشتیبانی ربات فرزند")
    reset_db()
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_child3")
    user = FakeUser(USER, "علی", "ali")
    cl = FakeClient(bot_id=222222222)

    compat.run(dispatch(app, cl, FakeMessage(cl, user, runtime.SUPPORT_BTN)))
    check("ورود به حالت پشتیبانی", (CHILD_TOKEN, USER) in runtime._support_mode)

    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "سلام مشکل دارم")))
    check("پیام برای مالک ارسال می‌شود",
          any("پیام جدید" in t for t in cl.sent_texts(OWNER)))
    check("متن کاربر کپی می‌شود",
          any(e["action"] == "copy" and e["chat_id"] == OWNER for e in cl.log))
    check("به کاربر تأیید داده می‌شود",
          any("ارسال شد" in t for t in cl.sent_texts(USER)))
    check("حالت پشتیبانی بسته می‌شود", (CHILD_TOKEN, USER) not in runtime._support_mode)

    # پاسخ مالک با ریپلای
    header_id = [e for e in cl.log
                 if e["action"] == "send_message" and e["chat_id"] == OWNER][0]
    ticket = db.ticket_by_msg(CHILD_TOKEN, db.fetchone(
        "SELECT owner_msg_id FROM tickets WHERE token=?", (CHILD_TOKEN,))["owner_msg_id"])
    check("تیکت در دیتابیس ثبت شد", ticket is not None and ticket["user_id"] == USER)

    cl.clear()
    owner = FakeUser(OWNER, "مالک")
    replied = FakeMessage(cl, owner, "هدر")
    replied.id = ticket["owner_msg_id"]
    reply = FakeMessage(cl, owner, "سلام، مشکل حل شد", reply_to=replied)
    compat.run(dispatch(app, cl, reply))
    check("پاسخ مالک به کاربر می‌رسد",
          any(e["action"] == "copy" and e["chat_id"] == USER for e in cl.log))

    # انصراف
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, runtime.SUPPORT_BTN)))
    compat.run(dispatch(app, cl, FakeMessage(cl, user, runtime.CANCEL_BTN)))
    check("انصراف حالت پشتیبانی را می‌بندد",
          (CHILD_TOKEN, USER) not in runtime._support_mode)


# ═══════════════════════════════════════════ ۶) پشتیبانی ربات مادر
def test_mother_support():
    section("۶) پشتیبانی ربات مادر")
    from mother import bot as mb

    mb.STATE.clear()
    user = FakeUser(USER, "علی", "ali")
    cl = FakeClient(bot_id=111111111, username="mother_bot")

    compat.run(dispatch(mb.app, cl, FakeMessage(cl, user, mb.BTN_SUPPORT)))
    check("ورود به حالت پشتیبانی مادر",
          mb.STATE.get(USER, {}).get("step") == "support_msg")

    cl.clear()
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, user, "چطور ربات بسازم؟")))
    for admin in config.ADMINS:
        check(f"پیام به ادمین {admin} می‌رسد",
              any("پیام پشتیبانی" in t for t in cl.sent_texts(admin)))
    check("متن کاربر برای ادمین کپی می‌شود",
          sum(1 for e in cl.log if e["action"] == "copy") == len(config.ADMINS))

    row = db.fetchone("SELECT * FROM dm_tickets WHERE scope='mother' AND chat_id=?",
                      (ADMIN,))
    check("تیکت ادمین ثبت شد", row is not None and row["user_id"] == USER)

    # پاسخ ادمین با ریپلای
    cl.clear()
    admin_user = FakeUser(ADMIN, "ادمین")
    header = FakeMessage(cl, admin_user, "هدر")
    header.id = row["msg_id"]
    compat.run(dispatch(mb.app, cl,
                        FakeMessage(cl, admin_user, "با /newbot شروع کن", reply_to=header)))
    check("پاسخ ادمین به کاربر می‌رسد",
          any(e["action"] == "copy" and e["chat_id"] == USER for e in cl.log))
    check("به ادمین تأیید داده می‌شود",
          any("ارسال شد" in t for t in cl.sent_texts(ADMIN)))

    # ریپلای بی‌ربط نباید چیزی بفرستد
    cl.clear()
    other = FakeMessage(cl, admin_user, "یه پیام دیگه")
    other.id = 999999
    compat.run(dispatch(mb.app, cl,
                        FakeMessage(cl, admin_user, "تست", reply_to=other)))
    check("ریپلای نامرتبط پیام اشتباه نمی‌فرستد",
          not any(e["action"] == "copy" for e in cl.log))


# ═════════════════════════════════════ ۷) پنل مادر و پارس callback
def test_mother_panel():
    section("۷) پنل ربات مادر و مدیریت کانال‌ها")
    from mother import bot as mb

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    cl = FakeClient(bot_id=111111111, username="mother_bot")

    check("find_token با tid درست کار می‌کند",
          mb.find_token(OWNER, tid) == CHILD_TOKEN)
    check("کاربر غریبه به ربات دیگران دسترسی ندارد",
          mb.find_token(12345, tid) is None)

    # افزودن دکمه و حذف آن (باگ «متعلق به شما نیست»)
    bid = db.add_button(CHILD_TOKEN, "تست", "text", "متن")
    cq = FakeCallbackQuery(cl, owner, f"delbtn:{tid}:{bid}", FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    answers = [e["text"] for e in cl.log if e["action"] == "answer"]
    check("حذف دکمه خطای مالکیت نمی‌دهد",
          not any("متعلق به شما نیست" in a for a in answers), str(answers))
    check("دکمه واقعاً حذف شد", db.button_by_title(CHILD_TOKEN, "تست") is None)

    # منوی کانال‌ها
    db.add_channel(CHILD_TOKEN, "@ch1")
    db.add_channel(CHILD_TOKEN, "@ch2")
    cl.clear()
    cq = FakeCallbackQuery(cl, owner, f"chans:{tid}", FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    edit = cl.last("edit")
    kb = edit["reply_markup"].inline_keyboard
    labels = [b.text for row in kb for b in row]
    check("هر کانال دکمه حذف مستقل دارد",
          "🗑 @ch1" in labels and "🗑 @ch2" in labels, str(labels))
    check("دکمه افزودن کانال هست", any("افزودن کانال" in l for l in labels))
    check("دکمه حذف همه هست", any("حذف همه" in l for l in labels))
    check("سوییچ معافیت مالک هست", any("معافیت خودم" in l for l in labels))

    # حذف کانال اول
    cl.clear()
    cq = FakeCallbackQuery(cl, owner, f"chdel:{tid}:0", FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("حذف کانال تکی کار می‌کند", db.get_channels(CHILD_TOKEN) == ["@ch2"])
    check("منو بعد از حذف به‌روز می‌شود",
          "@ch2" in cl.last("edit")["text"] and "@ch1" not in cl.last("edit")["text"])

    # حذف همه
    cl.clear()
    cq = FakeCallbackQuery(cl, owner, f"chclr:{tid}", FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("حذف همه کانال‌ها کار می‌کند", db.get_channels(CHILD_TOKEN) == [])

    # سوییچ معافیت
    cl.clear()
    cq = FakeCallbackQuery(cl, owner, f"chbyp:{tid}", FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("سوییچ معافیت مالک کار می‌کند",
          db.get_setting(CHILD_TOKEN, "owner_bypass") == "1")
    compat.run(dispatch(mb.app, cl,
                        FakeCallbackQuery(cl, owner, f"chbyp:{tid}",
                                          FakeMessage(cl, owner, "x")), kind="callback"))
    check("سوییچ دوباره خاموش می‌شود",
          db.get_setting(CHILD_TOKEN, "owner_bypass") == "0")

    # افزودن کانال با ورودی نامعتبر
    mb.STATE[OWNER] = {"step": "chan_add", "token": CHILD_TOKEN}
    cl.clear()
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "https://t.me/+SecretLink")))
    check("لینک خصوصی رد می‌شود",
          any("نامعتبر" in t for t in cl.sent_texts()) and db.get_channels(CHILD_TOKEN) == [])

    # افزودن معتبر وقتی ربات خاموش است
    mb.STATE[OWNER] = {"step": "chan_add", "token": CHILD_TOKEN}
    cl.clear()
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "@validchannel")))
    check("کانال معتبر اضافه می‌شود", db.get_channels(CHILD_TOKEN) == ["@validchannel"])
    db.clear_channels(CHILD_TOKEN)


# ═══════════════════════════════════════════════ ۸) پیام همگانی
def test_broadcast():
    section("۸) پیام همگانی")
    reset_db()
    for uid in (701, 702, 703):
        db.track_user(CHILD_TOKEN, uid, f"user{uid}", None)
    check("۳ کاربر ثبت شد", len(db.bot_user_ids(CHILD_TOKEN)) == 3)

    child_cl = FakeClient(bot_id=222222222)
    manager._clients[CHILD_TOKEN] = child_cl
    try:
        payload = {"kind": "text", "text": "سلام به همه", "path": None}
        ok, fail = compat.run(manager.broadcast(CHILD_TOKEN, payload))
        check("همه پیام‌ها ارسال شد", (ok, fail) == (3, 0), f"ok={ok} fail={fail}")
        check("ارسال با کلاینت ربات فرزند انجام شد",
              all(e["chat_id"] in (701, 702, 703)
                  for e in child_cl.log if e["action"] == "send_message"))

        # همگانی رسانه‌ای: فقط یک بار آپلود، بقیه از کش
        img = media.MEDIA_DIR / "bc.jpg"
        img.write_bytes(b"\xff" * 256)
        child_cl.clear()
        payload = {"kind": "photo", "text": "کپشن", "path": str(img)}
        ok, fail = compat.run(manager.broadcast(CHILD_TOKEN, payload))
        uploads_from_disk = [u for u in child_cl.uploads if u == str(img)]
        check("همگانی رسانه‌ای ارسال شد", (ok, fail) == (3, 0))
        check("فقط یک‌بار آپلود شد، بقیه از کش", len(uploads_from_disk) == 1,
              f"آپلودها={child_cl.uploads}")

        # ربات خاموش
        del manager._clients[CHILD_TOKEN]
        ok, fail = compat.run(manager.broadcast(CHILD_TOKEN, {"kind": "text", "text": "x"}))
        check("ربات خاموش → ارسال نمی‌شود و کرش نمی‌کند", (ok, fail) == (0, 0))
    finally:
        manager._clients.pop(CHILD_TOKEN, None)


# ══════════════════════════════════════════ ۹) اعتبارسنجی و امنیت
def test_validation():
    section("۹) اعتبارسنجی و امنیت")
    check("توکن معتبر پذیرفته می‌شود",
          manager.TOKEN_RE.match("123456789:AAE" + "x" * 30) is not None)
    for bad in ["سلام", "123", "abc:def", "123456789:short"]:
        check(f"توکن نامعتبر رد می‌شود ({bad[:12]})",
              manager.TOKEN_RE.match(bad) is None)

    reset_db()
    tid = CHILD_TOKEN.split(":")[0]
    from mother import bot as mb
    cl = FakeClient(bot_id=111111111)
    stranger = FakeUser(4242, "غریبه")
    cq = FakeCallbackQuery(cl, stranger, f"del:{tid}", FakeMessage(cl, stranger, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("کاربر غریبه نمی‌تواند ربات دیگری را حذف کند",
          any("متعلق به شما نیست" in e.get("text", "")
              for e in cl.log if e["action"] == "answer"))
    check("ربات هنوز در دیتابیس هست", db.get_bot(CHILD_TOKEN) is not None)


# ════════════════════════════════════════ ۱۰) سلامت event loop
def test_loop():
    section("۱۰) سلامت event loop (پایتون ۳.۱۴)")
    import asyncio

    from mother.bot import app as mother_app
    check("کلاینت مادر روی لوپ compat است", mother_app.loop is compat.LOOP)

    async def inner():
        return asyncio.get_running_loop()

    check("لوپ در حال اجرا همان لوپ است", compat.run(inner()) is compat.LOOP)


# ════════════════════ ۱۱) دکمه‌ی چندمحتوایی (متن + عکس + ویدیو + فایل)
def test_multi_content_button():
    section("۱۱) دکمه‌ی چندمحتوایی و ویزارد")
    from mother import bot as mb
    from mother import wizard

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")

    def cb(data):
        return FakeCallbackQuery(mcl, owner, data, FakeMessage(mcl, owner, "panel"))

    # شروع ویزارد
    compat.run(dispatch(mb.app, mcl, cb(f"addbtn:{tid}"), kind="callback"))
    check("ویزارد شروع می‌شود", mb.STATE.get(OWNER, {}).get("step") == "btn_title")
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "بسته آموزشی")))
    st = mb.STATE[OWNER]
    check("عنوان ثبت شد", st.get("title") == "بسته آموزشی")
    check("اولین سؤال درباره متن است", st.get("stage") == "text")

    # متن: بله → ارسال متن
    compat.run(dispatch(mb.app, mcl, cb("wz:y"), kind="callback"))
    check("حالت دریافت متن", mb.STATE[OWNER]["step"] == "wz_collect")
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "توضیحات بسته")))
    st = mb.STATE[OWNER]
    check("متن در سبد ذخیره شد", st["text"] == "توضیحات بسته")
    check("سؤال بعدی: عکس", st["stage"] == "photo")

    # عکس: بله → دو عکس
    compat.run(dispatch(mb.app, mcl, cb("wz:y"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, media_kind="photo")))
    check("عکس اول اضافه شد", len(mb.STATE[OWNER]["items"]) == 1)
    check("بعد از افزودن، دوباره همان نوع پرسیده می‌شود",
          mb.STATE[OWNER]["stage"] == "photo")
    compat.run(dispatch(mb.app, mcl, cb("wz:y"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, media_kind="photo")))
    check("عکس دوم اضافه شد", len(mb.STATE[OWNER]["items"]) == 2)

    # عکس دیگر: خیر → ویدیو: بله
    compat.run(dispatch(mb.app, mcl, cb("wz:n"), kind="callback"))
    check("مرحله بعد ویدیو است", mb.STATE[OWNER]["stage"] == "video")
    compat.run(dispatch(mb.app, mcl, cb("wz:y"), kind="callback"))

    # نوع اشتباه رد می‌شود
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, media_kind="photo")))
    check("نوع اشتباه پذیرفته نمی‌شود",
          any("دوباره بفرستید" in t for t in mcl.sent_texts())
          and len(mb.STATE[OWNER]["items"]) == 2)

    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, media_kind="video")))
    check("ویدیو اضافه شد", len(mb.STATE[OWNER]["items"]) == 3)
    compat.run(dispatch(mb.app, mcl, cb("wz:n"), kind="callback"))

    # فایل: بله
    check("مرحله بعد فایل است", mb.STATE[OWNER]["stage"] == "document")
    compat.run(dispatch(mb.app, mcl, cb("wz:y"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, media_kind="document")))
    check("فایل اضافه شد", len(mb.STATE[OWNER]["items"]) == 4)
    compat.run(dispatch(mb.app, mcl, cb("wz:n"), kind="callback"))

    # صوت: خیر → سؤال محل چسبیدن متن
    compat.run(dispatch(mb.app, mcl, cb("wz:n"), kind="callback"))
    st = mb.STATE[OWNER]
    check("سؤال محل چسبیدن متن پرسیده می‌شود", st["step"] == "wz_caption")
    panel = mcl.last("edit") or mcl.last("send_message")
    labels = [b.text for r in panel["reply_markup"].inline_keyboard for b in r]
    check("برای هر آیتم یک گزینه هست",
          sum(1 for l in labels if "عکس" in l or "ویدیو" in l or "فایل" in l) == 4,
          str(labels))
    check("گزینه ارسال جداگانه هست", any("جداگانه" in l for l in labels))

    # متن روی ویدیو (ایندکس ۲) بچسبد
    compat.run(dispatch(mb.app, mcl, cb("wz:cap:2"), kind="callback"))
    check("ویزارد بسته شد", OWNER not in mb.STATE)

    btn = db.button_by_title(CHILD_TOKEN, "بسته آموزشی")
    check("دکمه ذخیره شد", btn is not None)
    items = db.button_items(CHILD_TOKEN, btn["id"])
    check("۴ آیتم ذخیره شد", len(items) == 4, str([i["kind"] for i in items]))
    check("ترتیب آیتم‌ها حفظ شد",
          [i["kind"] for i in items] == ["photo", "photo", "video", "document"])
    check("هدف کپشن روی ویدیو تنظیم شد", btn["caption_target"] == items[2]["id"])

    # ── ارسال در ربات فرزند ──
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_multi")
    user = FakeUser(USER)
    ccl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, ccl, FakeMessage(ccl, user, "بسته آموزشی")))

    sends = [e for e in ccl.log if e["action"].startswith("send_")]
    kinds = [e["action"] for e in sends]
    check("هر ۴ رسانه ارسال شد",
          kinds == ["send_photo", "send_photo", "send_video", "send_document"],
          str(kinds))
    captions = [e.get("caption") for e in sends]
    check("متن دقیقاً یک بار ارسال شد",
          sum(1 for c in captions if c == "توضیحات بسته") == 1, str(captions))
    check("متن روی ویدیو نشسته", captions[2] == "توضیحات بسته")
    check("پیام متنی جداگانه فرستاده نشد",
          not any(e["action"] == "send_message" for e in ccl.log))

    # ── حالت «جداگانه» ──
    db.set_caption_target(CHILD_TOKEN, btn["id"], -1)
    ccl.clear()
    compat.run(dispatch(app, ccl, FakeMessage(ccl, user, "بسته آموزشی")))
    check("در حالت جداگانه، متن پیام مستقل می‌شود",
          any(e["action"] == "send_message" and e["text"] == "توضیحات بسته"
              for e in ccl.log))
    caps = [e.get("caption") for e in ccl.log if e["action"].startswith("send_") and
            e["action"] != "send_message"]
    check("در حالت جداگانه هیچ کپشنی ست نمی‌شود",
          all(c is None for c in caps), str(caps))

    # ── آیتم هدف حذف شود، متن نباید گم شود ──
    db.set_caption_target(CHILD_TOKEN, btn["id"], 999999)
    ccl.clear()
    compat.run(dispatch(app, ccl, FakeMessage(ccl, user, "بسته آموزشی")))
    check("با نبود آیتم هدف، متن باز هم یک بار می‌رود",
          sum(1 for e in ccl.log
              if e.get("text") == "توضیحات بسته" or e.get("caption") == "توضیحات بسته") == 1)

    # ── حذف دکمه، آیتم‌ها را هم پاک می‌کند ──
    db.delete_button(CHILD_TOKEN, btn["id"])
    check("حذف دکمه، آیتم‌هایش را هم حذف می‌کند",
          db.button_items(CHILD_TOKEN, btn["id"]) == [])

    # ── انصراف وسط ویزارد ──
    mb.STATE.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"addbtn:{tid}"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "موقت")))
    compat.run(dispatch(mb.app, mcl, cb("wz:x"), kind="callback"))
    check("انصراف ویزارد", OWNER not in mb.STATE
          and db.button_by_title(CHILD_TOKEN, "موقت") is None)

    # ── دکمه فقط رسانه‌ای (بدون متن) ──
    mb.STATE.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"addbtn:{tid}"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "فقط عکس")))
    compat.run(dispatch(mb.app, mcl, cb("wz:n"), kind="callback"))      # متن: خیر
    compat.run(dispatch(mb.app, mcl, cb("wz:y"), kind="callback"))      # عکس: بله
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, media_kind="photo")))
    for _ in range(4):                                                  # بقیه: خیر
        if OWNER in mb.STATE:
            compat.run(dispatch(mb.app, mcl, cb("wz:n"), kind="callback"))
    b2 = db.button_by_title(CHILD_TOKEN, "فقط عکس")
    check("دکبه بدون متن هم ساخته می‌شود",
          b2 is not None and len(db.button_items(CHILD_TOKEN, b2["id"])) == 1)
    check("بدون متن، سؤال کپشن پرسیده نمی‌شود", OWNER not in mb.STATE)

    # ── سازگاری با دکمه‌های قدیمی (تک‌محتوایی) ──
    legacy_file = media.MEDIA_DIR / "legacy.mp4"
    legacy_file.write_bytes(b"\x00" * 128)
    old_id = db.add_button(CHILD_TOKEN, "قدیمی", "video", "کپشن قدیمی",
                           file_path=str(legacy_file))
    ccl.clear()
    compat.run(dispatch(app, ccl, FakeMessage(ccl, user, "قدیمی")))
    check("دکمه‌های قدیمی هنوز کار می‌کنند",
          ccl.last("send_video") is not None
          and ccl.last("send_video")["caption"] == "کپشن قدیمی")


# ══════════════════════════ ۱۲) پیام عضویت سفارشی و لغو دسترسی
def test_join_message():
    section("۱۱) پیام عضویت سفارشی و لغو فوری دسترسی")
    reset_db()
    db.add_channel(CHILD_TOKEN, "@ch1")
    db.add_channel(CHILD_TOKEN, "@ch2")
    db.add_button(CHILD_TOKEN, "فایل", "text", "محتوای محرمانه")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_join")
    user = FakeUser(USER, "علی")

    # --- متن پیش‌فرض ---
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": set(), "@ch2": set()})
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    txt = " ".join(cl.sent_texts(USER))
    check("متن پیش‌فرض شامل نام کانال‌هاست", "@ch1" in txt and "@ch2" in txt)
    check("محتوا لو نمی‌رود", "محرمانه" not in txt)

    # --- متن سفارشی با متغیرها ---
    db.set_setting(CHILD_TOKEN, "join_text",
                   "{name} عزیز، برای دریافت فایل باید در {count} کانال زیر عضو شوی:\n{channels}")
    cl.clear()
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    txt = " ".join(cl.sent_texts(USER))
    check("متن سفارشی اعمال می‌شود", "برای دریافت فایل" in txt, txt[:80])
    check("{name} جای‌گذاری می‌شود", "علی عزیز" in txt)
    check("{count} جای‌گذاری می‌شود", "۲" in txt or "2 کانال" in txt)
    check("{channels} جای‌گذاری می‌شود", "@ch1" in txt and "@ch2" in txt)
    check("متغیر جای‌گذاری‌نشده نمی‌ماند", "{" not in txt.replace("{}", ""))

    kb = cl.last("send_message")["reply_markup"]
    urls = [b.url for row in kb.inline_keyboard for b in row if b.url]
    check("دکمه لینک برای هر کانال ساخته می‌شود",
          "https://t.me/ch1" in urls and "https://t.me/ch2" in urls, str(urls))

    # --- {links} ---
    db.set_setting(CHILD_TOKEN, "join_text", "عضو شو:\n{links}")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    check("{links} لینک HTML می‌سازد",
          'href="https://t.me/ch1"' in " ".join(cl.sent_texts(USER)))
    db.set_setting(CHILD_TOKEN, "join_text", "")

    # --- لغو فوری دسترسی پس از خروج از کانال ---
    memberships = {"@ch1": {USER}, "@ch2": {USER}}
    cl = FakeClient(bot_id=222222222, memberships=memberships)
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    check("عضو کانال → محتوا دریافت می‌کند",
          "محرمانه" in " ".join(cl.sent_texts(USER)))

    memberships["@ch2"].discard(USER)      # کاربر از کانال خارج می‌شود
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    txt = " ".join(cl.sent_texts(USER))
    check("خروج از کانال → دسترسی بلافاصله قطع می‌شود", "محرمانه" not in txt, txt[:60])
    check("پس از خروج، پیام عضویت نمایش داده می‌شود", "@ch2" in txt)

    memberships["@ch2"].add(USER)          # دوباره عضو می‌شود
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    check("عضویت مجدد → دسترسی برمی‌گردد",
          "محرمانه" in " ".join(cl.sent_texts(USER)))

    # --- کش اختیاری ---
    db.set_setting(CHILD_TOKEN, "check_ttl", "60")
    runtime._member_cache.clear()
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    memberships["@ch2"].discard(USER)
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    check("با روشن کردن کش، تا انقضا دسترسی می‌ماند (رفتار اختیاری)",
          "محرمانه" in " ".join(cl.sent_texts(USER)))
    db.set_setting(CHILD_TOKEN, "check_ttl", "0")
    runtime._member_cache.clear()
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    check("با خاموش کردن کش، فوراً مسدود می‌شود",
          "محرمانه" not in " ".join(cl.sent_texts(USER)))

    # --- ویرایش متن از ربات مادر ---
    from mother import bot as mb
    mb.STATE.clear()
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")
    tid = CHILD_TOKEN.split(":")[0]
    cq = FakeCallbackQuery(mcl, owner, f"chtxt:{tid}", FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    check("دکمه ویرایش متن، حالت ویرایش را باز می‌کند",
          mb.STATE.get(OWNER, {}).get("step") == "join_text")
    check("راهنمای متغیرها نمایش داده می‌شود",
          any("{channels}" in t for t in mcl.sent_texts()))

    mcl.clear()
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "لطفاً عضو شوید:\n{channels}")))
    check("متن جدید ذخیره می‌شود",
          db.get_setting(CHILD_TOKEN, "join_text") == "لطفاً عضو شوید:\n{channels}")
    check("پیش‌نمایش نمایش داده می‌شود",
          any("پیش‌نمایش" in t for t in mcl.sent_texts()))

    mcl.clear()
    mb.STATE[OWNER] = {"step": "join_text", "token": CHILD_TOKEN}
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "پیش‌فرض")))
    check("بازگشت به متن پیش‌فرض", db.get_setting(CHILD_TOKEN, "join_text") == "")

    # منو وضعیت را نشان می‌دهد
    mcl.clear()
    cq = FakeCallbackQuery(mcl, owner, f"chans:{tid}", FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    labels = [b.text for row in mcl.last("edit")["reply_markup"].inline_keyboard
              for b in row]
    check("دکمه ویرایش متن در منو هست", any("متن پیام عضویت" in l for l in labels))
    db.clear_channels(CHILD_TOKEN)


# ═══════════════════════════════════════ ۱۲) سناریوهای لبه‌ای
def test_edge_cases():
    section("۱۱) سناریوهای لبه‌ای")
    reset_db()
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_edge")
    user = FakeUser(USER, "علی")
    owner = FakeUser(OWNER, "مالک")

    # --- پاسخ مالک نباید پیام اضافی «از دکمه‌ها استفاده کنید» بگیرد ---
    db.add_ticket(CHILD_TOKEN, USER, 4321)
    cl = FakeClient(bot_id=222222222)
    hdr = FakeMessage(cl, owner, "هدر")
    hdr.id = 4321
    fired = compat.run(dispatch(app, cl, FakeMessage(cl, owner, "پاسخ", reply_to=hdr)))
    check("پاسخ مالک فقط هندلر تیکت را اجرا می‌کند", fired == ["on_owner_reply"], str(fired))
    check("پیام اضافی «از دکمه‌ها» فرستاده نمی‌شود",
          not any("دکمه‌های منو" in t for t in cl.sent_texts()))

    # --- مالک با کانال اجباری روشن، هنگام پاسخ به تیکت مسدود نشود ---
    db.add_channel(CHILD_TOKEN, "@ch1")
    runtime._member_cache.clear()
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": set()})
    hdr = FakeMessage(cl, owner, "هدر")
    hdr.id = 4321
    compat.run(dispatch(app, cl, FakeMessage(cl, owner, "پاسخ ۲", reply_to=hdr)))
    check("پاسخ مالک با کانال اجباری هم کار می‌کند",
          any(e["action"] == "copy" and e["chat_id"] == USER for e in cl.log))
    db.clear_channels(CHILD_TOKEN)

    # --- /start دو بار پردازش نشود ---
    runtime._member_cache.clear()
    cl = FakeClient(bot_id=222222222)
    fired = compat.run(dispatch(app, cl, FakeMessage(cl, user, "/start")))
    check("/start فقط on_start را اجرا می‌کند", fired == ["on_start"], str(fired))

    # --- جای‌گذاری {name} و {id} ---
    db.set_setting(CHILD_TOKEN, "welcome", "سلام {name} کد {id}")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "/start")))
    check("جای‌گذاری {name} و {id}",
          any(f"سلام علی کد {USER}" in t for t in cl.sent_texts()))

    # --- اطلاع «کاربر جدید» فقط یک بار ---
    reset_db()
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "/start")))
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "/start")))
    n = sum(1 for t in cl.sent_texts(OWNER) if "کاربر جدید" in t)
    check("اطلاع کاربر جدید فقط یک‌بار می‌رود", n == 1, f"تعداد={n}")

    # --- خاموش بودن پشتیبانی ---
    db.set_setting(CHILD_TOKEN, "support", "0")
    kb = runtime.main_keyboard(CHILD_TOKEN)
    labels = [b.text for r in (kb.keyboard if kb else []) for b in r]
    check("با خاموش بودن پشتیبانی، دکمه‌اش نیست", runtime.SUPPORT_BTN not in labels)
    db.set_setting(CHILD_TOKEN, "support", "1")

    # --- سقف تعداد ربات ---
    from mother import bot as mb
    mb.STATE.clear()
    cl = FakeClient(bot_id=111111111, username="mother_bot")
    heavy = FakeUser(8080, "پرمصرف")
    for i in range(config.MAX_BOTS_PER_USER):
        db.add_bot(f"90000000{i}:AA" + "z" * 33, 900 + i, f"b{i}", 8080)
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, heavy, mb.BTN_NEW)))
    check("سقف تعداد ربات رعایت می‌شود",
          any("سقف" in t for t in cl.sent_texts()))
    for i in range(config.MAX_BOTS_PER_USER):
        db.delete_bot(f"90000000{i}:AA" + "z" * 33)

    # --- انصراف در ربات مادر ---
    mb.STATE[8080] = {"step": "token"}
    cl.clear()
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, heavy, mb.BTN_CANCEL)))
    check("انصراف وضعیت را پاک می‌کند", 8080 not in mb.STATE)

    # --- کاراکترهای HTML در متن دکمه ---
    reset_db()
    db.add_button(CHILD_TOKEN, "کد", "text", "<code>a &lt; b</code>")
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "کد")))
    check("متن HTML سالم ارسال می‌شود",
          any("<code>" in t for t in cl.sent_texts()))

    # --- گزارش پیشرفت پیام همگانی ---
    for uid in range(600, 645):
        db.track_user(CHILD_TOKEN, uid, "u", None)
    total_users = len(db.bot_user_ids(CHILD_TOKEN))
    child_cl = FakeClient(bot_id=222222222)
    manager._clients[CHILD_TOKEN] = child_cl
    calls = []

    async def progress(ok, fail):
        calls.append((ok, fail))

    try:
        ok, fail = compat.run(manager.broadcast(
            CHILD_TOKEN, {"kind": "text", "text": "س", "path": None}, progress))
        check(f"همگانی برای همه‌ی {total_users} کاربر",
              (ok, fail) == (total_users, 0), f"{ok}/{fail}")
        check("گزارش پیشرفت صدا زده می‌شود", len(calls) >= 2, str(calls))
    finally:
        manager._clients.pop(CHILD_TOKEN, None)

    # --- کاربر بلاک‌کرده حذف می‌شود ---
    from pyrogram.errors import UserIsBlocked

    class BlockingClient(FakeClient):
        async def send_message(self, chat_id, text, **kw):
            if chat_id == 601:
                raise UserIsBlocked()
            return await FakeClient.send_message(self, chat_id, text, **kw)

    bc = BlockingClient(bot_id=222222222)
    manager._clients[CHILD_TOKEN] = bc
    try:
        ok, fail = compat.run(manager.broadcast(
            CHILD_TOKEN, {"kind": "text", "text": "س", "path": None}))
        check("کاربر بلاک‌کننده جدا شمرده می‌شود",
              (ok, fail) == (total_users - 1, 1), f"{ok}/{fail}")
        check("کاربر بلاک‌کننده از لیست خارج می‌شود",
              601 not in db.bot_user_ids(CHILD_TOKEN))
    finally:
        manager._clients.pop(CHILD_TOKEN, None)


def main() -> int:
    print("═" * 60)
    print(" 🧪 تست جامع پروژه ربات‌ساز")
    print("═" * 60)
    db.init()
    try:
        test_normalize()
        test_channels_db()
        test_force_join()
        test_media_buttons()
        test_child_support()
        test_mother_support()
        test_mother_panel()
        test_broadcast()
        test_validation()
        test_loop()
        test_multi_content_button()
        test_join_message()
        test_edge_cases()
        for fn in test_features.ALL:
            fn()
        for fn in test_new_features.ALL:
            fn()
        for fn in test_stats_features.ALL:
            fn()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

    print("\n" + "═" * 60)
    print(f" نتیجه: ✅ {len(PASS)} موفق   ❌ {len(FAIL)} ناموفق")
    print("═" * 60)
    if FAIL:
        for f in FAIL:
            print("  ❌", f)
        return 1
    print(" 🎉 همه تست‌ها پاس شدند.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
