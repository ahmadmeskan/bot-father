"""تست قابلیت‌های پیام پایانی، وظیفه اجباری و مدیریت کاربران."""
from __future__ import annotations

import time

from tests.harness import (  # noqa: F401
    ADMIN,
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
    reset_db,
    runtime,
    section,
)


def test_footer():
    section("پیام پایانی (بعد از هر دکمه)")
    from mother import bot as mb

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    db.add_button(CHILD_TOKEN, "راهنما", "text", "متن راهنما")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_footer")
    user = FakeUser(USER, "علی")

    # بدون پیام پایانی
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "راهنما")))
    check("بدون تنظیم، پیام پایانی فرستاده نمی‌شود",
          len([e for e in cl.log if e["action"] == "send_message"]) == 1)

    # تنظیم از ربات مادر
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")
    cq = FakeCallbackQuery(mcl, owner, f"ftr:{tid}", FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    panel = mcl.last("edit") or mcl.last("send_message")
    check("پنل پیام پایانی باز می‌شود", "پیام پایانی" in panel["text"])

    mcl.clear()
    cq = FakeCallbackQuery(mcl, owner, f"ftredit:{tid}", FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    check("حالت ویرایش باز می‌شود",
          mb.STATE.get(OWNER, {}).get("step") == "ftr_text")

    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "{name} جان، کانال ما: @ch")))
    check("پیام پایانی ذخیره شد",
          db.get_setting(CHILD_TOKEN, "footer_text") == "{name} جان، کانال ما: @ch")
    check("وضعیت پاک شد", OWNER not in mb.STATE)

    # ارسال در ربات فرزند
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "راهنما")))
    texts = cl.sent_texts()
    check("پیام پایانی بعد از محتوا می‌آید", len(texts) == 2, str(texts))
    check("ترتیب درست است: اول محتوا بعد پایانی",
          texts[0] == "متن راهنما" and "کانال ما" in texts[1])
    check("{name} در پیام پایانی جای‌گذاری می‌شود", "علی جان" in texts[1])

    # پیام پایانی نباید بعد از پیام‌های غیر دکمه بیاید
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "یه چیز بی‌ربط")))
    check("بعد از پیام بی‌ربط، پیام پایانی نمی‌آید",
          not any("کانال ما" in t for t in cl.sent_texts()))

    # حذف
    mcl.clear()
    cq = FakeCallbackQuery(mcl, owner, f"ftrdel:{tid}", FakeMessage(mcl, owner, "x"))
    compat.run(dispatch(mb.app, mcl, cq, kind="callback"))
    check("حذف پیام پایانی", db.get_setting(CHILD_TOKEN, "footer_text") == "")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "راهنما")))
    check("پس از حذف دیگر ارسال نمی‌شود", len(cl.sent_texts()) == 1)





