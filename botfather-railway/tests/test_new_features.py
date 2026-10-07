"""تست قابلیت‌های جدید و باگ‌های رفع‌شده:
زیرمجموعه‌گیری (عکس‌دار/متنی)، پیام به کاربر خاص، escape کردن HTML،
پاک‌سازی فایل‌های رسانه، WAL و جستجوی امن.

اجرا:  python tests/test_all.py   (به‌صورت خودکار صدا زده می‌شود)
"""
from __future__ import annotations

import os
import shutil

from tests.harness import (  # noqa: F401
    CHILD_TOKEN,
    FakeCallbackQuery,
    FakeClient,
    FakeMessage,
    FakeUser,
    OWNER,
    USER,
    check,
    compat,
    db,
    dispatch,
    media,
    manager,
    reset_db,
    runtime,
    section,
)


# ══════════════════════════════════════════ ۱) escape کردن نام کاربر
def test_html_escaping():
    section("escape کردن نام کاربر در پیام‌های HTML")
    reset_db()
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_esc")
    # کاربری که < و & در نامش دارد — قبلاً پیام خوش‌آمد را نمی‌گرفت
    tricky = FakeUser(USER, "Ali <3 & <b>bad</b>")

    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, tricky, "/start")))
    texts = cl.sent_texts(USER)
    check("خوش‌آمد با نام سمی ارسال شد", any("سلام" in t for t in texts))
    check("کاراکتر < escape شده است",
          any("&lt;" in t for t in texts), str(texts))
    check("تگ جعلی <b> رندر نمی‌شود",
          not any("<b>bad</b>" in t for t in texts))

    # پیام اطلاع کاربر جدید به مالک هم باید سالم باشد
    owner_texts = cl.sent_texts(OWNER)
    check("اطلاع کاربر جدید به مالک سالم است",
          any("کاربر جدید" in t and "&lt;" in t for t in owner_texts),
          str(owner_texts))

    # فوتر هم {name} را escape می‌کند
    reset_db()
    db.set_setting(CHILD_TOKEN, "footer_text", "پایان {name}")
    db.add_button(CHILD_TOKEN, "راهنما", "text", "متن")
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, tricky, "راهنما")))
    check("فوتر با نام escape‌شده",
          any("پایان Ali &lt;3" in t for t in cl.sent_texts(USER)),
          str(cl.sent_texts(USER)))
    db.set_setting(CHILD_TOKEN, "footer_text", "")

    # متن وظیفه هم escape می‌شود
    from child import tasks
    db.set_setting(CHILD_TOKEN, "task_enabled", "1")
    db.set_setting(CHILD_TOKEN, "task_channel", "@c")
    db.set_setting(CHILD_TOKEN, "task_text", "سلام {name} — وظیفه")
    txt = tasks.render_text(CHILD_TOKEN, tricky)
    check("متن وظیفه با نام سمی سالم است",
          "&lt;" in txt and "<b>bad</b>" not in txt, txt)
    db.set_setting(CHILD_TOKEN, "task_enabled", "0")


# ══════════════════════════════════════════ ۲) زیرمجموعه‌گیری — دیتابیس
def test_referral_db():
    from child import referrals
    section("زیرمجموعه‌گیری — ثبت در دیتابیس")
    reset_db()
    referrals._resolved.clear() if hasattr(referrals, "_resolved") else None

    # دعوت‌کننده‌ای که ربات را استارت نکرده ثبت نمی‌شود
    check("دعوت‌کننده ناشناس رد می‌شود",
          referrals.register(CHILD_TOKEN, 881, 999) is False)

    db.track_user(CHILD_TOKEN, USER, "علی", None)
    check("دعوت معتبر ثبت می‌شود",
          referrals.register(CHILD_TOKEN, 881, USER) is True)
    # کاربر ۸۸۱ قبلاً توسط USER ثبت شده؛ دعوت‌کنندهٔ دیگر نباید او را بگیرد
    check("دعوت تکراری شمرده نمی‌شود",
          referrals.register(CHILD_TOKEN, 881, OWNER) is False)
    check("دعوت خودی رد می‌شود",
          referrals.register(CHILD_TOKEN, USER, USER) is False)
    check("referrer_of درست است",
          db.referrer_of(CHILD_TOKEN, 881) == USER)
    check("شمارش دعوت‌ها", db.referral_count(CHILD_TOKEN, USER) == 1)
    check("مجموع دعوت‌ها", db.referral_total(CHILD_TOKEN) == 1)

    # حذف ربات، دعوت‌ها را هم پاک می‌کند
    db.delete_bot(CHILD_TOKEN)
    check("حذف ربات، دعوت‌ها را هم پاک می‌کند",
          db.referral_total(CHILD_TOKEN) == 0)
    db.add_bot(CHILD_TOKEN, 222222222, "child_bot", OWNER)


