import json
from datetime import date, datetime

from rasid.classify.schema import Field, Verdict
from rasid.dates import RIYADH
from rasid.entities import Channel, Entity
from rasid.privacy_guard import scan_text
from rasid.publish import build_results, compute_stars, expected_month
from rasid.run import State

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=RIYADH)
ARAMCO = Entity("aramco", "أرامكو", 1, 3, [Channel("web", "https://a/x"), Channel("web", "https://a/y")],
                stars_manual=5, fulltime_history="yes", fulltime_evidence="لا يسمح بتسجيل مواد", usual_months=[10])
SDAIA = Entity("sdaia", "سدايا", 3, 2, [Channel("web", "https://s/x")])


def state():
    st = State()
    v = Verdict("coop", "gemini-3.5-flash", {"opens": Field(date(2026, 10, 26), "يفتح 26 أكتوبر 2026"),
                                            "closes": Field(date(2026, 11, 2), "حتى 2 نوفمبر 2026")})
    st.programs.merge("aramco", v, "https://a/x", NOW)
    st.health = {"https://a/x": {"entity": "aramco", "name": "أرامكو", "last_success": NOW.isoformat(),
                                 "consecutive_failures": 0, "last_error_ar": None, "first_failure": None, "via": "direct"},
                 "https://a/y": {"entity": "aramco", "name": "أرامكو", "last_success": None,
                                 "consecutive_failures": 2, "last_error_ar": "[الجالب] فشل", "first_failure": NOW.isoformat()},
                 "https://s/x": {"entity": "sdaia", "name": "سدايا", "last_success": NOW.isoformat(),
                                 "consecutive_failures": 0, "last_error_ar": None, "first_failure": None, "via": "home"}}
    st.queue.add("q1", "sdaia", "https://s/x", "نص صفحة كامل سري لا يُنشر", "متوقف", NOW)
    return st


def test_results_have_entities_programs_and_honest_health():
    r = build_results(state(), [ARAMCO, SDAIA], NOW)
    a = next(e for e in r["entities"] if e["id"] == "aramco")
    assert a["sources_ok"] == 1 and a["sources_total"] == 2 and a["status"] == "announced"
    assert a["fulltime_history"] == "yes" and a["fulltime_evidence"]
    s = next(e for e in r["entities"] if e["id"] == "sdaia")
    assert s["status"] == "not_announced" and s["via_home"] is True
    p = r["programs"][0]
    assert p["opens"] == "2026-10-26" and p["fields"]["opens"]["quote"] == "يفتح 26 أكتوبر 2026"
    assert r["health"]["sources_total"] == 3 and r["health"]["sources_ok"] == 2 and r["health"]["queue"] == 1


def test_results_never_contain_raw_page_text_or_errors_detail():
    blob = json.dumps(build_results(state(), [ARAMCO, SDAIA], NOW), ensure_ascii=False)
    assert "سري لا يُنشر" not in blob


def test_results_pass_privacy_guard():
    blob = json.dumps(build_results(state(), [ARAMCO, SDAIA], NOW), ensure_ascii=False)
    assert scan_text(blob, forbidden=["FAKE-SECRET-NAME"], check_emails=False) == []


def test_manual_stars_win_else_computed_from_founder_weights():
    assert compute_stars(ARAMCO, None) == 5
    strong = Entity("x", "x", cyber=3, hires_after=3, channels=[])
    weak = Entity("y", "y", cyber=0, hires_after=0, channels=[])
    assert 1 <= compute_stars(weak, None) < compute_stars(strong, None) <= 5


def test_expected_month_from_history_else_usual_else_unknown():
    assert expected_month(ARAMCO, ["2025-10-20", "2024-10-28", "2023-11-01"]) == 10
    assert expected_month(ARAMCO, []) == 10
    assert expected_month(SDAIA, []) is None
