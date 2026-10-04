from datetime import date

from rasid.classify.chain import Budget, Pending, classify
from rasid.classify.providers import CallResult, Provider
from rasid.classify.schema import parse_verdict

TEXT = "الجهة: sdaia\nالرابط: https://x.example\n\nالنص:\nتعلن سدايا فتح التسجيل في برنامج التدريب التعاوني من 5 يوليو 2026 حتى 12 يوليو 2026."


def good(kind="coop", opens="2026-07-05"):
    return {"kind": kind, "kind_quote": "برنامج التدريب التعاوني",
            "opens": {"value": opens, "quote": "من 5 يوليو 2026"},
            "closes": {"value": "2026-07-12", "quote": "حتى 12 يوليو 2026"},
            "majors": []}


R1 = Provider("reader-a", "gemini", "m1", "K", daily=100, role="reader")
R2 = Provider("reader-b", "gemini", "m2", "K", daily=100, role="reader")
C1 = Provider("confirm-a", "gemini", "c1", "K", daily=20, role="confirmer")
C2 = Provider("confirm-b", "groq", "c2", "K", daily=20, role="confirmer")


def caller(script):
    """script: dict model -> CallResult أو قائمة نتائج متتالية."""
    calls = []

    def call(p, system, user):
        calls.append(p.name)
        r = script[p.model]
        return r.pop(0) if isinstance(r, list) else r
    call.calls = calls
    return call


OK = lambda d: CallResult(True, d)  # noqa: E731
FAIL = lambda kind: CallResult(False, None, kind, "x")  # noqa: E731


# ---------- schema ----------

def test_valid_verdict_parses():
    v = parse_verdict(good(), TEXT, "m1")
    assert v.kind == "coop" and v.fields["opens"].value == date(2026, 7, 5) and v.model == "m1"


def test_fabricated_quote_rejected():
    d = good(); d["closes"]["quote"] = "حتى نهاية الشهر"
    assert parse_verdict(d, TEXT, "m1") is None


def test_quote_ignores_punctuation_and_bullets():
    d = good(); d["kind_quote"] = "- برنامج التدريب، التعاوني"
    assert parse_verdict(d, TEXT, "m1") is not None


def test_date_contradicting_its_quote_rejected():
    assert parse_verdict(good(opens="2026-07-06"), TEXT, "m1") is None


def test_hijri_value_is_converted():
    t = TEXT + " يبدأ 15 جمادى الأولى 1448"
    d = good(); d["opens"] = {"value": "H:1448-05-15", "quote": "يبدأ 15 جمادى الأولى 1448"}
    assert parse_verdict(d, t, "m1").fields["opens"].value == date(2026, 10, 26)


def test_unknown_kind_rejected():
    assert parse_verdict(good(kind="maybe"), TEXT, "m1") is None


def test_null_fields_are_fine():
    d = good(); d["closes"] = {"value": None, "quote": None}
    assert parse_verdict(d, TEXT, "m1").fields.get("closes") is None


# ---------- chain ----------

def test_relevant_reader_verdict_is_confirmed_by_confirmer():
    call = caller({"m1": OK(good()), "c1": OK(good())})
    v = classify(TEXT, [R1, C1], Budget(), call)
    assert v.kind == "coop" and v.model == "c1" and call.calls == ["reader-a", "confirm-a"]


def test_irrelevant_without_keywords_skips_confirmer():
    t = "الجهة: x\n\nالنص:\nافتتاح مبنى جديد للهيئة."
    d = {"kind": "irrelevant", "kind_quote": "افتتاح مبنى جديد"}
    call = caller({"m1": OK(d)})
    v = classify(t, [R1, C1], Budget(), call)
    assert v.kind == "irrelevant" and call.calls == ["reader-a"]


def test_irrelevant_but_strong_keyword_escalates():
    d = {"kind": "irrelevant", "kind_quote": "برنامج التدريب التعاوني"}
    call = caller({"m1": OK(d), "c1": OK(good())})
    v = classify(TEXT, [R1, C1], Budget(), call)
    assert v.kind == "coop" and call.calls == ["reader-a", "confirm-a"]


