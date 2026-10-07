"""تست قابلیت‌های جدید: آمار، دموگرافیک، پسورد، رندوم، سرچ، لایک/دیسلایک، حذف خودکار."""
from __future__ import annotations

import asyncio

from tests.harness import (
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
    reset_db,
    runtime,
    section,
)

RND_BTN = runtime.RND_BTN
SEARCH_BTN = runtime.SEARCH_BTN


# ══════════════════════════════════════════ ۱) لایک/دیسلایک و بازدید
def test_votes_and_views():
    section("👍👎 لایک/دیسلایک و 👁 بازدید فایل‌ها")
    reset_db()
    db.set_setting(CHILD_TOKEN, "task_wait", "0")
    bid = db.add_button(CHILD_TOKEN, "فایل محبوب", "text", "محتوای ویژه")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_vote")
    u1, u2 = FakeUser(USER, "علی"), FakeUser(778, "مریم")

    check("پیش‌فرض لایک/دیسلایک روشن است",
          db.get_setting(CHILD_TOKEN, "votes_enabled", "1") == "1")

    # ارسال محتوا → بازدید +۱ و کیبورد 👍/👎
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, u1, "فایل محبوب")))
    check("بازدید ثبت شد", db.views_of(CHILD_TOKEN, bid) == 1)
    last = cl.last("send_message")
    kb = last["reply_markup"]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("دکمه‌های 👍/👎 زیر محتوا هست",
          any("👍" in l for l in labels) and any("👎" in l for l in labels),
          str(labels))
    check("شمارنده‌ها صفر هستند", any("👍 0" in l for l in labels))

    # لایک کاربر اول
    cq = FakeCallbackQuery(cl, u1, f"fv:{bid}:1",
                           FakeMessage(cl, u1, "محتوا", msg_id=555))
    compat.run(dispatch(app, cl, cq, kind="callback"))
    check("لایک ثبت شد", db.vote_counts(CHILD_TOKEN, bid) == (1, 0))
    check("پیام تأیید داده شد",
          any("ثبت شد" in e.get("text", "") for e in cl.log
              if e["action"] == "answer"))
    check("شمارنده روی پیام به‌روز شد",
          any(e["action"] == "edit_markup" for e in cl.log))
    markup = cl.last("edit_markup")["reply_markup"]
    labels2 = [b.text for row in markup.inline_keyboard for b in row]
    check("لایک ۱ شد در دکمه", any("👍 1" in l for l in labels2), str(labels2))

    # رأی همان کاربر عوض می‌شود (نه جمع می‌شود)
    compat.run(dispatch(app, cl, FakeCallbackQuery(
        cl, u1, f"fv:{bid}:0", FakeMessage(cl, u1, "محتوا", msg_id=555)),
        kind="callback"))
    check("رأی عوض شد (دیسلایک)", db.vote_counts(CHILD_TOKEN, bid) == (0, 1))
    # دوباره همان → برداشتن رأی
    compat.run(dispatch(app, cl, FakeCallbackQuery(
        cl, u1, f"fv:{bid}:0", FakeMessage(cl, u1, "محتوا", msg_id=555)),
        kind="callback"))
    check("دوباره همان رأی → برداشتن", db.vote_of(CHILD_TOKEN, bid, USER) is None)

    # کاربر دوم لایک می‌کند → جمع کلی
    compat.run(dispatch(app, cl, FakeCallbackQuery(
        cl, u2, f"fv:{bid}:1", FakeMessage(cl, u2, "محتوا", msg_id=555)),
        kind="callback"))
    likes, dislikes = db.votes_total(CHILD_TOKEN)
    check("مجموع کلی درست است", (likes, dislikes) == (1, 0))

    # دکمهٔ حذف‌شده → خطای ملایم
    compat.run(dispatch(app, cl, FakeCallbackQuery(
        cl, u2, "fv:99999:1", FakeMessage(cl, u2, "x", msg_id=556)),
        kind="callback"))
    check("رأی به دکمهٔ حذف‌شده پیام خطا می‌دهد",
          any("موجود نیست" in e.get("text", "") for e in cl.log
              if e["action"] == "answer"))

    # خاموش‌کردن لایک/دیسلایک → بدون کیبورد
    db.set_setting(CHILD_TOKEN, "votes_enabled", "0")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, u1, "فایل محبوب")))
    last = cl.last("send_message")
    kb = last["reply_markup"] if last else None
    check("با خاموشی، کیبورد رأی نیست", kb is None)
    check("بازدید همچنان شمرده می‌شود", db.views_of(CHILD_TOKEN, bid) == 2)
    reset_db()


