"""اختبارات إصلاح الفحص الثاني عشر (٢٤ أكتوبر): برنامج بعدة مسارات لا يأخذ تخصص آخر مسار قُرئ."""
from datetime import date, timedelta

from rasid.classify.schema import Field, Verdict
from rasid.programs import Programs
from rasid.run import State, run_once
from tests.test_audit_fixes import ELM
from tests.test_programs import T0
from tests.test_run import World

BASE = "Elm Co-op Training Program (January 2027 Intake)"
LISTING = "https://career.elm.sa/go/coop"


def _track(name: str) -> tuple[Verdict, str]:
    url = f"https://career.elm.sa/job/{name.replace(' ', '-')}/1"
    return Verdict("coop", "m", {"title": Field(f"{BASE} - {name}", "q"), "closes": Field(date(2026, 11, 4), "q"),
                                 "apply_url": Field(url, "q")},
                   majors=[{"name": name, "seats": None, "quote": name}]), url


def test_track_postings_keep_every_major_with_its_own_link():
    ps = Programs()
    urls = {}
    for i, name in enumerate(["Software Engineering", "Computer Science", "Legal"]):
        verdict, urls[name] = _track(name)
        p, _ = ps.merge("elm", verdict, urls[name], T0 + timedelta(hours=i), listing=LISTING)
    assert len(ps.items) == 1
    assert p.fields["title"]["value"] == BASE
    assert [(m["name"], m["url"]) for m in p.majors] == [(n, urls[n]) for n in urls]
    assert p.fields["apply_url"]["value"] == LISTING  # رابط التقديم العام: صفحة كل المسارات


def test_track_without_listing_keeps_the_first_apply_link():
    ps = Programs()
    first, url = _track("Computer Science")
    ps.merge("elm", first, url, T0)
    p, _ = ps.merge("elm", _track("Legal")[0], "https://career.elm.sa/job/Legal/1", T0 + timedelta(hours=1))
    assert p.fields["apply_url"]["value"] == url and p.fields["title"]["value"] == BASE


def test_a_different_title_is_not_a_track():
    ps = Programs()
    ps.merge("elm", _track("Legal")[0], "https://career.elm.sa/job/Legal/1", T0)
    other = Verdict("coop", "m", {"title": Field("برنامج التدريب التعاوني لدفعة يناير 2027", "q"),
                                  "closes": Field(date(2026, 11, 4), "q")},
                    majors=[{"name": "علوم الحاسب", "seats": None, "quote": "علوم الحاسب"}])
    p, _ = ps.merge("elm", other, "https://agg.example.com/elm", T0 + timedelta(hours=1))
    assert p.fields["title"]["value"] == "برنامج التدريب التعاوني لدفعة يناير 2027"
    assert [m["name"] for m in p.majors] == ["Legal", "علوم الحاسب"]  # مصدر يذكر بعض التخصصات لا يمحو غيرها


def test_followed_postings_link_to_the_listing_page():
    w = World()
    w.pages[LISTING] = ["فرص التدريب في علم"]
    st = State()
    run_once(T0, [ELM], st, w.deps())
    for name in ("Computer Science", "Legal"):
        verdict, url = _track(name)
        w.links.setdefault(LISTING, []).append((f"{BASE} - {name}", url))
        w.pages[url] = [f"مسار {name}"]
        w.verdicts[f"مسار {name}"] = lambda verdict=verdict: verdict
    run_once(T0 + timedelta(hours=3), [ELM], st, w.deps())
    (p,) = st.programs.items.values()
    assert p.fields["apply_url"]["value"] == LISTING
    assert {m["name"] for m in p.majors} == {"Computer Science", "Legal"}