def test_confirmer_overrides_reader():
    call = caller({"m1": OK(good(kind="job")), "c1": OK(good(kind="coop"))})
    assert classify(TEXT, [R1, C1], Budget(), call).kind == "coop"


def test_bad_reader_answer_tries_next_reader():
    bad = good(); bad["opens"]["quote"] = "مختلق تماماً"
    call = caller({"m1": OK(bad), "m2": OK(good()), "c1": OK(good())})
    v = classify(TEXT, [R1, R2, C1], Budget(), call)
    assert v.kind == "coop" and call.calls[:2] == ["reader-a", "reader-b"]


def test_busy_confirmer_falls_to_next():
    call = caller({"m1": OK(good()), "c1": FAIL("busy"), "c2": OK(good())})
    assert classify(TEXT, [R1, C1, C2], Budget(), call).model == "c2"


def test_all_confirmers_down_keeps_reader_verdict_flagged_for_recheck():
    call = caller({"m1": OK(good()), "c1": FAIL("busy"), "c2": FAIL("network")})
    v = classify(TEXT, [R1, C1, C2], Budget(), call)
    assert v.kind == "coop" and v.model == "m1" and v.needs_recheck


def test_everything_down_with_keywords_alerts_uncertain():
    call = caller({"m1": FAIL("network"), "m2": FAIL("rate_day"), "c1": FAIL("busy"), "c2": FAIL("busy")})
    v = classify(TEXT, [R1, R2, C1, C2], Budget(), call)
    assert v.uncertain and v.model == "keywords" and v.kind == "coop" and v.needs_recheck


def test_everything_down_without_keywords_is_pending_not_dropped():
    t = "الجهة: x\n\nالنص:\nافتتاح مبنى جديد."
    call = caller({"m1": FAIL("network"), "c1": FAIL("busy")})
    r = classify(t, [R1, C1], Budget(), call)
    assert isinstance(r, Pending) and r.reason_ar


def test_daily_budget_is_respected_and_resets_by_riyadh_day():
    b = Budget()
    p = Provider("tiny", "gemini", "m1", "K", daily=1, role="reader")
    call = caller({"m1": [OK(good()), OK(good())], "c1": OK(good())})
    classify(TEXT, [p, C1], b, call, today=date(2026, 10, 4))
    r = classify(TEXT, [p], b, call, today=date(2026, 10, 4))
    assert call.calls.count("tiny") == 1  # الحصة خلصت
    classify(TEXT, [p, C1], b, call, today=date(2026, 10, 5))
    assert call.calls.count("tiny") == 2


def test_rate_day_marks_provider_exhausted_for_today():
    b = Budget()
    call = caller({"m1": [FAIL("rate_day")], "m2": [OK(good()), OK(good())], "c1": [OK(good()), OK(good())]})
    classify(TEXT, [R1, R2, C1], b, call, today=date(2026, 10, 4))
    classify(TEXT, [R1, R2, C1], b, call, today=date(2026, 10, 4))
    assert call.calls.count("reader-a") == 1


def test_thinking_text_is_stripped_from_answer():
    from rasid.classify.providers import _extract_json
    assert _extract_json('<thought>أفكر... {"x": 1}</thought>\n```json\n{"kind": "job"}\n```') == {"kind": "job"}
    assert _extract_json("not json") is None


def test_budget_survives_between_runs():
    b = Budget()
    b.spend(R1, date(2026, 10, 4)); b.spend(R1, date(2026, 10, 4)); b.exhaust(C1, date(2026, 10, 4))
    b2 = Budget.from_dict(b.to_dict(), today=date(2026, 10, 4))
    assert b2.used[("reader-a", date(2026, 10, 4))] == 2 and not b2.available(C1, date(2026, 10, 4))


def test_old_budget_days_are_dropped():
    b = Budget(); b.spend(R1, date(2026, 10, 1))
    assert Budget.from_dict(b.to_dict(), today=date(2026, 10, 4)).to_dict() == {"used": {}, "exhausted": []}