# ══════════════════════════════════════════ ۳) زیرمجموعه‌گیری — مدل توکن
def test_referral_gate():
    from child import referrals
    section("زیرمجموعه‌گیری — مدل توکن (سوختن، انتظار، باز ماندن)")
    reset_db()
    db.set_setting(CHILD_TOKEN, "ref_enabled", "1")
    db.set_setting(CHILD_TOKEN, "ref_count", "2")
    bid_free = db.add_button(CHILD_TOKEN, "آزاد", "text", "محتوای آزاد")
    bid_locked = db.add_button(CHILD_TOKEN, "قفل‌دار", "text", "محتوای ویژه")
    # قفل فقط برای دکمهٔ «قفل‌دار»؛ تعداد ۰ = استفاده از تعداد کلی (۲)
    db.set_button_ref(CHILD_TOKEN, bid_locked, ref_req=1, ref_count=0)
    check("دکمهٔ بدون قفل gate ندارد", not referrals.button_gate(CHILD_TOKEN,
          db.button_by_id(CHILD_TOKEN, bid_free)))
    check("دکمهٔ قفل‌دار gate دارد", referrals.button_gate(CHILD_TOKEN,
          db.button_by_id(CHILD_TOKEN, bid_locked)))
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_ref")
    user = FakeUser(USER, "علی")

    # ۱) استارت هیچ قفل توکنی ندارد
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "/start")))
    texts = cl.sent_texts(USER)
    check("استارت پیام دعوت ندارد", not any("زیرمجموعه" in t for t in texts))
    check("خوش‌آمد مستقیم می‌آید", any("خوش آمدید" in t for t in texts))

    # ۲) دکمهٔ بدون قفل مستقیم باز می‌شود (بدون سوختن توکن)
    compat.run(dispatch(app, cl, FakeMessage(
        cl, FakeUser(881, "u881"), f"/start ref{USER}")))
    check("یک توکن unused ثبت شد", db.unused_tokens(CHILD_TOKEN, USER) == 1)
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "آزاد")))
    check("دکمهٔ بدون قفل مستقیم باز می‌شود",
          "محتوای آزاد" in " ".join(cl.sent_texts(USER)))
    check("توکنی سوخته نشد", db.unused_tokens(CHILD_TOKEN, USER) == 1)

    # ۳) دکمهٔ قفل‌دار با ۱ توکن (کمتر از ۲) → در انتظار، بدون سوختن
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "قفل‌دار")))
    texts = cl.sent_texts(USER)
    check("دکمهٔ قفل‌دار پیام دعوت می‌دهد",
          any("زیرمجموعه" in t for t in texts), str(texts))
    check("عنوان دکمه در پیام دعوت هست",
          any("قفل‌دار" in t for t in texts))
    check("تعداد لازم (۲) در پیام هست", any("2" in t for t in texts))
    check("لینک دعوت هست", any(f"?start=ref{USER}" in t for t in texts))
    check("دکمهٔ کنسل در پیام هست",
          any("کنسل" in str(e.get("reply_markup"))
              for e in cl.log if e["action"] == "send_message"))
    check("محتوای ویژه هنوز داده نمی‌شود",
          not any("محتوای ویژه" in t for t in texts))
    check("توکن کم‌بودن نمی‌سوزد", db.unused_tokens(CHILD_TOKEN, USER) == 1)

    # ۳-ب) کنسل کردن → فقط بستن پیام؛ توکن و وضعیت سالم
    kb_msg = next(e for e in cl.log if e["action"] == "send_message"
                  and "زیرمجموعه" in e["text"])
    cq = FakeCallbackQuery(cl, user, "refcancel",
                           FakeMessage(cl, user, "پیام دعوت"))
    compat.run(dispatch(app, cl, cq, kind="callback"))
    check("کنسل → پیام بسته شد",
          any(e["action"] == "delete" for e in cl.log))
    check("کنسل → توکن‌ها سالم‌اند", db.unused_tokens(CHILD_TOKEN, USER) == 1)

    # ۴) دعوت دوم → حالا ۲ توکن؛ دکمه باز می‌شود و دقیقاً ۲ توکن می‌سوزد
    compat.run(dispatch(app, cl, FakeMessage(
        cl, FakeUser(882, "u882"), f"/start ref{USER}")))
    check("دو توکن unused شد", db.unused_tokens(CHILD_TOKEN, USER) == 2)
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "قفل‌دار")))
    check("با توکن کافی، محتوا باز می‌شود",
          "محتوای ویژه" in " ".join(cl.sent_texts(USER)))
    total, used, unused = db.token_stats(CHILD_TOKEN, USER)
    check("دقیقاً ۲ توکن سوخت", (total, used, unused) == (2, 2, 0),
          f"{total}/{used}/{unused}")

    # ۵) دکمهٔ بازشده باز می‌ماند؛ دوباره زدن توکن جدید نمی‌سوزاند
    compat.run(dispatch(app, cl, FakeMessage(
        cl, FakeUser(883, "u883"), f"/start ref{USER}")))
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "قفل‌دار")))
    check("دکمهٔ بازشده دوباره هم محتوا می‌دهد (باز می‌ماند)",
          "محتوای ویژه" in " ".join(cl.sent_texts(USER)))
    total, used, unused = db.token_stats(CHILD_TOKEN, USER)
    check("دوباره زدن توکن نمی‌سوزاند (۱ آزاد مانده)",
          (total, used, unused) == (3, 2, 1), f"{total}/{used}/{unused}")

    # ۶) تعویض دکمه: دکمهٔ دیگری با همان توکن آزاد باز می‌شود بدون سوختن
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "آزاد")))
    check("دکمهٔ آزاد در کنار قفل‌دار کار می‌کند",
          "محتوای آزاد" in " ".join(cl.sent_texts(USER)))
    total, used, unused = db.token_stats(CHILD_TOKEN, USER)
    check("تعویض دکمه توکن نمی‌سوزاند", unused == 1)

    # ۷) دکمهٔ قفل‌دار دوم → توکن آزاد ۱، لازم ۳ → در انتظار
    bid2 = db.add_button(CHILD_TOKEN, "گرون", "text", "محتوای گرون")
    db.set_button_ref(CHILD_TOKEN, bid2, ref_req=1, ref_count=3)
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "گرون")))
    texts = cl.sent_texts(USER)
    check("توکن ناکافی برای دکمهٔ دوم → در انتظار",
          any("زیرمجموعه" in t for t in texts)
          and not any("محتوای گرون" in t for t in texts))
    check("توکن آزاد نسوخته", db.unused_tokens(CHILD_TOKEN, USER) == 1)

    # ۸) کلید اصلی خاموش → هیچ قفلی اثر ندارد
    db.set_setting(CHILD_TOKEN, "ref_enabled", "0")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(900, "u900"), "قفل‌دار")))
    check("کلید اصلی خاموش → قفل بی‌اثر",
          "محتوای ویژه" in " ".join(cl.sent_texts(900)))

    # ۹) معافیت مالک
    db.set_setting(CHILD_TOKEN, "ref_enabled", "1")
    db.set_button_ref(CHILD_TOKEN, bid_locked, ref_count=10)
    db.set_setting(CHILD_TOKEN, "owner_bypass", "1")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(OWNER, "مالک"), "قفل‌دار")))
    check("مالکِ معاف، دکمهٔ قفل‌دار را مستقیم می‌بیند",
          "محتوای ویژه" in " ".join(cl.sent_texts(OWNER)))
    db.set_setting(CHILD_TOKEN, "owner_bypass", "0")
    db.set_setting(CHILD_TOKEN, "ref_enabled", "0")
    db.set_button_ref(CHILD_TOKEN, bid_locked, ref_count=0)