# ════════════════════════════════════════════ وظیفه اجباری (تأیید + ۲ دقیقه)
def test_forced_task():
    """وظیفه‌ی اجباری مدل جدید: چک عضویت + تأیید با دکمه‌ی «عضو شدم»
    و پنجره‌ی اعتبار ۲ دقیقه‌ای."""
    from child import tasks
    from mother import bot as mb

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    db.add_button(CHILD_TOKEN, "فایل", "text", "محتوای ویژه")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_task")
    user = FakeUser(USER, "علی")
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")

    def cb(data):
        return FakeCallbackQuery(mcl, owner, data, FakeMessage(mcl, owner, "x"))

    # ── تنظیم از پنل ربات مادر ──
    compat.run(dispatch(mb.app, mcl, cb(f"tskch:{tid}"), kind="callback"))
    check("حالت تنظیم کانال", mb.STATE.get(OWNER, {}).get("step") == "tsk_channel")
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "@taskchannel")))
    check("کانال ذخیره شد",
          db.get_setting(CHILD_TOKEN, "task_channel") == "@taskchannel")

    # فعال‌سازی
    compat.run(dispatch(mb.app, mcl, cb(f"tskon:{tid}"), kind="callback"))
    check("وظیفه فعال شد", db.get_setting(CHILD_TOKEN, "task_enabled") == "1")
    check("وظیفه فعال تشخیص داده می‌شود", tasks.is_active(CHILD_TOKEN))

    # ── رفتار سمت کاربر: غیرعضو → پیام وظیفه + دکمه «عضو شدم» ──
    cl = FakeClient(bot_id=222222222)   # memberships خالی → غیرعضو
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    txts = cl.sent_texts(USER)
    check("پیام وظیفه نمایش داده می‌شود", "وظیفه اجباری" in " ".join(txts),
          str(txts)[:300])
    check("کانال در پیام هست", any("@taskchannel" in t for t in txts))
    check("محتوا هنوز ارسال نشده",
          not any("محتوای ویژه" in t for t in txts))
    kb = None
    for e in reversed(cl.log):
        if e["action"] == "send_message" and "وظیفه اجباری" in e["text"]:
            kb = e["reply_markup"]
            break
    labels = [b.text for row in kb.inline_keyboard for b in row] if kb else []
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row] if kb else []
    check("دکمه‌ی «عضو شدم» هست", any("عضو شدم" in l for l in labels), str(labels))
    check("کال‌بک taskjoin هست", "taskjoin" in cbs, str(cbs))
    check("دکمه‌ی ورود به کانال هست", any("کانال" in l for l in labels))

    # ── «عضو شدم» بدون عضویت واقعی → خطای صریح ──
    cl.clear()
    cq = FakeCallbackQuery(cl, user, "taskjoin", FakeMessage(cl, user, "پیام وظیفه"))
    compat.run(dispatch(app, cl, cq, kind="callback"))
    ans = cl.last("answer")
    check("بدون عضویت → «هنوز عضو نشدید»",
          ans and "عضو کانال نشدید" in ans["text"], str(ans))
    check("محتوا هنوز داده نمی‌شود",
          not any("محتوای ویژه" in t for t in cl.sent_texts(USER)))

    # ── «عضو شدم» بعد از عضویت واقعی → تأیید + ارسال محتوای در انتظار ──
    cl2 = FakeClient(bot_id=222222222, memberships={"@taskchannel": {USER}})
    cq = FakeCallbackQuery(cl2, user, "taskjoin",
                           FakeMessage(cl2, user, "پیام وظیفه"))
    compat.run(dispatch(app, cl2, cq, kind="callback"))
    txts = cl2.sent_texts(USER)
    check("بعد از عضویت، محتوای درخواستی ارسال می‌شود",
          any("محتوای ویژه" in t for t in txts), str(txts)[:200])
    check("زمان تأیید ثبت شد",
          db.task_verified_at(CHILD_TOKEN, USER) > 0)
    check("شمارنده تأیید +۱ شد", db.task_completions(CHILD_TOKEN) == 1)
    check("حالت در انتظار پاک شد",
          (CHILD_TOKEN, USER) not in runtime._task_pending)

    # ── پنجره‌ی ۲ دقیقه: دکمه‌ی دیگر → بدون چک، مستقیم محتوا ──
    db.add_button(CHILD_TOKEN, "دومی", "text", "محتوای دوم")
    cl3 = FakeClient(bot_id=222222222)   # بدون memberships → چک می‌کرد رد می‌شد
    compat.run(dispatch(app, cl3, FakeMessage(cl, user, "دومی")))
    txts = cl3.sent_texts(USER)
    check("در پنجره‌ی ۲ دقیقه، بدون چک عضویت محتوا می‌آید",
          any("محتوای دوم" in t for t in txts), str(txts)[:200])
    check("پیام وظیفه دوباره نیامده",
          not any("وظیفه اجباری" in t for t in txts))

    # ── پایان پنجره → دوباره وظیفه ──
    db._q("DELETE FROM user_state WHERE token=? AND key=?",
          (CHILD_TOKEN, db.TASK_VERIFY_KEY))
    tasks.mark_verified(CHILD_TOKEN, USER)
    old = db.now_ms() - 3 * 60 * 1000   # ۳ دقیقه پیش
    db.user_set_state(CHILD_TOKEN, USER, db.TASK_VERIFY_KEY, str(old))
    check("پنجره تمام‌شده تشخیص داده می‌شود",
          not tasks.verified_recently(CHILD_TOKEN, USER))
    cl4 = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl4, FakeMessage(cl4, user, "دومی")))
    check("بعد از پایان پنجره، دوباره پیام وظیفه می‌آید",
          any("وظیفه اجباری" in t for t in cl4.sent_texts(USER)))

    # ── عضو بودن از همان اول (بدون پیام وظیفه) → مستقیم محتوا ──
    db._q("DELETE FROM user_state WHERE token=? AND key=?",
          (CHILD_TOKEN, db.TASK_VERIFY_KEY))
    cl5 = FakeClient(bot_id=222222222, memberships={"@taskchannel": {USER}})
    compat.run(dispatch(app, cl5, FakeMessage(cl5, user, "فایل")))
    txts = cl5.sent_texts(USER)
    check("عضوِ کانال بدون پیام وظیفه محتوا می‌گیرد",
          any("محتوای ویژه" in t for t in txts)
          and not any("وظیفه اجباری" in t for t in txts))
    check("تأیید عضوِ از ابتدا ثبت می‌شود",
          db.task_verified_at(CHILD_TOKEN, USER) > 0)

    # ── صفر کردن تأیید همه ──
    compat.run(dispatch(mb.app, mcl, cb(f"tskreset:{tid}"), kind="callback"))
    check("صفر کردن تأیید همه",
          db.task_verified_at(CHILD_TOKEN, USER) == 0
          and db.task_completions(CHILD_TOKEN) == 0)

    # ── متن سفارشی وظیفه ──
    compat.run(dispatch(mb.app, mcl, cb(f"tsktxt:{tid}"), kind="callback"))
    compat.run(dispatch(mb.app, mcl, FakeMessage(
        mcl, owner, "{name} عزیز: {channel}")))
    rendered = tasks.render_text(CHILD_TOKEN, user)
    check("متن سفارشی با متغیرها رندر می‌شود",
          "علی عزیز: @taskchannel" in rendered, rendered)

    # ── حذف وظیفه ──
    compat.run(dispatch(mb.app, mcl, cb(f"tskdel:{tid}"), kind="callback"))
    check("حذف وظیفه همه‌چیز را پاک می‌کند",
          not tasks.is_active(CHILD_TOKEN)
          and db.get_setting(CHILD_TOKEN, "task_channel") == "")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    check("پس از حذف وظیفه، ربات عادی کار می‌کند",
          any("محتوای ویژه" in t for t in cl.sent_texts(USER)))