def test_views_not_counted_in_preview():
    section("پیش‌نمایش پنل، بازدید ثبت نمی‌کند")
    from mother.bot import _btns_panel  # noqa: F401
    from mother import bot as mb
    reset_db()
    bid = db.add_button(CHILD_TOKEN, "پیش‌نمایشی", "text", "متن")
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")
    cq = FakeCallbackQuery(mcl, owner, f"btnprev:{0}:{bid}",
                           FakeMessage(mcl, owner, "x"))
    # btnprev مستقیماً در bot.py هندل می‌شود؛ token از tid می‌آید
    tid = CHILD_TOKEN.split(":")[0]
    cq = FakeCallbackQuery(mcl, owner, f"btnprev:{tid}:{bid}",
                           FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    check("پیش‌نمایش محتوا را می‌فرستد",
          any("متن" in t for t in mcl.sent_texts(OWNER)))
    check("پیش‌نمایش بازدید ثبت نمی‌کند", db.views_of(CHILD_TOKEN, bid) == 0)
    check("پیش‌نمایش کیبورد رأی ندارد",
          not any(e.get("reply_markup") and "👍" in str(e.get("reply_markup"))
                  for e in mcl.log if e["action"] == "send_message"))
    reset_db()


# ══════════════════════════════════════════ ۲) دموگرافیک
def test_demographics():
    section("🎂 پرسش سن و جنسیت + آمار دموگرافیک")
    reset_db()
    db.set_setting(CHILD_TOKEN, "demo_ask", "1")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_demo")
    new_user = FakeUser(880, "تازه")

    # استارت کاربر جدید → بعد از خوش‌آمد، سؤال سن
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, new_user, "/start")))
    txts = cl.sent_texts(880)
    check("خوش‌آمد آمد", any("خوش آمدید" in t for t in txts))
    check("سؤال سن پرسیده شد", any("سن" in t for t in txts), str(txts))

    # پاسخ نامعتبر
    compat.run(dispatch(app, cl, FakeMessage(cl, new_user, "سالوم")))
    check("پاسخ نامعتبر دوباره می‌پرسد",
          any("عدد" in t for t in cl.sent_texts(880)))

    # سن (با ارقام فارسی) → سؤال جنسیت
    compat.run(dispatch(app, cl, FakeMessage(cl, new_user, "۲۵")))
    check("سؤال جنسیت آمد", any("جنسیت" in t for t in cl.sent_texts(880)))
    row = db.get_bot_user(CHILD_TOKEN, 880)
    check("سن ذخیره شد", row["age"] == 25)

    # جنسیت → پایان
    compat.run(dispatch(app, cl, FakeMessage(cl, new_user, "👨 مرد")))
    row = db.get_bot_user(CHILD_TOKEN, 880)
    check("جنسیت ذخیره شد", row["gender"] == "m")
    check("پیام پایان",
          any("ممنون" in t for t in cl.sent_texts(880)))

    # «رد کردن» در مرحلهٔ جنسیت هم کار می‌کند
    new2 = FakeUser(881, "دومی")
    compat.run(dispatch(app, cl, FakeMessage(cl, new2, "/start")))
    compat.run(dispatch(app, cl, FakeMessage(cl, new2, "30")))
    compat.run(dispatch(app, cl, FakeMessage(cl, new2, "رد کردن")))
    row = db.get_bot_user(CHILD_TOKEN, 881)
    check("رد کردن → جنسیت خالی می‌ماند",
          row["age"] == 30 and not row["gender"])

    # آمار دموگرافیک
    db.set_user_meta(CHILD_TOKEN, 881, gender="f")
    demo = db.demo_stats(CHILD_TOKEN)
    check("میانگین سنی درست است", abs(demo["avg_age"] - 27.5) < 0.01,
          str(demo))
    check("توزیع جنسیتی درست است",
          (demo["male"], demo["female"]) == (1, 1))

    # کاربر داخل حالت دمو نباید محتوا بگیرد؛ بعد از انصراف آزاد می‌شود
    new3 = FakeUser(882, "سومی")
    compat.run(dispatch(app, cl, FakeMessage(cl, new3, "/start")))
    compat.run(dispatch(app, cl, FakeMessage(cl, new3, "❌ انصراف")))
    check("انصراف حالت دمو را می‌بندد",
          (CHILD_TOKEN, 882) not in runtime._demo_stage)

    # ── فقط بار اول: استارت دوباره دیگر سؤال نمی‌پرسد ──
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, new_user, "/start")))
    txts2 = cl.sent_texts(880)
    check("استارت دوم → خوش‌آمد می‌آید",
          any("خوش آمدید" in t for t in txts2))
    check("استارت دوم → دیگر سؤال سن نمی‌آید",
          not any("سن خود را" in t for t in txts2), str(txts2))

    # کاربری که «رد کردن» زده هم دیگر پرسیده نمی‌شود
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, new3, "/start")))
    txts3 = cl.sent_texts(882)
    check("استارت بعد از «رد کردن» → سؤال نمی‌آید",
          not any("سن خود را" in t for t in txts3), str(txts3))
    reset_db()


