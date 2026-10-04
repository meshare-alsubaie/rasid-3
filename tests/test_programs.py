from datetime import date, datetime, timedelta

from rasid.classify.schema import Field, Verdict
from rasid.dates import RIYADH
from rasid.programs import Programs, status_of

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=RIYADH)


def v(kind="coop", opens=None, closes=None, **extra):
    f = {}
    if opens:
        f["opens"] = Field(opens, "q")
    if closes:
        f["closes"] = Field(closes, "q")
    for k, val in extra.items():
        f[k] = Field(val, "q")
    return Verdict(kind=kind, model="m", fields=f)


def test_first_relevant_verdict_creates_program_with_new_change():
    ps = Programs()
    p, ch = ps.merge("aramco", v(opens=date(2026, 10, 26)), "https://a", T0)
    assert ch.kind == "new" and p.entity_id == "aramco" and p.sources == ["https://a"]


def test_same_program_from_two_sources_is_one_card():
    ps = Programs()
    ps.merge("aramco", v(opens=date(2026, 10, 26)), "https://site", T0)
    p, ch = ps.merge("aramco", v(opens=date(2026, 10, 26)), "https://x.com/aramco", T0 + timedelta(hours=3))
    assert len(ps.items) == 1 and ch is None
    assert p.sources == ["https://site", "https://x.com/aramco"]


def test_announcement_without_dates_attaches_to_recent_program():
    ps = Programs()
    ps.merge("aramco", v(opens=date(2026, 10, 26)), "https://site", T0)
    ps.merge("aramco", v(), "https://x.com/aramco", T0 + timedelta(days=2))
    assert len(ps.items) == 1


def test_hint_then_official_is_same_program_with_second_new():
    ps = Programs()
    _, c1 = ps.merge("sdaia", v(kind="hint"), "https://x.com/sdaia", T0)
    p, c2 = ps.merge("sdaia", v(opens=date(2026, 12, 6)), "https://sdaia", T0 + timedelta(days=5))
    assert c1.kind == "hint" and c2.kind == "new" and len(ps.items) == 1 and p.kind == "coop"


def test_changed_closing_date_is_important_update():
    ps = Programs()
    ps.merge("aramco", v(opens=date(2026, 10, 26), closes=date(2026, 11, 2)), "https://a", T0)
    p, ch = ps.merge("aramco", v(opens=date(2026, 10, 26), closes=date(2026, 11, 9)), "https://a", T0)
    assert ch.kind == "important_update" and p.fields["closes"]["value"] == "2026-11-09"
    assert "2026-11-02" in ch.detail_ar and "2026-11-09" in ch.detail_ar


def test_irrelevant_makes_nothing():
    ps = Programs()
    p, ch = ps.merge("x", v(kind="irrelevant"), "https://a", T0)
    assert p is None and ch is None and ps.items == {}


def test_different_cycles_are_different_programs():
    ps = Programs()
    ps.merge("sdaia", v(opens=date(2026, 7, 5)), "https://a", T0)
    ps.merge("sdaia", v(opens=date(2026, 12, 6)), "https://a", T0)
    assert len(ps.items) == 2


def test_jobs_are_kept_separately_from_coop():
    ps = Programs()
    ps.merge("elm", v(kind="job"), "https://a", T0)
    ps.merge("elm", v(kind="coop", opens=date(2026, 11, 1)), "https://a", T0)
    assert len(ps.items) == 2


def test_status_by_dates():
    d = date(2026, 10, 20)
    assert status_of({"opens": "2026-10-26", "closes": "2026-11-02"}, d) == "announced"
    assert status_of({"opens": "2026-10-26", "closes": "2026-11-02"}, date(2026, 10, 27)) == "open"
    assert status_of({"opens": "2026-10-26", "closes": "2026-11-02"}, date(2026, 10, 31)) == "closing_soon"
    assert status_of({"opens": "2026-10-26", "closes": "2026-11-02"}, date(2026, 11, 3)) == "closed"
    assert status_of({}, d) == "announced"


def test_round_trip_serialisation():
    ps = Programs()
    ps.merge("aramco", v(opens=date(2026, 10, 26), housing=True), "https://a", T0)
    ps2 = Programs.from_dict(ps.to_dict())
    assert ps2.to_dict() == ps.to_dict()