# ═══════════════════ ۳-ب) ترتیب دروازه‌ها + کنسل خودکار پیام انتظار
def test_task_gate_before_token_and_autocancel():
    """قابلیت‌های ۱ و ۲ صاحب ربات با هم:
    • چکِ وظیفه اجباری «همیشه» قبل از قفل توکن انجام می‌شود.
    • انتخاب دکمه، پیام انتظار قبلی را خودکار می‌بندد (توکن نمی‌سوزد).
    • پیش‌فرض‌ها: کانال @HAJI_TAKAVAR_CH + متن ساده‌ی جدید.
    """
    from child import tasks
    section("ترتیب دروازه‌ها: وظیفه اجباری قبل از قفل توکن + کنسل خودکار")
    reset_db()
    db.set_setting(CHILD_TOKEN, "ref_enabled", "1")
    db.set_setting(CHILD_TOKEN, "ref_count", "2")
    bid = db.add_button(CHILD_TOKEN, "گنج", "text", "محتوای قفل‌شده")
    db.set_button_ref(CHILD_TOKEN, bid, ref_req=1, ref_count=0)
    db.set_setting(CHILD_TOKEN, "task_channel", "@lockchan")
    db.set_setting(CHILD_TOKEN, "task_enabled", "1")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_order")
    user = FakeUser(USER, "علی")

    # ۱) غیرعضو + بدون توکن → اول پیام وظیفه، نه پیام دعوت
    cl = FakeClient(bot_id=222222222)   # memberships خالی → غیرعضو
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "گنج")))
    txts = cl.sent_texts(USER)
    check("اول پیام وظیفه می‌آید (چک همیشه اول)",
          any("وظیفه اجباری" in t for t in txts), str(txts)[:200])
    check("پیام دعوت هنوز نمی‌آید", not any("زیرمجموعه" in t for t in txts))
    check("محتوا هنوز نمی‌آید", not any("محتوای قفل‌شده" in t for t in txts))

    # ۲) تأیید وظیفه (پنجره ۲ دقیقه) → حالا نوبت قفل توکن است
    db.set_task_verified(CHILD_TOKEN, USER)
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "گنج")))
    txts = cl.sent_texts(USER)
    check("بعد از تأیید وظیفه، پیام دعوت می‌آید",
          any("زیرمجموعه" in t for t in txts), str(txts)[:200])
    check("محتوا هنوز قفل است", not any("محتوای قفل‌شده" in t for t in txts))

    # ۳) انتخاب دوباره همان دکمه → پیام انتظار قبلی خودکار حذف می‌شود
    prompts_before = sum(1 for e in cl.log
                         if e["action"] == "send_message"
                         and "زیرمجموعه" in e["text"])
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "گنج")))
    check("پیام انتظار قبلی خودکار حذف شد",
          any(e["action"] == "delete" for e in cl.log))
    prompts_after = sum(1 for e in cl.log
                        if e["action"] == "send_message"
                        and "زیرمجموعه" in e["text"])
    check("پیام انتظار جدید جای قبلی را گرفت",
          prompts_after == prompts_before + 1)
    check("توکنی سوخته نشد", db.unused_tokens(CHILD_TOKEN, USER) == 0)

    # ۴) پیش‌فرض‌ها: کانال و متن طبق spec صاحب ربات
    db.set_setting(CHILD_TOKEN, "task_channel", "")
    cfg = tasks.config(CHILD_TOKEN)
    check("کانال پیش‌فرض @HAJI_TAKAVAR_CH است",
          cfg["channel"] == tasks.DEFAULT_TASK_CHANNEL == "@HAJI_TAKAVAR_CH")
    check("متن پیش‌فرض ساده است (بدون بولد)",
          cfg["text"] == tasks.DEFAULT_TASK_TEXT and "<b>" not in cfg["text"])
    check("متن رندرشده عین نمونه‌ی صاحب ربات است",
          tasks.render_text(CHILD_TOKEN, user)
          == "🤜 وظیفه اجباری\n\n"
             "برای دریافت فایل، ابتدا این خواسته انجام شود:\n"
             "🔹 @HAJI_TAKAVAR_CH")
    reset_db()