# ══════════════════════════════════════════ ۳) پسورد فایل‌ها
def test_file_password():
    section("🔑 پسورد فایل‌ها")
    reset_db()
    db.set_setting(CHILD_TOKEN, "file_pass", "رمز۱۲۳")
    db.add_button(CHILD_TOKEN, "مخفی", "text", "محتوای مخفی")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_pass")
    u = FakeUser(USER, "علی")

    # درخواست محتوا → درخواست رمز
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "مخفی")))
    txts = cl.sent_texts(USER)
    check("درخواست رمز آمد", any("رمز" in t for t in txts), str(txts)[:200])
    check("محتوا داده نشد", not any("محتوای مخفی" in t for t in txts))

    # رمز غلط
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "اشتباه")))
    check("رمز غلط رد می‌شود",
          any("اشتباه" in t for t in cl.sent_texts(USER)))

    # رمز درست (با ارقام فارسیِ داخل رمز: مقایسهٔ دقیق متن)
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "رمز۱۲۳")))
    check("رمز درست پذیرفته شد", any("درست بود" in t for t in cl.sent_texts(USER)))
    # محتوای در انتظار، خودکار ارسال می‌شود
    check("محتوای در انتظار خودکار ارسال شد",
          any("محتوای مخفی" in t for t in cl.sent_texts(USER)))
    check("وضعیت رمز ذخیره شد",
          db.user_get_state(CHILD_TOKEN, USER, "pass_ok") == "رمز۱۲۳")

    # دفعات بعد بدون رمز
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "مخفی")))
    check("دفعات بعد مستقیم محتوا می‌دهد",
          any("محتوای مخفی" in t for t in cl.sent_texts(USER)))

    # تغییر رمز → همه دوباره قفل می‌شوند
    db.set_setting(CHILD_TOKEN, "file_pass", "جدید")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "مخفی")))
    check("تغییر رمز → دوباره درخواست رمز",
          any("رمز" in t for t in cl.sent_texts(USER)))
    reset_db()


def _reply_btn_texts(cl, user_id, contains):
    """برچسب دکمه‌های آخرین پیام حاوی «contains» را برمی‌گرداند."""
    for e in reversed(cl.log):
        if (e["action"] == "send_message" and e["chat_id"] == user_id
                and contains in str(e["text"]) and e.get("reply_markup")):
            kb = e["reply_markup"]
            rows = getattr(kb, "keyboard", None) or getattr(kb, "inline_keyboard", None)
            if rows is not None:
                return [b.text for row in rows for b in row]
    return []


