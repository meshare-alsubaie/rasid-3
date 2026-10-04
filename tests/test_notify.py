from datetime import date, datetime, timedelta

import httpx
import pytest
import respx

from rasid.dates import RIYADH
from rasid.notify.outbox import Outbox
from rasid.notify.telegram import DeliveryError, send
from rasid.notify.templates import fmt_date, reminders, render
from rasid.programs import Change, Program

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=RIYADH)


def prog(kind="coop", **fields):
    f = {"opens": {"value": "2026-10-26", "quote": "سيتم فتح بوابة التسجيل يوم الإثنين 26 أكتوبر 2026م"},
         "closes": {"value": "2026-11-02", "quote": "وينتهي يوم الإثنين 2 نوفمبر 2026م"},
         "apply_url": {"value": "https://jobs.aramco.com/myprofile/", "quote": "x"}}
    f.update({k: {"value": v, "quote": f"«{k}»"} for k, v in fields.items()})
    return Program("aramco:student:2026-10", "aramco", "student", kind, "2026-10", T0.isoformat(),
                   T0.isoformat(), ["https://www.aramco.com/ar/x"], f, [], ["gemini-3.5-flash"])


def test_date_shows_both_calendars():
    assert fmt_date("2026-10-26") == "26 أكتوبر 2026 (15 جمادى الأولى 1448هـ)"


def test_new_coop_message_has_entity_dates_link_and_evidence():
    t = render(Change("new", "k"), prog(), "أرامكو السعودية")
    assert "أرامكو السعودية" in t and "تعاوني" in t
    assert "26 أكتوبر 2026" in t and "2 نوفمبر 2026" in t
    assert "https://jobs.aramco.com/myprofile/" in t
    assert "سيتم فتح بوابة التسجيل" in t  # الدليل المقتبس


def test_university_message_has_university_check_note():
    t = render(Change("new", "k"), prog(kind="university"), "أرامكو")
    assert "تأكّد من جامعتك هل يُحتسب تعاونياً" in t


def test_hint_message_says_unconfirmed():
    t = render(Change("hint", "k"), prog(kind="hint"), "سدايا")
    assert "تلميح غير مؤكّد" in t


def test_uncertain_program_says_so():
    p = prog()
    p.uncertain = True
    assert "غير مؤكّد" in render(Change("new", "k"), p, "أرامكو")


def test_fulltime_warning():
    t = render(Change("new", "k"), prog(no_courses_allowed=True), "أرامكو")
    assert "🔴" in t and "التفرّغ" in t


def test_update_message_has_detail():
    t = render(Change("important_update", "k", "تغيّر closes: من 2026-11-02 إلى 2026-11-09"), prog(), "أرامكو")
    assert "تحديث" in t and "2026-11-09" in t


def test_no_latin_template_words_leak():
    t = render(Change("new", "k"), prog(), "أرامكو")
    assert "None" not in t and "closes" not in t


def test_reminders_three_days_and_one_day_once_each():
    p = prog()
    r3 = reminders([p], date(2026, 10, 30), {"aramco": "أرامكو"})
    r1 = reminders([p], date(2026, 11, 1), {"aramco": "أرامكو"})
    assert [i for i, _ in r3] == ["rem3:aramco:student:2026-10"]
    assert [i for i, _ in r1] == ["rem1:aramco:student:2026-10"]
    assert reminders([p], date(2026, 10, 27), {"aramco": "أرامكو"}) == []
    assert reminders([p], date(2026, 11, 3), {"aramco": "أرامكو"}) == []


# ---------- telegram ----------

API = "https://api.telegram.org/botTOKEN/sendMessage"


@respx.mock
def test_send_returns_receipt():
    respx.post(API).mock(return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 42}}))
    assert send("TOKEN", "-1", "مرحبا", httpx.Client()).message_id == 42


@respx.mock
def test_send_failure_raises_arabic_error():
    respx.post(API).mock(return_value=httpx.Response(400, json={"ok": False, "description": "chat not found"}))
    with pytest.raises(DeliveryError) as e:
        send("TOKEN", "-1", "مرحبا", httpx.Client())
    assert "تيليجرام" in str(e.value) and "chat not found" in str(e.value)


