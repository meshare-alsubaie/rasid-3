"""اختبارات إصلاح الفحص الثامن (٢٢ أكتوبر): المنشور الواحد لا يُصنَّف مرتين من خلاصتين لنفس الموقع."""
from rasid.classify.schema import Field, Verdict
from rasid.entities import Aggregator
from rasid.fetch import Block
from rasid.run import State, run_once
from tests.test_audit6_fixes import POST
from tests.test_audit_fixes import FEED
from tests.test_run import T0, World

STUDENTS = Aggregator("موقع تجميع (للطلاب)", "https://agg.example.com/?s=students&feed=rss2")
OTHER = Aggregator("موقع تجميع آخر", "https://other.example.org/feed")
TITLE = "شركة علم تطلق برنامج التدريب التعاوني"


def _world():
    w = World()
    for a in (FEED, STUDENTS):
        w.pages[a.url] = [Block(TITLE, POST)]
    w.pages[POST] = ["شركة علم تعلن التدريب التعاوني"]
    w.verdicts["شركة علم تعلن"] = lambda: Verdict("coop", "m", {"entity_name": Field("شركة علم", "q")})
    return w


def _reads(w):
    return sum("شركة علم تعلن" in t for t in w.classified)


def test_same_post_in_two_feeds_of_one_site_is_classified_once():
    w, st = _world(), State()
    run_once(T0, [], st, w.deps(), aggregators=[FEED, STUDENTS])
    assert _reads(w) == 1
    run_once(T0, [], st, w.deps(), aggregators=[FEED, STUDENTS])
    assert _reads(w) == 1


def test_post_read_earlier_by_a_sister_feed_is_not_read_again():
    w, st = _world(), State()
    w.pages[STUDENTS.url] = []
    run_once(T0, [], st, w.deps(), aggregators=[FEED, STUDENTS])
    w.pages[STUDENTS.url] = [Block(TITLE, POST)]
    run_once(T0, [], st, w.deps(), aggregators=[STUDENTS, FEED])  # الأخت تُعالج أولاً هذه المرة
    assert _reads(w) == 1


def test_another_site_keeps_its_own_memory():
    w, st = _world(), State()
    w.pages[OTHER.url] = [Block(TITLE, "https://other.example.org/post")]
    w.pages["https://other.example.org/post"] = ["شركة علم تعلن التدريب التعاوني"]
    run_once(T0, [], st, w.deps(), aggregators=[FEED, OTHER])
    assert _reads(w) == 2