# ══════════════════════════════════════════ ۴) فایل رندوم
def test_random_file():
    section("🎲 فایل رندوم")
    reset_db()
    db.set_setting(CHILD_TOKEN, "task_wait", "0")
    for t in ("یکی", "دومی", "سومی"):
        db.add_button(CHILD_TOKEN, t, "text", f"محتوای {t}")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_rnd")
    u = FakeUser(USER, "علی")

    # وقتی خاموش است دکمه‌ای در منو نیست
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "/start")))
    labels = _reply_btn_texts(cl, USER, "خوش آمدید")
    check("خاموش → دکمهٔ رندوم در منو نیست",
          not any(RND_BTN in l for l in labels), str(labels))

    db.set_setting(CHILD_TOKEN, "rnd_enabled", "1")
    db.set_setting(CHILD_TOKEN, "search_enabled", "1")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "/start")))
    labels = _reply_btn_texts(cl, USER, "خوش آمدید")
    check("روشن → دکمهٔ رندوم در منو هست",
          any(RND_BTN in l for l in labels), str(labels))
    check("روشن → دکمهٔ سرچ هم در منو هست",
          any(SEARCH_BTN in l for l in labels), str(labels))

    # فشار دکمه → یکی از محتواها ارسال می‌شود
    compat.run(dispatch(app, cl, FakeMessage(cl, u, RND_BTN)))
    txt = " ".join(cl.sent_texts(USER))
    got = [t for t in ("محتوای یکی", "محتوای دومی", "محتوای سومی")
           if t in txt]
    check("یک فایل رندوم ارسال شد", len(got) == 1, got)

    # دکمه‌های قفل‌دار و بازنشده از استخر رندوم حذف می‌شوند
    bid_locked = db.add_button(CHILD_TOKEN, "قفل‌دار", "text", "محتوای قفل")
    db.set_button_ref(CHILD_TOKEN, bid_locked, ref_req=1, ref_count=5)
    db.set_setting(CHILD_TOKEN, "ref_enabled", "1")   # هم‌راستا با panel auto-enable
    pool = runtime.random_pool(CHILD_TOKEN, USER)
    titles = [b["title"] for b in pool]
    check("دکمهٔ قفل‌دار در استخر رندوم نیست", "قفل‌دار" not in titles, titles)
    reset_db()


# ══════════════════════════════════════════ ۵) جستجوی فایل
def test_file_search():
    section("🔍 جستجوی فایل")
    reset_db()
    db.set_setting(CHILD_TOKEN, "task_wait", "0")
    db.add_button(CHILD_TOKEN, "کتاب ریاضی", "text", "جزوه ریاضی")
    db.add_button(CHILD_TOKEN, "کتاب فیزیک", "text", "جزوه فیزیک")
    db.add_button(CHILD_TOKEN, "خلاصه‌ی شیمی", "text", "متن شیمی")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_srch")
    u = FakeUser(USER, "علی")

    db.set_setting(CHILD_TOKEN, "search_enabled", "1")
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, u, SEARCH_BTN)))
    check("درخواست کلیدواژه آمد", any("کلیدواژه" in t for t in cl.sent_texts(USER)))

    # جستجو بر اساس عنوان
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "کتاب")))
    txt = " ".join(cl.sent_texts(USER))
    check("نتایج عنوان آمد", "2 نتیجه" in txt, txt[:200])
    check("نتایج به‌صورت دکمهٔ اینلاین هستند",
          any("fget:" in str(e.get("reply_markup"))
              for e in cl.log if e["action"] == "send_message"))

    # جستجو بر اساس متن دکمه
    compat.run(dispatch(app, cl, FakeMessage(cl, u, SEARCH_BTN)))
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "شیمی")))
    labels = _reply_btn_texts(cl, USER, "نتیجه")
    check("جستجو در متن هم هست", any("شیمی" in l for l in labels), str(labels))

    # بدون نتیجه
    compat.run(dispatch(app, cl, FakeMessage(cl, u, SEARCH_BTN)))
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "چیزی‌که‌نیست")))
    check("بدون نتیجه پیام مناسب",
          any("پیدا نشد" in t for t in cl.sent_texts(USER)))

    # دریافت از نتایج (fget)
    bid = db.button_by_title(CHILD_TOKEN, "کتاب ریاضی")["id"]
    compat.run(dispatch(app, cl, FakeCallbackQuery(
        cl, u, f"fget:{bid}", FakeMessage(cl, u, "نتایج")), kind="callback"))
    check("دریافت از نتیجهٔ جستجو محتوا می‌دهد",
          any("جزوه ریاضی" in t for t in cl.sent_texts(USER)))
    check("بازدید فایل از مسیر سرچ هم شمرده شد",
          db.views_of(CHILD_TOKEN, bid) == 1)

    # کاراکترهای LIKE نباید همه‌چیز را برگردانند
    rows = runtime.search_buttons(CHILD_TOKEN, "%")
    check("کاراکتر % به‌عنوان وایلدکارد رفتار نمی‌کند", len(rows) == 0)
    reset_db()