# ══════════════════════════════════════════ ۴) زیرمجموعه‌گیری — عکس‌دار
def test_referral_photo():
    from child import referrals
    section("زیرمجموعه‌گیری — پیام عکس‌دار (از مسیر دکمهٔ قفل‌دار)")
    reset_db()
    db.set_setting(CHILD_TOKEN, "ref_enabled", "1")
    db.set_setting(CHILD_TOKEN, "ref_count", "1")
    bid = db.add_button(CHILD_TOKEN, "ویژه", "text", "محتوای ویژه")
    db.set_button_ref(CHILD_TOKEN, bid, ref_req=1)
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_refphoto")
    user = FakeUser(USER, "علی")

    # عکس واقعی روی دیسک
    photo_dir = media.MEDIA_DIR / "222222222"
    photo_dir.mkdir(parents=True, exist_ok=True)
    photo_path = photo_dir / "ref_test.jpg"
    photo_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    db.set_setting(CHILD_TOKEN, "ref_photo_path", str(photo_path))

    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "ویژه")))
    check("پیام دعوت با عکس ارسال می‌شود",
          any(e["action"] == "send_photo" and e["chat_id"] == USER
              for e in cl.log), str(cl.log))
    check("کپشن عکس شامل متن دعوت است",
          any(e["action"] == "send_photo" and "زیرمجموعه" in (e.get("caption") or "")
              for e in cl.log))

    # عکس گم‌شده → تنظیم پاک و ارسال متنی
    db.set_setting(CHILD_TOKEN, "ref_photo_path", "/nonexistent/x.jpg")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(883, "u883"), "ویژه")))
    check("عکس گم‌شده → تنظیم پاک می‌شود",
          db.get_setting(CHILD_TOKEN, "ref_photo_path") == "")

    # پاک‌سازی
    db.set_setting(CHILD_TOKEN, "ref_enabled", "0")
    if photo_path.exists():
        photo_path.unlink()


