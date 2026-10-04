import json
from datetime import date, datetime, timedelta

import pytest

from rasid.classify.chain import Pending
from rasid.classify.schema import Field, Verdict
from rasid.dates import RIYADH
from rasid.entities import Channel, Entity
from rasid.fetch import Block, FetchResult
from rasid.run import Deps, State, run_once

T0 = datetime(2026, 10, 26, 10, 0, tzinfo=RIYADH)
ARAMCO = Entity("aramco", "أرامكو", 1, 3, [Channel("web", "https://aramco/x")])
SDAIA = Entity("sdaia", "سدايا", 3, 2, [Channel("web", "https://sdaia/x")])


def coop():
    return Verdict("coop", "m", {"opens": Field(date(2026, 10, 26), "q"),
                                 "closes": Field(date(2026, 11, 2), "q")})


class World:
    def __init__(self):
        self.pages = {"https://aramco/x": ["برنامج التدريب التعاوني يفتح 26 أكتوبر"],
                      "https://sdaia/x": ["خبر عن مبنى"]}
        self.broken = set()
        self.verdicts = {}
        self.sent = []
        self.classified = []

    def fetch(self, ch):
        if ch.url in self.broken:
            raise RuntimeError("انهيار مفاجئ")
        return FetchResult(True, ch.url, [Block(t) for t in self.pages[ch.url]])

    def classify(self, text):
        self.classified.append(text)
        for key, v in self.verdicts.items():
            if key in text:
                return v() if callable(v) else v
        return Verdict("irrelevant", "m")

    def send(self, chat, text):
        self.sent.append((chat, text))
        return len(self.sent)

    def deps(self):
        return Deps(self.fetch, self.classify, self.send)


def test_new_coop_is_sent_to_group_with_receipt(tmp_path):
    w = World(); w.verdicts["التعاوني"] = coop
    st = State()
    rep = run_once(T0, [ARAMCO, SDAIA], st, w.deps())
    assert rep.sent >= 1 and any("أرامكو" in t and c == "group" for c, t in w.sent)
    assert len(st.programs.items) == 1


def test_unchanged_page_is_not_classified_again():
    w = World(); w.verdicts["التعاوني"] = coop
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    n = len(w.classified)
    run_once(T0 + timedelta(hours=3), [ARAMCO], st, w.deps())
    assert len(w.classified) == n


def test_one_crashing_source_does_not_stop_others():
    w = World(); w.verdicts["التعاوني"] = coop
    w.broken.add("https://sdaia/x")
    st = State()
    rep = run_once(T0, [SDAIA, ARAMCO], st, w.deps())
    assert rep.fetch_ok == 1 and rep.fetch_fail == 1
    assert st.health["https://sdaia/x"]["last_success"] is None
    assert "انهيار" in st.health["https://sdaia/x"]["last_error_ar"]
    assert st.health["https://aramco/x"]["last_success"] == T0.isoformat()


def test_classifier_unavailable_goes_to_queue_not_lost():
    w = World(); w.verdicts["التعاوني"] = Pending("الذكاء متوقف")
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    assert len(st.queue.items) == 1 and st.programs.items == {}
    w.verdicts["التعاوني"] = coop
    run_once(T0 + timedelta(hours=3), [ARAMCO], st, w.deps())
    assert st.queue.items == {} and len(st.programs.items) == 1


def test_stuck_queue_alerts_owner_once():
    w = World(); w.verdicts["التعاوني"] = Pending("متوقف")
    st = State()
    for h in range(0, 30, 3):
        run_once(T0 + timedelta(hours=h), [ARAMCO], st, w.deps())
    owner = [t for c, t in w.sent if c == "owner" and "عالق في طابور" in t]
    assert len(owner) == 1


def test_dead_source_for_three_days_alerts_owner():
    w = World(); w.broken.add("https://sdaia/x")
    st = State()
    run_once(T0, [SDAIA], st, w.deps())
    run_once(T0 + timedelta(days=3, hours=1), [SDAIA], st, w.deps())
    assert any(c == "owner" and "سدايا" in t for c, t in w.sent)


def test_daily_digest_at_seven_once_says_alive_when_nothing_new():
    w = World()
    st = State()
    morning = datetime(2026, 10, 27, 7, 5, tzinfo=RIYADH)
    run_once(morning, [SDAIA], st, w.deps())
    run_once(morning + timedelta(hours=3), [SDAIA], st, w.deps())
    group = [t for c, t in w.sent if c == "group"]
    assert len(group) == 1 and "راصد شغّال" in group[0]
    assert any(c == "owner" and "تقرير" in t for c, t in w.sent)


def test_quiet_hours_hold_group_alert():
    w = World(); w.verdicts["التعاوني"] = coop
    st = State()
    night = datetime(2026, 10, 27, 2, 0, tzinfo=RIYADH)
    run_once(night, [ARAMCO], st, w.deps())
    assert [c for c, _ in w.sent if c == "group"] == []
    assert len(st.outbox.pending) == 1


def test_state_save_is_atomic_and_round_trips(tmp_path):
    w = World(); w.verdicts["التعاوني"] = coop
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    p = tmp_path / "state.json"
    st.save(p)
    st2 = State.load(p)
    assert st2.programs.to_dict() == st.programs.to_dict()
    assert st2.seen == st.seen