# ════════════════════════════════════════════ زمان‌بندی وظیفه
def test_task_timing():
    """پنجره‌ی ۲ دقیقه‌ای: verified_recently/seconds_left/mark_verified."""
    from child import tasks

    reset_db()
    db.set_setting(CHILD_TOKEN, "task_channel", "@taskchannel")
    db.set_setting(CHILD_TOKEN, "task_enabled", "1")

    check("کاربر تازه → پنجره بسته است",
          not tasks.verified_recently(CHILD_TOKEN, USER))

    tasks.mark_verified(CHILD_TOKEN, USER)
    check("بعد از تأیید → پنجره باز است",
          tasks.verified_recently(CHILD_TOKEN, USER))
    check("ثانیه‌های باقی‌مانده درست است (≈۱۲۰)",
          110 <= tasks.seconds_left(CHILD_TOKEN, USER) <= 120)
    check("شمارنده ثبت شد", db.task_completions(CHILD_TOKEN) == 1)

    # غیرفعال‌کردن وظیفه هیچ تأثیری روی پنجره ندارد (ولی دروازه خاموش است)
    db.set_setting(CHILD_TOKEN, "task_enabled", "0")
    check("غیرفعال → is_active خاموش", not tasks.is_active(CHILD_TOKEN))
    check("پنجره همچنان باز است (فقط دروازه خاموش شده)",
          tasks.verified_recently(CHILD_TOKEN, USER))