# ══════════════════════════════════════════ ۶) حذف خودکار
def test_autodel():
    section("🗑 حذف خودکار محتوا")
    reset_db()
    db.set_setting(CHILD_TOKEN, "task_wait", "0")
    db.add_button(CHILD_TOKEN, "زودگذر", "text", "محتوای زودگذر")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_autodel")
    u = FakeUser(USER, "علی")

    # خاموش → حذفی نیست
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, u, "زودگذر")))
    check("خاموش → حذفی در کار نیست",
          not any(e["action"] == "delete" for e in cl.log))

    # روشن → پیام‌ها حذف می‌شوند (همه در یک لوپ تا تسک پس‌زمینه اجرا شود)
    db.set_setting(CHILD_TOKEN, "autodel", "1")
    bid = db.button_by_title(CHILD_TOKEN, "زودگذر")["id"]
    btn = db.button_by_id(CHILD_TOKEN, bid)
    real_sleep = asyncio.sleep

    async def fast_sleep(sec, *a, **kw):
        await real_sleep(0.05)

    async def run_all():
        cl2 = FakeClient(bot_id=222222222)
        msgs = await runtime._send_button_content(cl2, USER, btn, CHILD_TOKEN,
                                                  with_stats=True)
        check("محتوا برای حذف خودکار ارسال شد", len(msgs) == 1)
        runtime.schedule_autodel(CHILD_TOKEN, msgs)
        await real_sleep(0.3)
        return cl2

    from unittest import mock
    with mock.patch("asyncio.sleep", new=fast_sleep):
        cl2 = compat.run(run_all())
    check("محتوا بعد از تاخیر حذف شد",
          any(e["action"] == "delete" for e in cl2.log),
          str([e["action"] for e in cl2.log]))
    reset_db()