# ══════════════════════════════════════════ ۵) زیرمجموعه‌گیری — پنل مادر
def test_referral_panel():
    from mother import bot as mb
    from mother import panels
    section("زیرمجموعه‌گیری — پنل ربات مادر")
    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    cl = FakeClient(bot_id=111111111, username="mother_bot")

    # پنل زیرمجموعه‌گیری
    cq = FakeCallbackQuery(cl, owner, f"ref:{tid}", FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    edit = cl.last("edit")
    check("پنل زیرمجموعه‌گیری باز می‌شود",
          edit and "زیرمجموعه" in edit["text"], str(edit and edit["text"]))

    # تنظیم تعداد
    mb.STATE[OWNER] = {"step": "ref_count", "token": CHILD_TOKEN, "tid": tid}
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "3")))
    check("تعداد دعوت ذخیره شد",
          db.get_setting(CHILD_TOKEN, "ref_count") == "3")

    # متن سفارشی + پیش‌نمایش
    mb.STATE[OWNER] = {"step": "ref_text", "token": CHILD_TOKEN, "tid": tid}
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "دعوت کن {count} نفر لینک: {link}")))
    check("متن سفارشی ذخیره شد",
          "دعوت کن" in db.get_setting(CHILD_TOKEN, "ref_text"))
    check("پیش‌نمایش متن نمایش داده شد",
          any("پیش‌نمایش" in t for t in cl.sent_texts(OWNER)))

    # بازگشت به پیش‌فرض
    mb.STATE[OWNER] = {"step": "ref_text", "token": CHILD_TOKEN, "tid": tid}
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "پیش‌فرض")))
    check("بازگشت به متن پیش‌فرض",
          db.get_setting(CHILD_TOKEN, "ref_text") == "")

    # فعال‌سازی از پنل
    cq = FakeCallbackQuery(cl, owner, f"refon:{tid}", FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("فعال‌سازی از پنل",
          db.get_setting(CHILD_TOKEN, "ref_enabled") == "1")

    # دکمه در پنل اصلی ربات هست
    kb = mb.bot_panel_kb(CHILD_TOKEN)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("دکمه زیرمجموعه‌گیری در پنل اصلی هست",
          any("زیرمجموعه" in l for l in labels), str(labels))
    db.set_setting(CHILD_TOKEN, "ref_enabled", "0")


# ══════════════════════════════════════════ ۶) پیام به کاربر خاص
def test_direct_message():
    from mother import bot as mb
    from mother import panels
    section("پیام به کاربر خاص")
    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    db.track_user(CHILD_TOKEN, USER, "علی", None)

    # منوی کاربران دکمه پیام به کاربر خاص را دارد
    kb = panels.users_view(CHILD_TOKEN, tid)[1]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("دکمه «پیام به کاربر خاص» در منوی کاربران",
          any("پیام به کاربر" in l for l in labels))

    # کارت کاربر دکمه ارسال پیام را دارد
    kb = panels.user_card(CHILD_TOKEN, tid, USER)[1]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("دکمه «ارسال پیام» در کارت کاربر",
          any("ارسال پیام" in l for l in labels))

    # جریان کامل: انتخاب از طریق آیدی → ارسال متن
    mb.STATE[OWNER] = {"step": "usr_dm_pick", "token": CHILD_TOKEN, "tid": tid}
    cl = FakeClient(bot_id=111111111, username="mother_bot")
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, str(USER))))
    check("کارت کاربر بعد از وارد کردن آیدی باز می‌شود",
          any("پرونده کاربر" in t for t in cl.sent_texts(OWNER)))

    child_cl = FakeClient(bot_id=222222222)
    manager._clients[CHILD_TOKEN] = child_cl
    try:
        mb.STATE[OWNER] = {"step": "dm_msg", "token": CHILD_TOKEN,
                           "tid": tid, "target": USER}
        compat.run(dispatch(mb.app, cl,
                            FakeMessage(cl, owner, "سلام — پیام مخصوص شما")))
        check("پیام با کلاینت ربات فرزند به کاربر رسید",
              any("پیام مخصوص شما" in t for t in child_cl.sent_texts(USER)),
              str(child_cl.sent_texts(USER)))
        check("تأیید ارسال به مالک داده شد",
              any("ارسال شد" in t for t in cl.sent_texts(OWNER)))
    finally:
        manager._clients.pop(CHILD_TOKEN, None)

    # ربات خاموش → پیام خطا
    mb.STATE[OWNER] = {"step": "dm_msg", "token": CHILD_TOKEN,
                       "tid": tid, "target": USER}
    cl.clear()
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "تست")))
    check("ربات خاموش → پیام خطا",
          any("خاموش" in t for t in cl.sent_texts(OWNER)))
    check("وضعیت پاک شده", OWNER not in mb.STATE)

    # آیدی ناشناس در usr_dm_pick
    mb.STATE[OWNER] = {"step": "usr_dm_pick", "token": CHILD_TOKEN, "tid": tid}
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "424242")))
    check("آیدی ناشناس → پیام «پیدا نشد»",
          any("نیست" in t for t in cl.sent_texts(OWNER)))


