"""اختبارات إصلاحات الفحص الثالث (٢٢ أكتوبر): رسائل الصباح المنتظرة، الفتح القديم بلا إغلاق، تذكير الموعد الممدّد."""
from datetime import date, datetime, timedelta

from rasid.classify.schema import Field, Verdict
from rasid.notify.templates import reminders, render, update_detail
from rasid.programs import Change, Program, Programs, program_status
from rasid.run import State, _push_text, run_once
from tests.test_audit2_fixes import AGG, FEED, GOV, _prog
from tests.test_run import RIYADH, T0, World

DAWN = datetime(2026, 10, 26, 4, 0, tzinfo=RIYADH)  # ساعات الهدوء: الرسائل تنتظر الساعة ٧


def _opens_only(opens, accepting_at=None):
    p = Program("x:الدوري:student:2026-09", "x:الدوري", "student", "coop", "2026-09", "t", "t",
                ["https://agg.example.com/post-9"], {"opens": {"value": opens, "quote": "q"}}, [], ["m"])
    if accepting_at:
        p.fields["accepting_now"] = {"value": True, "quote": "q", "at": accepting_at}
    return p


# ---------- ١: الفتح بلا إغلاق لا يبقى «مفتوح» للأبد ----------

def test_opens_only_program_is_open_for_three_weeks_then_a_program_page():
    p = _opens_only("2026-10-01")
    assert program_status(p, date(2026, 10, 20)) == "open"
    assert program_status(p, date(2026, 10, 23)) == "listed"
    p.fields["accepting_now"] = {"value": True, "quote": "q", "at": "2026-10-20T10:00"}
    assert program_status(p, date(2026, 10, 23)) == "open"  # المصدر قال حديثاً إن التسجيل مفتوح


def test_safety_net_does_not_announce_an_old_opens_only_post():
    st = State()
    p = _opens_only("2026-09-14")
    st.programs.items[p.key] = p
    w = World()
    run_once(T0, [], st, w.deps(), aggregators=[FEED])
    assert not any(c == "group" and "الدوري" in t for c, t in w.sent) and not p.alerted


# ---------- ٢: الرسائل المنتظرة تُكتب من جديد، والتذكير لا يتكرر مع التنبيه ----------

def test_waiting_alert_is_rewritten_and_waiting_reminder_dropped():
    st = State()
    p = _prog("2026-10-28", ["https://agg.example.com/post-1", "https://ncgr.gov.sa/coop"])
    p.alerted = True
    st.programs.items[p.key] = p
    old = render(Change("new", p.key), p, "المركز", DAWN.date())  # كُتب قبل ترتيب المصادر
    st.outbox.enqueue(f"new:{p.key}:e3b0c44298fc1c14", "group", old, DAWN)
    st.outbox.enqueue(f"rem3:{p.key}", "group", "⏰ باقي 2 أيام", DAWN)  # معرّف قديم بلا تاريخ
    w = World()
    run_once(DAWN, [GOV], st, w.deps(), aggregators=[FEED])
    texts = [m["text"] for m in st.outbox.pending.values()]
    assert any("المصدر: https://ncgr.gov.sa/coop" in t for t in texts)
    assert not any(t.startswith("⏰") for t in texts) and not w.sent


def test_waiting_dates_alert_is_dropped_when_program_is_no_longer_open():
    st = State()
    p = _opens_only("2026-09-14")
    st.programs.items[p.key] = p
    st.outbox.enqueue(f"dates:{p.key}:e3b0c44298fc1c14", "group", "📅 أعلنت المواعيد: الدوري", DAWN)
    st.outbox.enqueue(f"push:dates:{p.key}:e3b0c44298fc1c14", "push", "{}", DAWN)
    st.meta["new_since_digest"] = [p.key]
    run_once(DAWN, [], st, World().deps(), aggregators=[FEED])
    assert not st.outbox.pending and st.meta["new_since_digest"] == []


# ---------- ٣: الموعد الممدّد يأتي معه تذكير ----------

def test_extended_deadline_gets_its_own_reminder_but_old_one_is_not_repeated():
    (first, _), = reminders([_prog("2026-10-28")], date(2026, 10, 26), {"ncgr": "المركز"})
    (later, _), = reminders([_prog("2026-11-04")], date(2026, 11, 2), {"ncgr": "المركز"})
    assert first != later and first.endswith(":2026-10-28")
    st, w = State(), World()
    p = _prog("2026-10-28")
    p.alerted = True
    st.programs.items[p.key] = p
    st.outbox.receipts[f"rem3:{p.key}"] = 7  # أُرسل قبل إضافة التاريخ للمعرّف
    run_once(T0, [], st, w.deps(), aggregators=[FEED])
    assert not any("⏰" in t for _, t in w.sent)


# ---------- ٤: دورة جديدة بتاريخ إغلاق فقط ----------

def test_closes_only_announcement_after_a_closed_cycle_is_a_new_program():
    ps, now = Programs(), datetime(2026, 10, 22, 10, 0, tzinfo=RIYADH)
    old = Verdict("coop", "m", {"opens": Field(date(2026, 8, 1), "q"), "closes": Field(date(2026, 8, 20), "q")})
    p1, _ = ps.merge("ncgr", old, "https://ncgr.gov.sa/a", now - timedelta(days=60))
    new = Verdict("coop", "m", {"closes": Field(date(2026, 10, 31), "q")})
    p2, change = ps.merge("ncgr", new, "https://ncgr.gov.sa/b", now)
    assert p2.key != p1.key and change.kind == "new" and "opens" not in p2.fields


# ---------- ٥: نص «تحديث مهم» ----------

def test_important_update_text_is_arabic_with_readable_dates():
    detail = "تغيّر closes: من 2026-10-24 إلى 2026-11-01"
    assert update_detail(detail).startswith("تغيّر تاريخ الإغلاق: من 24 أكتوبر 2026 (")
    p = _prog("2026-10-01")  # أقفل، فلا عدّ تنازلي في تنبيه الجوال
    body = _push_text(Change("important_update", p.key, detail), p, "المركز", 3, date(2026, 10, 22))
    assert "closes" not in body and "2026-10-24" not in body
    assert "closes" not in render(Change("important_update", p.key, detail), p, "المركز", date(2026, 10, 22), AGG)
