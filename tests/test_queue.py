from datetime import datetime, timedelta

from rasid.dates import RIYADH
from rasid.queue import RetryQueue

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=RIYADH)


def test_failed_item_stays_and_is_never_dropped():
    q = RetryQueue()
    q.add("a1", "aramco", "https://x", "نص", "الذكاء متوقف", T0)
    for i in range(10):
        q.fail("a1", "ما زال متوقفاً", T0 + timedelta(hours=i))
    assert "a1" in q.items and q.items["a1"].attempts == 11


def test_backoff_then_due():
    q = RetryQueue()
    q.add("a1", "aramco", "https://x", "نص", "سبب", T0)
    assert q.due(T0) == []
    assert [i.id for i in q.due(T0 + timedelta(hours=2))] == ["a1"]


def test_stuck_after_five_attempts_or_a_day():
    q = RetryQueue()
    q.add("a1", "e", "u", "t", "r", T0)
    q.add("b2", "e", "u", "t", "r", T0)
    for _ in range(4):
        q.fail("a1", "r", T0)
    assert [i.id for i in q.stuck(T0)] == ["a1"]
    assert {i.id for i in q.stuck(T0 + timedelta(hours=25))} == {"a1", "b2"}


def test_done_removes():
    q = RetryQueue()
    q.add("a1", "e", "u", "t", "r", T0)
    q.mark_done("a1")
    assert q.items == {}


def test_adding_same_item_again_does_not_reset_it():
    q = RetryQueue()
    q.add("a1", "e", "u", "t", "r", T0)
    q.fail("a1", "r", T0)
    q.add("a1", "e", "u", "t", "r", T0 + timedelta(hours=1))
    assert q.items["a1"].attempts == 2 and q.items["a1"].first_seen == T0


def test_recheck_flag_and_previous_kind_survive_round_trip():
    q = RetryQueue()
    q.add("a1", "e", "u", "t", "إعادة فحص", T0, recheck_of="university")
    q2 = RetryQueue.from_dict(q.to_dict())
    assert q2.items["a1"].recheck_of == "university" and q2.items["a1"].first_seen == T0