# ════════════════════════════════════════════ ترتیب دروازه‌ها
def test_gate_order():
    section("ترتیب دروازه‌های دسترسی")
    reset_db()
    db.add_button(CHILD_TOKEN, "فایل", "text", "محتوای ویژه")
    db.add_channel(CHILD_TOKEN, "@ch1")
    db.set_setting(CHILD_TOKEN, "task_enabled", "1")
    db.set_setting(CHILD_TOKEN, "task_channel", "@taskch")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_gate")
    user = FakeUser(USER, "علی")
    db.track_user(CHILD_TOKEN, USER, "علی", None)

    # مسدود + غیرعضو → فقط پیام مسدودی
    db.block_user(CHILD_TOKEN, USER, OWNER)
    cl = FakeClient(bot_id=222222222, memberships={"@ch1": set()})
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    txt = " ".join(cl.sent_texts(USER))
    check("اولویت با مسدودی است", "مسدود" in txt)
    check("پیام عضویت نمایش داده نمی‌شود", "@ch1" not in txt)

    # رفع مسدودی → پیام عضویت
    db.unblock_user(CHILD_TOKEN, USER)
    cl.clear()
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    txt = " ".join(cl.sent_texts(USER))
    check("سپس نوبت عضویت اجباری است", "@ch1" in txt)
    check("پیام وظیفه هنوز نمایش داده نمی‌شود", "وظیفه اجباری" not in txt)

    # عضو کانال‌های اجباری + عضو کانال وظیفه → محتوا مستقیم
    cl = FakeClient(bot_id=222222222,
                    memberships={"@ch1": {USER}, "@taskch": {USER}})
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, user, "فایل")))
    txts = cl.sent_texts(USER)
    check("با تمام‌شدن شرط‌ها، محتوا ارسال می‌شود",
          "محتوای ویژه" in " ".join(txts))
    check("پیام وظیفه نیامد (عضو بود)", "وظیفه اجباری" not in " ".join(txts))

    # عضو کانال‌های اجباری ولی غیرعضو کانال وظیفه → پیام وظیفه، بدون محتوا
    db._q("DELETE FROM user_state WHERE token=? AND key=?",
          (CHILD_TOKEN, db.TASK_VERIFY_KEY))
    cl2 = FakeClient(bot_id=222222222, memberships={"@ch1": {USER}})
    runtime._member_cache.clear()
    compat.run(dispatch(app, cl2, FakeMessage(cl2, user, "فایل")))
    txts = cl2.sent_texts(USER)
    check("بعد از عضویت اجباری، نوبت وظیفه است",
          any("وظیفه اجباری" in t for t in txts))
    check("محتوا هنوز ارسال نمی‌شود",
          not any("محتوای ویژه" in t for t in txts))
    # تأیید وظیفه → محتوا
    cl3 = FakeClient(bot_id=222222222,
                     memberships={"@ch1": {USER}, "@taskch": {USER}})
    cq = FakeCallbackQuery(cl3, user, "taskjoin",
                           FakeMessage(cl3, user, "پیام وظیفه"))
    compat.run(dispatch(app, cl3, cq, kind="callback"))
    check("بعد از تأیید وظیفه، محتوا می‌آید",
          any("محتوای ویژه" in t for t in cl3.sent_texts(USER)))