# ══════════════════════════════════════════ ۷) پنل آمار و راستی‌آزمایی
def test_stats_panel():
    section("📊 پنل آمار کامل + 🔗 راستی‌آزمایی")
    from mother import bot as mb

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")

    # دادهٔ نمونه
    db.track_user(CHILD_TOKEN, USER, "علی", None)
    db.track_user(CHILD_TOKEN, 778, "مریم", None)
    db.block_user(CHILD_TOKEN, 778, OWNER)
    db.set_user_meta(CHILD_TOKEN, USER, age=20, gender="m")
    db.set_user_meta(CHILD_TOKEN, 778, age=30, gender="f")
    db.set_setting(CHILD_TOKEN, "demo_ask", "1")   # برای نمایش بخش دموگرافیک
    bid = db.add_button(CHILD_TOKEN, "فایل", "text", "متن")
    db.bump_views(CHILD_TOKEN, bid)
    db.set_vote(CHILD_TOKEN, bid, USER, 1)
    db.set_task_verified(CHILD_TOKEN, USER)   # API جدید وظیفه (تأیید + پنجره ۲ دقیقه)
    manager_row = db.get_bot(CHILD_TOKEN)

    cq = FakeCallbackQuery(mcl, owner, f"stat:{tid}", FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    edit = mcl.last("edit")
    txt = edit["text"] if edit else ""
    for fragment in (
        "آمار ربات", "کاربران", "مسدود", "هفته", "دموگرافیک",
        "میانگین سنی", "مرد", "زن", "فایل‌ها", "بازدید",
        "لایک", "قابلیت‌ها", "آیدی", "مالک",
        "حذف خودکار", "پسورد فایل‌ها", "وظیفه اجباری",
        "تأیید", "فایل رندوم", "جستجوی فایل",
    ):
        check(f"پنل آمار شامل «{fragment}»", fragment in txt)
    check("وضعیت ربات نمایش داده می‌شود",
          ("روشن" in txt) or ("خاموش" in txt))

    # راستی‌آزمایی روی دادهٔ سالم
    mcl.clear()
    cq = FakeCallbackQuery(mcl, owner, f"statchk:{tid}",
                           FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    report = " ".join(mcl.sent_texts(OWNER))
    check("راستی‌آزمایی اجرا شد", "راستی‌آزمایی" in report)
    check("داده‌های سالم تأیید می‌شوند", "سالم" in report, report[:300])

    # دادهٔ خراب → گزارش ناسازگاری
    db._q("UPDATE bot_users SET blocked=9 WHERE user_id=778 AND token=?",
          (CHILD_TOKEN,))
    mcl.clear()
    cq = FakeCallbackQuery(mcl, owner, f"statchk:{tid}",
                           FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    report = " ".join(mcl.sent_texts(OWNER))
    check("ناسازگاری گزارش می‌شود", "ناسازگاری" in report, report[:300])
    reset_db()


def test_stats_ranked_lists():
    section("لیست‌های مرتب فایل‌ها در آمار")
    from mother.panels import statlist_view

    reset_db()
    b1 = db.add_button(CHILD_TOKEN, "قدیمی", "text", "متن")
    b2 = db.add_button(CHILD_TOKEN, "جدید", "text", "متن")
    db.bump_views(CHILD_TOKEN, b1)
    db.bump_views(CHILD_TOKEN, b1)
    db.set_vote(CHILD_TOKEN, b1, USER, 1)

    tid = CHILD_TOKEN.split(":")[0]
    newest = statlist_view(CHILD_TOKEN, tid, "newest")[0]
    check("جدیدترین اول است", newest.index("جدید") < newest.index("قدیمی"))
    views = statlist_view(CHILD_TOKEN, tid, "views")[0]
    check("پربازدیدترین اول است", views.index("قدیمی") < views.index("جدید"))
    likes = statlist_view(CHILD_TOKEN, tid, "likes")[0]
    check("محبوب‌ترین اول است", likes.index("قدیمی") < likes.index("جدید"))
    reset_db()


# ══════════════════════════════════════════ ۸) پنل قابلیت‌ها
def test_features_panel():
    section("⚙️ پنل قابلیت‌ها")
    from mother import bot as mb

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")

    def cb(data):
        return FakeCallbackQuery(mcl, owner, data, FakeMessage(mcl, owner, "x"))

    compat.run(dispatch(mb.app, mcl, cb(f"feat:{tid}"), kind="callback"))
    edit = mcl.last("edit")
    txt = edit["text"] if edit else ""
    for fragment in ("حذف خودکار", "پسورد فایل‌ها", "فایل رندوم",
                     "فایل با سرچ", "سن و جنسیت", "لایک/دیسلایک"):
        check(f"پنل قابلیت‌ها شامل «{fragment}»", fragment in txt)

    # کلیدها واقعاً تغییر می‌کنند
    compat.run(dispatch(mb.app, mcl, cb(f"rndon:{tid}"), kind="callback"))
    check("رندوم روشن شد", db.get_setting(CHILD_TOKEN, "rnd_enabled") == "1")
    compat.run(dispatch(mb.app, mcl, cb(f"srchon:{tid}"), kind="callback"))
    check("سرچ روشن شد", db.get_setting(CHILD_TOKEN, "search_enabled") == "1")
    compat.run(dispatch(mb.app, mcl, cb(f"demon:{tid}"), kind="callback"))
    check("دموگرافیک روشن شد", db.get_setting(CHILD_TOKEN, "demo_ask") == "1")
    compat.run(dispatch(mb.app, mcl, cb(f"voteon:{tid}"), kind="callback"))
    check("لایک/دیسلایک خاموش شد",
          db.get_setting(CHILD_TOKEN, "votes_enabled") == "0")

    # حذف خودکار با عدد فارسی
    compat.run(dispatch(mb.app, mcl, cb(f"autodel:{tid}"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "۶۰")))
    check("حذف خودکار ۶۰ ثانیه شد", db.get_setting(CHILD_TOKEN, "autodel") == "60")

    # پسورد تنظیم و حذف
    compat.run(dispatch(mb.app, mcl, cb(f"fpass:{tid}"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "سری۱۲۳")))
    check("پسورد فعال شد", db.get_setting(CHILD_TOKEN, "file_pass") == "سری۱۲۳")
    compat.run(dispatch(mb.app, mcl, cb(f"fpass:{tid}"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "حذف")))
    check("پسورد حذف شد", db.get_setting(CHILD_TOKEN, "file_pass") == "")
    reset_db()


# ══════════════════════════════════════════ ۹) fallback پشتیبانی
def test_support_fallback():
    section("📨 fallback تیکت پشتیبانی به ربات مادر")
    from tests.harness import FakeCallbackQuery  # noqa: F401

    reset_db()
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_fb")
    user = FakeUser(USER, "علی", "ali")

    class FailingClient(FakeClient):
        """send_message به مالک همیشه fail می‌شود (مالک ربات فرزند را استارت نکرده)."""
        async def send_message(self, chat_id, text, **kw):
            if chat_id == OWNER:
                from pyrogram.errors import RPCError
                raise RPCError("FORBIDDEN")
            return await super().send_message(chat_id, text, **kw)

    cl = FailingClient(bot_id=222222222)
    mcl = FakeClient(bot_id=111111111, username="mother_bot")
    runtime.set_mother_client(mcl)
    try:
        compat.run(dispatch(app, cl, FakeMessage(cl, user, runtime.SUPPORT_BTN)))
        check("ورود به حالت پشتیبانی", (CHILD_TOKEN, USER) in runtime._support_mode)

        cl.clear(); mcl.clear()
        compat.run(dispatch(app, cl, FakeMessage(cl, user, "سلام مشکل دارم")))
        check("تیکت از مسیر مادر به مالک رسید",
              any("پشتیبانی از ربات فرزند" in t for t in mcl.sent_texts(OWNER)))
        check("متن پیام کاربر ارسال شد",
              any(e["action"] == "send_message" and e["chat_id"] == OWNER
                  and "سلام مشکل دارم" in str(e.get("text")) for e in mcl.log))
        check("به کاربر تأیید رسید",
              any("ارسال شد" in t for t in cl.sent_texts(USER)))
        check("تیکت در دیتابیس ثبت شد",
              db.fetchone("SELECT 1 FROM tickets WHERE token=?",
                          (CHILD_TOKEN,)) is not None)

        # هر دو مسیر fail → پیام خطای صریح (نه سکوت)
        runtime.set_mother_client(None)
        cl.clear()
        compat.run(dispatch(app, cl, FakeMessage(cl, user, runtime.SUPPORT_BTN)))
        cl.clear()
        compat.run(dispatch(app, cl, FakeMessage(cl, user, "دوباره مشکل")))
        check("خطای تحویل‌نشده صریح اعلام می‌شود",
              any("نرسید" in t for t in cl.sent_texts(USER)))
    finally:
        runtime.set_mother_client(None)
        reset_db()


ALL = [test_votes_and_views, test_views_not_counted_in_preview,
       test_demographics, test_file_password, test_random_file,
       test_file_search, test_autodel, test_stats_panel,
       test_stats_ranked_lists, test_features_panel, test_support_fallback]
