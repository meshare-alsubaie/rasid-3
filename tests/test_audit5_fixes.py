"""اختبارات إصلاحات الفحص الخامس (٢٢ أكتوبر): أحكام الذكاء وحصصه."""
from datetime import date, datetime

from rasid.classify import chain
from rasid.classify.chain import SHORT_INPUT, Budget, classify
from rasid.classify.schema import check_verdict
from rasid.dates import RIYADH, quota_day
from tests.test_classify import C1, FAIL, OK, R1, TEXT, caller, good

LONG = TEXT + "\nسياق " * 2000


# ---------- ١: «غير ذي صلة» باقتباس غير مطابق يُقبل بلا اقتباس ----------

def test_irrelevant_with_unmatched_quote_is_kept_without_the_quote():
    v, _ = check_verdict({"kind": "irrelevant", "kind_quote": "نص مختلق"}, TEXT, "m")
    assert v.kind == "irrelevant" and v.kind_quote is None and v.notes


def test_opportunity_with_unmatched_quote_is_still_rejected():
    d = good(); d["kind_quote"] = "نص مختلق"
    v, why = check_verdict(d, TEXT, "m")
    assert v is None and "اقتباس" in why


# ---------- ٢: النص الطويل يُعاد مختصراً لنفس النموذج ----------

def test_too_large_is_retried_once_with_the_start_of_the_text():
    seen = []
    base = caller({"m1": OK(good()), "c1": [FAIL("too_large"), OK(good())]})

    def call(p, system, user):
        seen.append((p.name, len(user)))
        return base(p, system, user)
    b = Budget()
    v = classify(LONG, [R1, C1], b, call, today=date(2026, 10, 22))
    assert v.kind == "coop" and v.model == "c1"
    assert seen[-2:] == [("confirm-a", len(LONG)), ("confirm-a", SHORT_INPUT)]
    assert b.used[("confirm-a", date(2026, 10, 22))] == 2


def test_quote_from_the_cut_tail_is_rejected():
    d = good(); d["kind_quote"] = "سياق سياق"
    tail = TEXT[:SHORT_INPUT] + "x" * SHORT_INPUT + " سياق سياق"
    call = caller({"m1": OK(good()), "c1": [FAIL("too_large"), OK(d)]})
    v = classify(tail, [R1, C1], Budget(), call, today=date(2026, 10, 22))
    assert v.model == "m1" and v.needs_recheck


# ---------- ٣: يوم الحصة بتوقيت المحيط الهادئ، وتاريخ التعليمات بالرياض ----------

def test_quota_day_turns_over_at_pacific_midnight():
    assert quota_day(datetime(2026, 10, 22, 9, 59, tzinfo=RIYADH)) == date(2026, 10, 21)
    assert quota_day(datetime(2026, 10, 22, 10, 0, tzinfo=RIYADH)) == date(2026, 10, 22)


def test_budget_uses_quota_day_and_prompt_keeps_riyadh_date(monkeypatch):
    monkeypatch.setattr(chain, "riyadh_now", lambda: datetime(2026, 10, 22, 8, 0, tzinfo=RIYADH))
    monkeypatch.setattr(chain, "quota_day", lambda: date(2026, 10, 21))
    systems = []
    base = caller({"m1": OK(good()), "c1": OK(good())})

    def call(p, system, user):
        systems.append(system)
        return base(p, system, user)
    b = Budget()
    classify(TEXT, [R1, C1], b, call)
    assert b.used[("reader-a", date(2026, 10, 21))] == 1
    assert all(s.endswith("تاريخ اليوم: 2026-10-22") for s in systems)


# ---------- ٤: نوع الحكم المرفوض في السجل ----------

def test_rejection_note_names_the_verdict_kind():
    d = good(); d["kind_quote"] = "نص مختلق"
    call = caller({"m1": OK(d), "c1": OK(good())})
    v = classify(TEXT, [R1, C1], Budget(), call, today=date(2026, 10, 22))
    assert any("جواب مرفوض (coop)" in n for n in v.notes)