def test_users_admin():
    section("مسدودسازی و جستجوی کاربران")
    from mother import bot as mb
    from mother import panels

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    db.add_button(CHILD_TOKEN, "فایل", "text", "محتوای ویژه")
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_users")
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")

    def cb(data):
        return FakeCallbackQuery(mcl, owner, data, FakeMessage(mcl, owner, "x"))

    # چند کاربر
    db.track_user(CHILD_TOKEN, 1001, "علی رضایی", "alireza")
    db.track_user(CHILD_TOKEN, 1002, "مریم احمدی", "maryam_a")
    db.track_user(CHILD_TOKEN, 1003, "علی محمدی", None)

    # جستجو
    check("جستجو با آیدی عددی",
          [r["user_id"] for r in db.search_users(CHILD_TOKEN, "1002")] == [1002])
    check("جستجو با یوزرنیم",
          [r["user_id"] for r in db.search_users(CHILD_TOKEN, "@alireza")] == [1001])
    check("جستجو با یوزرنیم بدون @",
          [r["user_id"] for r in db.search_users(CHILD_TOKEN, "maryam")] == [1002])
    names = {r["user_id"] for r in db.search_users(CHILD_TOKEN, "علی")}
    check("جستجو با نام (چند نتیجه)", names == {1001, 1003}, str(names))
    check("جستجوی بی‌نتیجه", db.search_users(CHILD_TOKEN, "نیستم") == [])
    check("جستجوی خالی امن است", db.search_users(CHILD_TOKEN, "   ") == [])

    # جستجو از پنل
    compat.run(dispatch(mb.app, mcl, cb(f"usrsrch:{tid}"), kind="callback"))
    check("حالت جستجو باز می‌شود",
          mb.STATE.get(OWNER, {}).get("step") == "usr_search")
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "1001")))
    card = mcl.last("send_message")
    check("پرونده کاربر نمایش داده می‌شود", "علی رضایی" in card["text"])
    check("تاریخ عضویت در پرونده هست", "عضویت در ربات" in card["text"])
    labels = [b.text for r in card["reply_markup"].inline_keyboard for b in r]
    check("دکمه مسدود کردن هست", any("مسدود کردن" in l for l in labels))

    # چند نتیجه
    mb.STATE[OWNER] = {"step": "usr_search", "token": CHILD_TOKEN, "tid": tid}
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "علی")))
    res = mcl.last("send_message")
    check("چند نتیجه به‌صورت لیست می‌آید", "2 نتیجه" in res["text"], res["text"][:40])

    # مسدود کردن
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"ublk:{tid}:1001"), kind="callback"))
    check("کاربر مسدود شد", db.is_blocked(CHILD_TOKEN, 1001))
    row = db.get_bot_user(CHILD_TOKEN, 1001)
    check("تاریخ مسدودی ثبت شد", row["blocked_at"] is not None)
    check("مسدودکننده ثبت شد", row["blocked_by"] == OWNER)
    check("شمارش مسدودشده‌ها", db.blocked_count(CHILD_TOKEN) == 1)

    # ربات برای کاربر مسدود کار نمی‌کند
    cl = FakeClient(bot_id=222222222)
    blocked_user = FakeUser(1001, "علی رضایی", "alireza")
    compat.run(dispatch(app, cl, FakeMessage(cl, blocked_user, "فایل")))
    txt = " ".join(cl.sent_texts(1001))
    check("کاربر مسدود محتوا نمی‌گیرد", "محتوای ویژه" not in txt)
    check("پیام مسدودی نمایش داده می‌شود", "مسدود" in txt)

    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, blocked_user, "/start")))
    check("کاربر مسدود حتی /start هم نمی‌تواند",
          "خوش" not in " ".join(cl.sent_texts(1001)))

    # کاربر دیگر عادی کار می‌کند
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(1002, "مریم"), "فایل")))
    check("کاربر عادی تحت تأثیر قرار نمی‌گیرد",
          "محتوای ویژه" in " ".join(cl.sent_texts(1002)))

    # لیست مسدودها
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"usrblk:{tid}"), kind="callback"))
    view = mcl.last("edit") or mcl.last("send_message")
    check("لیست مسدودها نام کاربر را دارد", "علی رضایی" in view["text"])
    check("لیست مسدودها تاریخ دارد", "📅" in view["text"])
    check("لیست مسدودها آیدی دارد", "1001" in view["text"])
    ulabels = [b.text for r in view["reply_markup"].inline_keyboard for b in r]
    check("دکمه رفع مسدودی در لیست هست", any("رفع مسدودی" in l for l in ulabels))

    # آمار کاربران
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"usr:{tid}"), kind="callback"))
    stats = (mcl.last("edit") or mcl.last("send_message"))["text"]
    check("آمار کل کاربران", "کل کاربران" in stats)
    check("آمار مسدودشده‌ها درست است", "<b>1</b>" in stats)

    # رفع مسدودی
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"uunblk:{tid}:1001"), kind="callback"))
    check("رفع مسدودی انجام شد", not db.is_blocked(CHILD_TOKEN, 1001))
    check("تاریخ مسدودی پاک شد",
          db.get_bot_user(CHILD_TOKEN, 1001)["blocked_at"] is None)
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, blocked_user, "فایل")))
    check("پس از رفع مسدودی، ربات کار می‌کند",
          "محتوای ویژه" in " ".join(cl.sent_texts(1001)))

    # مسدود کردن کاربر ناموجود
    check("مسدود کردن کاربر ناموجود امن است",
          db.block_user(CHILD_TOKEN, 999999, OWNER) is False)