def test_crash_during_save_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    State().save(p)
    old = p.read_text(encoding="utf-8")
    st = State(); st.seen["x"] = ["h"]
    monkeypatch.setattr(json, "dumps", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        st.save(p)
    assert p.read_text(encoding="utf-8") == old


def test_missing_state_file_starts_fresh(tmp_path):
    assert State.load(tmp_path / "none.json").programs.items == {}


def test_recheck_disagreement_sends_correction():
    w = World()
    v = coop(); v.needs_recheck = True; v.model = "reader"
    w.verdicts["التعاوني"] = v
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    assert len(st.queue.items) == 1
    w.verdicts["التعاوني"] = Verdict("irrelevant", "confirmer")
    run_once(T0 + timedelta(hours=3), [ARAMCO], st, w.deps())
    assert any("تصحيح" in t for c, t in w.sent if c == "group")


def test_first_sight_of_page_without_upcoming_window_is_silent():
    w = World()
    w.verdicts["التعاوني"] = lambda: Verdict("coop", "m", {})  # صفحة دائمة بلا تواريخ
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    assert not any(c == "group" and "جديد:" in t for c, t in w.sent)
    assert len(st.programs.items) == 1  # محفوظ بهدوء


def test_first_sight_of_closed_program_is_silent():
    w = World()
    w.verdicts["التعاوني"] = lambda: Verdict("coop", "m", {"closes": Field(date(2025, 7, 12), "q")})
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    assert not any(c == "group" and "جديد:" in t for c, t in w.sent)


def test_change_after_first_sight_alerts_even_without_dates():
    w = World()
    w.verdicts["التعاوني"] = lambda: Verdict("coop", "m", {})
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    w.pages["https://aramco/x"].append("إعلان جديد: برنامج التدريب الصيفي الثاني")
    w.verdicts = {"الصيفي": lambda: Verdict("university", "m", {})}
    st.programs.items.clear()
    run_once(T0 + timedelta(hours=3), [ARAMCO], st, w.deps())
    assert any(c == "group" and "جديد:" in t for c, t in w.sent)


def test_closed_program_from_queue_is_not_announced_as_new():
    w = World(); w.verdicts["التعاوني"] = Pending("متوقف")
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    w.verdicts["التعاوني"] = lambda: Verdict("coop", "m", {"closes": Field(date(2025, 7, 12), "q")})
    run_once(T0 + timedelta(hours=3), [ARAMCO], st, w.deps())
    assert not any(c == "group" and "جديد:" in t for c, t in w.sent)


def test_saudi_list_has_blocked_and_home_fetched_sources():
    from rasid.run import saudi_list
    w = World(); w.broken.add("https://sdaia/x")
    st = State()
    run_once(T0, [SDAIA, ARAMCO], st, w.deps())
    st.health["https://aramco/x"]["via"] = "home"
    assert set(saudi_list(st)) == {"https://sdaia/x", "https://aramco/x"}


def test_health_records_how_source_was_read():
    w = World()
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    assert st.health["https://aramco/x"]["via"] == "direct"


def test_fetching_is_parallel_so_slow_sites_do_not_add_up():
    import time
    w = World()
    ents = [Entity(f"e{i}", f"جهة {i}", 1, 1, [Channel("web", f"https://s{i}/x")]) for i in range(8)]
    for i in range(8):
        w.pages[f"https://s{i}/x"] = ["خبر عام"]

    def slow_fetch(ch):
        time.sleep(0.5)
        return World.fetch(w, ch)
    t0 = time.time()
    run_once(T0, ents, State(), Deps(slow_fetch, w.classify, w.send))
    assert time.time() - t0 < 2.0  # ٨ مواقع بطيئة × نصف ثانية = ٤ ثوانٍ لو كانت متتالية


def test_deadline_stops_cleanly_and_leaves_rest_for_next_run():
    w = World(); w.verdicts["التعاوني"] = coop
    st = State()
    rep = run_once(T0, [SDAIA, ARAMCO], st, w.deps(), deadline=lambda: len(w.classified) >= 1)
    assert rep.deferred == 1
    assert "https://aramco/x" not in st.seen  # لم يُعلَّم مقروءاً
    run_once(T0 + timedelta(hours=3), [SDAIA, ARAMCO], st, w.deps())
    assert "https://aramco/x" in st.seen and len(st.programs.items) == 1


def test_checkpoint_is_called_during_run():
    w = World()
    st = State()
    calls = []
    ents = [Entity(f"e{i}", f"جهة {i}", 1, 1, [Channel("web", f"https://s{i}/x")]) for i in range(30)]
    for i in range(30):
        w.pages[f"https://s{i}/x"] = [f"خبر {i}"]
    run_once(T0, ents, st, w.deps(), checkpoint=lambda: calls.append(1), checkpoint_every=10)
    assert len(calls) >= 3


def test_aramco_scenario_from_first_real_run_alerts_when_dates_appear():
    w = World()
    w.pages["https://aramco/x"] = ["برامج الطلاب في أرامكو"]
    w.verdicts["برامج الطلاب"] = lambda: Verdict("coop", "m", {})
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    w.pages["https://aramco/x"].append("التسجيل في برنامج التدريب التعاوني يفتح 26 أكتوبر")
    w.verdicts = {"التسجيل": coop}
    run_once(T0 + timedelta(hours=3), [ARAMCO], st, w.deps())
    assert any(c == "group" and "أرامكو" in t and "26 أكتوبر" in t for c, t in w.sent)