# ══════════════════════════════════════════ ۷) پاک‌سازی فایل‌های رسانه
def test_media_cleanup():
    section("پاک‌سازی فایل‌های رسانه هنگام حذف")
    reset_db()
    sub = media.MEDIA_DIR / "222222222"
    sub.mkdir(parents=True, exist_ok=True)

    f1 = sub / "item1.jpg"
    f1.write_bytes(b"\x00" * 64)
    bid = db.add_button(CHILD_TOKEN, "مولتی", "text", "متن")
    iid = db.add_button_item(CHILD_TOKEN, bid, "photo", str(f1))
    check("فایل قبل از حذف وجود دارد", f1.exists())

    n = media.delete_button_files(CHILD_TOKEN, bid)
    check("فایل آیتم دکمه حذف شد", n >= 1 and not f1.exists())

    # حذف کل پوشه ربات
    f2 = sub / "other.bin"
    f2.write_bytes(b"\x00" * 32)
    n = media.delete_bot_files(CHILD_TOKEN)
    check("پوشه رسانه ربات حذف شد", n == 1 and not sub.exists())

    # unlink_media خارج از MEDIA_DIR حذف نمی‌کند
    outside = media.MEDIA_DIR.parent / "outside.bin"
    outside.write_bytes(b"\x00" * 8)
    check("فایل خارج از MEDIA_DIR حذف نمی‌شود",
          media.unlink_media(str(outside)) is False and outside.exists())
    outside.unlink()

    # مسیر None ایمن است
    check("مسیر خالی ایمن است", media.unlink_media(None) is False)


# ══════════════════════════════════════════ ۸) دیتابیس: WAL و جستجو
def test_db_hardening():
    section("دیتابیس — WAL و جستجوی امن")
    db.init()
    mode = db.fetchone("PRAGMA journal_mode")
    check("حالت WAL فعال است", mode is not None and str(mode["journal_mode"]).lower() == "wal",
          str(mode and dict(mode)))

    # جستجو: % و _ نباید وایلدکارد رفتار کنند
    reset_db()
    db.track_user(CHILD_TOKEN, 700, "الف", "a_b")
    db.track_user(CHILD_TOKEN, 701, "ب", "axb")
    db.track_user(CHILD_TOKEN, 702, "پ", "c%d")
    rows = db.search_users(CHILD_TOKEN, "a_b")
    check("زیرخط (_) وایلدکارد حساب نمی‌شود",
          len(rows) == 1 and rows[0]["user_id"] == 700, str([dict(r) for r in rows]))
    rows = db.search_users(CHILD_TOKEN, "c%")
    check("درصد (%) وایلدکارد حساب نمی‌شود",
          len(rows) == 1 and rows[0]["user_id"] == 702, str([dict(r) for r in rows]))