def test_texts_panel():
    section("پنل متن‌های ربات")
    from mother import bot as mb
    from mother import panels

    reset_db()
    mb.STATE.clear()
    tid = CHILD_TOKEN.split(":")[0]
    owner = FakeUser(OWNER, "مالک")
    mcl = FakeClient(bot_id=111111111, username="mother_bot")

    def cb(data):
        return FakeCallbackQuery(mcl, owner, data, FakeMessage(mcl, owner, "x"))

    compat.run(dispatch(mb.app, mcl, cb(f"txts:{tid}"), kind="callback"))
    view = mcl.last("edit") or mcl.last("send_message")
    labels = [b.text for r in view["reply_markup"].inline_keyboard for b in r]
    check(f"همه‌ی {len(panels.EDITABLE_TEXTS)} متن در لیست هستند",
          len(labels) == len(panels.EDITABLE_TEXTS) + 1, str(len(labels)))
    check("همه در ابتدا پیش‌فرض‌اند", all("▫️" in l for l in labels[:-1]))

    # ویرایش «پیام راهنمای منو» (اندیس ۵)
    idx = next(i for i, (k, _, _) in enumerate(panels.EDITABLE_TEXTS)
               if k == "menu_hint")
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"txt:{tid}:{idx}"), kind="callback"))
    detail = mcl.last("edit") or mcl.last("send_message")
    check("جزئیات متن نمایش داده می‌شود", "راهنمای منو" in detail["text"])

    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"txtedit:{tid}:{idx}"), kind="callback"))
    check("حالت ویرایش باز می‌شود",
          mb.STATE.get(OWNER, {}).get("step") == "txt_edit")
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "لطفاً از منو انتخاب کنید")))
    check("متن ذخیره شد",
          db.get_setting(CHILD_TOKEN, "menu_hint") == "لطفاً از منو انتخاب کنید")

    # اثر در ربات فرزند
    app = runtime.build_client(CHILD_TOKEN, OWNER, "t_texts")
    cl = FakeClient(bot_id=222222222)
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(USER), "چیز بی‌ربط")))
    check("متن جدید در ربات فرزند اعمال می‌شود",
          any("لطفاً از منو انتخاب کنید" in t for t in cl.sent_texts()))

    # نشانه‌ی سفارشی‌شده
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"txts:{tid}"), kind="callback"))
    labels = [b.text for r in (mcl.last("edit") or mcl.last("send_message"))
              ["reply_markup"].inline_keyboard for b in r]
    check("متن سفارشی با ✏️ علامت می‌خورد",
          any("✏️" in l and "راهنمای منو" in l for l in labels))

    # بازگشت به پیش‌فرض
    mcl.clear()
    compat.run(dispatch(mb.app, mcl, cb(f"txtdel:{tid}:{idx}"), kind="callback"))
    check("بازگشت به پیش‌فرض", db.get_setting(CHILD_TOKEN, "menu_hint") == "")
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(USER), "چیز بی‌ربط")))
    check("پیش‌فرض دوباره اعمال می‌شود",
          any("از دکمه‌های منو" in t for t in cl.sent_texts()))

    # ویرایش پیام مسدودی و اثرش
    bidx = next(i for i, (k, _, _) in enumerate(panels.EDITABLE_TEXTS)
                if k == "blocked_text")
    mb.STATE[OWNER] = {"step": "txt_edit", "token": CHILD_TOKEN, "tid": tid,
                       "key": "blocked_text"}
    compat.run(dispatch(mb.app, mcl, FakeMessage(mcl, owner, "شما بن شدید!")))
    db.track_user(CHILD_TOKEN, 2001, "تست", None)
    db.block_user(CHILD_TOKEN, 2001, OWNER)
    cl.clear()
    compat.run(dispatch(app, cl, FakeMessage(cl, FakeUser(2001, "تست"), "سلام")))
    check("پیام مسدودی سفارشی نمایش داده می‌شود",
          any("شما بن شدید!" in t for t in cl.sent_texts(2001)))





ALL = [test_footer, test_forced_task, test_task_timing, test_users_admin,
       test_texts_panel, test_gate_order]
