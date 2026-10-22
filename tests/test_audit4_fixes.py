"""اختبارات إصلاحات الفحص الرابع (٢٢ أكتوبر): التصحيح بعد إعادة الفحص، نقل التذكير القديم، تقرير المالك."""
from datetime import datetime, timedelta

from rasid.classify.schema import Verdict
from rasid.entities import Aggregator
from rasid.run import Ctx, RunReport, State, _digests, run_once
from tests.test_audit2_fixes import _prog
from tests.test_run import ARAMCO, RIYADH, T0, World, coop

DAWN = datetime(2026, 10, 26, 3, 0, tzinfo=RIYADH)  # ساعات الهدوء


def _recheck_world(first):
    w = World()
    v = first(); v.needs_recheck = True; v.model = "reader"
    w.verdicts["التعاوني"] = v
    return w


# ---------- ١: التصحيح فقط لما وصل القروب ----------

def test_waiting_alert_is_dropped_quietly_when_recheck_disagrees():
    w, st = _recheck_world(coop), State()
    run_once(DAWN, [ARAMCO], st, w.deps())
    assert any(m.startswith("new:") for m in st.outbox.pending)
    w.verdicts["التعاوني"] = Verdict("irrelevant", "confirmer")
    run_once(DAWN + timedelta(hours=2), [ARAMCO], st, w.deps())
    assert not st.programs.items and not st.outbox.pending
    run_once(T0, [ARAMCO], st, w.deps())  # الصباح: لا تنبيه ولا تصحيح
    assert not any("أرامكو" in t for c, t in w.sent if c == "group")


def test_no_correction_for_a_program_the_group_never_saw():
    w, st = _recheck_world(lambda: Verdict("grad_program", "m", {})), State()
    run_once(T0, [ARAMCO], st, w.deps())
    w.verdicts["التعاوني"] = Verdict("irrelevant", "confirmer")
    run_once(T0 + timedelta(hours=2), [ARAMCO], st, w.deps())
    assert not any("تصحيح" in t for _, t in w.sent) and not st.programs.items


def test_same_family_correction_fixes_the_waiting_alert_in_place():
    w = _recheck_world(lambda: Verdict("university", "m", coop().fields))
    st = State()
    run_once(DAWN, [ARAMCO], st, w.deps())
    w.verdicts["التعاوني"] = Verdict("coop", "confirmer", coop().fields)
    run_once(DAWN + timedelta(hours=2), [ARAMCO], st, w.deps())
    (p,) = st.programs.items.values()
    texts = [m["text"] for k, m in st.outbox.pending.items() if k.startswith("new:")]
    assert p.kind == "coop" and texts and "تدريب تعاوني جديد" in texts[0]
    assert not any(k.startswith("fix:") for k in st.outbox.pending)


# ---------- ٢: التذكير القديم يُنقل لمعرّف تاريخه، والتمديد بعده يُذكَّر به ----------

def test_legacy_reminder_receipt_moves_to_its_date_and_extension_is_reminded():
    st, w = State(), World()
    p = _prog("2026-10-28")
    p.alerted = True
    st.programs.items[p.key] = p
    st.outbox.receipts[f"rem3:{p.key}"] = 7
    run_once(T0, [], st, w.deps())
    assert f"rem3:{p.key}:2026-10-28" in st.outbox.receipts and f"rem3:{p.key}" not in st.outbox.receipts
    assert not any("⏰" in t for _, t in w.sent)
    p.fields["closes"]["value"] = "2026-11-04"  # الجهة مدّدت
    run_once(datetime(2026, 11, 2, 10, 0, tzinfo=RIYADH), [], st, w.deps())
    assert any(t.startswith("⏰ باقي يومين") for _, t in w.sent)


# ---------- ٣: تقرير المالك بالعربية ----------

def test_owner_report_names_every_verdict_kind_in_arabic():
    st = State()
    now = datetime(2026, 10, 22, 7, 17, tzinfo=RIYADH)
    st.meta["verdicts"] = [{"at": "2026-10-22T05:00", "kind": k, "url": "u"} for k in ("irrelevant", "pending", "coop")]
    _digests(Ctx(st, None, now, [], RunReport(), lambda: False), [Aggregator("ت", "https://agg.example.com/f")])
    owner = st.outbox.pending["owner-digest:2026-10-22"]["text"]
    assert "غير ذي صلة 1" in owner and "معلّق 1" in owner and "irrelevant" not in owner