# ══════════════════════════════════════════ ۹) ویزارد: عکس به‌صورت فایل
def test_wizard_photo_as_document():
    from types import SimpleNamespace
    from mother import wizard
    section("ویزارد — عکسِ فرستاده‌شده به‌صورت فایل")
    state = {"token": CHILD_TOKEN, "title": "ت", "text": None,
             "items": [], "stage": "photo", "step": "wz_collect",
             "chat_id": 1, "panel_id": None}

    sent = []

    async def fake_save(client, message, subdir):
        sent.append(subdir)
        return "/tmp/fake.jpg"

    orig_save = media.save_media
    media.save_media = fake_save
    try:
        cl = FakeClient(bot_id=222222222)
        msg = FakeMessage(cl, FakeUser(USER), caption=None)
        msg.media = None
        object.__setattr__(msg, "document", SimpleNamespace(
            file_id="F", file_unique_id="U", file_name="pic.jpg",
            mime_type="image/jpeg"))
        ok = compat.run(wizard.collect(cl, state, msg))
        check("عکس به‌صورت فایل در مرحله عکس پذیرفته می‌شود", ok is True)
        check("به‌عنوان عکس ذخیره شد",
              state["items"] and state["items"][0]["kind"] == "photo")
    finally:
        media.save_media = orig_save