@respx.mock
def test_network_error_becomes_delivery_error():
    respx.post(API).mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(DeliveryError):
        send("TOKEN", "-1", "مرحبا", httpx.Client())


# ---------- outbox ----------

class FakeSender:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, chat, text):
        if self.fail:
            raise DeliveryError("[تيليجرام] فشل")
        self.sent.append((chat, text))
        return len(self.sent)


def test_quiet_hours_hold_then_send_at_seven():
    ob, s = Outbox(), FakeSender()
    night = datetime(2026, 10, 27, 2, 0, tzinfo=RIYADH)
    ob.enqueue("m1", "group", "نص", night)
    assert ob.flush(night, s) == 0 and s.sent == []
    assert ob.flush(night.replace(hour=7), s) == 1


def test_marked_sent_only_with_receipt_and_kept_on_failure():
    ob = Outbox()
    ob.enqueue("m1", "group", "نص", T0)
    assert ob.flush(T0, FakeSender(fail=True)) == 0
    assert "m1" in ob.pending and "m1" not in ob.receipts and ob.pending["m1"]["errors"]
    assert ob.flush(T0 + timedelta(minutes=5), FakeSender()) == 1
    assert ob.receipts["m1"] == 1 and "m1" not in ob.pending


def test_same_message_id_never_sent_twice():
    ob, s = Outbox(), FakeSender()
    ob.enqueue("m1", "group", "نص", T0)
    ob.flush(T0, s)
    ob.enqueue("m1", "group", "نص", T0)
    ob.flush(T0, s)
    assert len(s.sent) == 1


def test_owner_alerts_ignore_quiet_hours():
    ob, s = Outbox(), FakeSender()
    night = datetime(2026, 10, 27, 2, 0, tzinfo=RIYADH)
    ob.enqueue("o1", "owner", "حساب محظور", night, urgent=True)
    assert ob.flush(night, s) == 1


def test_round_trip():
    ob = Outbox()
    ob.enqueue("m1", "group", "نص", T0)
    assert Outbox.from_dict(ob.to_dict()).to_dict() == ob.to_dict()


def test_days_in_correct_arabic():
    from rasid.notify.templates import days_ar
    assert days_ar(1) == "يوم واحد" and days_ar(2) == "يومين"
    assert days_ar(3) == "3 أيام" and days_ar(10) == "10 أيام" and days_ar(11) == "11 يوماً"


def test_countdown_before_opening():
    t = render(Change("new", "k"), prog(), "أرامكو", today=date(2026, 10, 25))
    assert "يفتح بعد يوم واحد" in t and "باقي 8 أيام على الإغلاق" in t


def test_countdown_while_open():
    t = render(Change("new", "k"), prog(), "أرامكو", today=date(2026, 10, 28))
    assert "مفتوح الآن" in t and "باقي 5 أيام على الإغلاق" in t


def test_countdown_last_day_and_closed():
    assert "آخر يوم للتقديم اليوم" in render(Change("new", "k"), prog(), "أرامكو", today=date(2026, 11, 2))
    assert "أقفل التقديم" in render(Change("important_update", "k", ""), prog(), "أرامكو", today=date(2026, 11, 5))


def test_launch_message_lists_open_and_upcoming_only():
    from rasid.notify.templates import launch_message
    old = prog()
    old.fields["closes"] = {"value": "2025-07-12", "quote": "q"}
    old.key = "old"
    t = launch_message([prog(), old], {"aramco": "أرامكو السعودية"}, date(2026, 10, 20))
    assert "أرامكو السعودية" in t and "يفتح بعد 6 أيام" in t
    assert t.count("أرامكو") == 1  # المنتهي لا يظهر
    assert "راصد" in t


def test_launch_message_when_nothing_open():
    from rasid.notify.templates import launch_message
    t = launch_message([], {}, date(2026, 10, 20))
    assert "ما فيه شي مفتوح" in t