# ════════════════════════════════════ پنل قفل دکمه‌ها و شناخت پست‌ها
def test_referral_button_panel():
    from mother import bot as mb
    section("پنل قفل زیرمجموعه‌گیری هر دکمه")
    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    cl = FakeClient(bot_id=111111111, username="mother_bot")
    bid = db.add_button(CHILD_TOKEN, "محصول", "text", "متن")

    # 🎁 در لیست دکمه‌ها هست
    _, kb = mb._btns_panel(CHILD_TOKEN, tid)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("دکمهٔ 🎁 برای هر دکمه در لیست هست", "🎁" in labels, str(labels))

    # باز کردن پنل قفل
    cq = FakeCallbackQuery(cl, owner, f"btnref:{tid}:{bid}",
                           FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    edit = cl.last("edit")
    check("پنل قفل دکمه باز می‌شود",
          edit and "قفل توکن دکمه" in edit["text"], str(edit and edit["text"]))

    # روشن کردن قفل
    cq = FakeCallbackQuery(cl, owner, f"btnrefon:{tid}:{bid}",
                           FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("قفل روشن شد", db.button_by_id(CHILD_TOKEN, bid)["ref_req"] == 1)

    # آیکون 🔒 در لیست
    _, kb = mb._btns_panel(CHILD_TOKEN, tid)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("آیکون 🔒 برای دکمهٔ قفل‌دار", "🔒" in labels)

    # تعداد جداگانهٔ دکمه
    mb.STATE[OWNER] = {"step": "btn_ref_count", "token": CHILD_TOKEN,
                       "tid": tid, "bid": bid}
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "6")))
    check("تعداد ۶ برای دکمه ذخیره شد",
          db.button_by_id(CHILD_TOKEN, bid)["ref_count"] == 6)

    # عدد نامعتبر رد می‌شود
    mb.STATE[OWNER] = {"step": "btn_ref_count", "token": CHILD_TOKEN,
                       "tid": tid, "bid": bid}
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "زیاد")))
    check("عدد نامعتبر رد می‌شود",
          db.button_by_id(CHILD_TOKEN, bid)["ref_count"] == 6)

    # صفر = تعداد کلی
    mb.STATE[OWNER] = {"step": "btn_ref_count", "token": CHILD_TOKEN,
                       "tid": tid, "bid": bid}
    compat.run(dispatch(mb.app, cl, FakeMessage(cl, owner, "0")))
    check("صفر یعنی تعداد کلی",
          db.button_by_id(CHILD_TOKEN, bid)["ref_count"] == 0)

    # خاموش کردن قفل
    cq = FakeCallbackQuery(cl, owner, f"btnrefon:{tid}:{bid}",
                           FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("قفل خاموش شد", db.button_by_id(CHILD_TOKEN, bid)["ref_req"] == 0)

    # کال‌بک با دکمهٔ حذف‌شده نباید بشکند
    cq = FakeCallbackQuery(cl, owner, f"btnref:{tid}:99999",
                           FakeMessage(cl, owner, "x"))
    compat.run(dispatch(mb.app, cl, cq, kind="callback"))
    check("آیدی نامعتبر → پیام «وجود ندارد»",
          any("وجود ندارد" in t for t in cl.sent_texts(OWNER))
          or (cl.last("edit") and "وجود ندارد" in cl.last("edit")["text"]))



# ══════════════════════════════════════════ رگرسیون باگ قفل زیرمجموعه
def test_ref_lock_regression():
    """باگ گزارش‌شده: دکمهٔ قفل‌شده بدون هیچ اخطاری باز می‌شد.

    سناریوی کاربر: دکمه ساخته و قفل شد (با کلید اصلی خاموش یا بدون تعداد) —
    اکانتی که قبلاً استارت کرده بود بدون اخطار محتوا می‌گرفت.
    """
    from child import referrals
    from mother import bot as mb
    section("رگرسیون: قفل دکمه باید همیشه واقعی باشد")
    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")
    bid = db.add_button(CHILD_TOKEN, "گنج", "text", "محتوای قفل‌شده")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_reflock")
    tester = FakeUser(USER, "تستر قدیمی")
    db.track_user(CHILD_TOKEN, USER, "تستر", None)

    # سازنده فقط دکمه را قفل می‌کند (همان کاری که کاربر کرد) —
    # کلید اصلی خاموش و هیچ تعدادی تنظیم نیست:
    cq = FakeCallbackQuery(mcl, owner, f"btnrefon:{tid}:{bid}",
                           FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    check("قفل دکمه روشن شد", db.button_by_id(CHILD_TOKEN, bid)["ref_req"] == 1)
    check("کلید اصلی خودکار روشن شد",
          db.get_setting(CHILD_TOKEN, "ref_enabled") == "1")
    check("تعداد لازم خودکار ۱ شد", referrals.need_for(
        CHILD_TOKEN, db.button_by_id(CHILD_TOKEN, bid)) == 1)

    # اکانت قدیمی (قبلاً استارت کرده و دعوتی ندارد) → باید قفل ببیند
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, tester, "گنج")))
    txts = cl.sent_texts(USER)
    check("اکانت قدیمی بدون دعوت، اخطار زیرمجموعه می‌گیرد",
          any("زیرمجموعه" in t for t in txts), str(txts)[:200])
    check("محتوای قفل‌شده داده نمی‌شود",
          not any("محتوای قفل‌شده" in t for t in txts))
    check("لینک دعوت اختصاصی در پیام هست",
          any(f"?start=ref{USER}" in t for t in txts))

    # «کلید اصلی» یک کلید اضطراری است: اگر سازنده دستی خاموشش کند،
    # همه‌ی قفل‌ها موقتاً بی‌اثر می‌شوند (رفتار مستند کلید اضطراری) —
    # ولی در جریانِ عادی، همان قفل‌کردنِ دکمه، کلید اصلی را خودکار روشن
    # می‌کند و پنل هم موقع خاموش‌کردن هشدار می‌دهد.
    db.set_setting(CHILD_TOKEN, "ref_enabled", "0")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, tester, "گنج")))
    check("کلید اضطراری خاموش → قفل‌ها موقتاً بی‌اثر",
          any("محتوای قفل‌شده" in t for t in cl.sent_texts(USER)))
    db.set_setting(CHILD_TOKEN, "ref_enabled", "1")

    # یک دعوت → آزاد می‌شود
    compat.run(dispatch(app, cl, FakeMessage(
        cl, FakeUser(955, "دعوت‌شده"), f"/start ref{USER}")))
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, tester, "گنج")))
    check("بعد از ۱ دعوت، محتوا باز می‌شود",
          any("محتوای قفل‌شده" in t for t in cl.sent_texts(USER)))

    # خاموش‌کردن قفل از پنل → دوباره آزاد
    cq = FakeCallbackQuery(mcl, owner, f"btnrefon:{tid}:{bid}",
                           FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    check("قفل خاموش شد", db.button_by_id(CHILD_TOKEN, bid)["ref_req"] == 0)
    reset_db()


def test_start_has_no_ref_gate():
    section("استارت — دیگر دروازهٔ سراسری دعوت وجود ندارد")
    reset_db()
    db.set_setting(CHILD_TOKEN, "ref_enabled", "1")
    db.set_setting(CHILD_TOKEN, "ref_count", "5")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_nogate")
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(USER, "علی"), "/start")))
    texts = cl.sent_texts(USER)
    check("با دعوت صفر هم استارت کامل است",
          any("خوش آمدید" in t for t in texts), str(texts))
    check("پیام دعوت در استارت نمی‌آید",
          not any("زیرمجموعه" in t for t in texts))
    db.set_setting(CHILD_TOKEN, "ref_enabled", "0")


ALL = [
    test_html_escaping,
    test_referral_db,
    test_referral_gate,
    test_task_gate_before_token_and_autocancel,
    test_referral_photo,
    test_referral_panel,
    test_referral_button_panel,
    test_start_has_no_ref_gate,
    test_ref_lock_regression,
    test_direct_message,
    test_media_cleanup,
    test_db_hardening,
    test_wizard_photo_as_document,
]
