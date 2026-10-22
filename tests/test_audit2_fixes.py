"""اختبارات إصلاحات الفحص الثاني (٢٢ أكتوبر): كل اختبار يثبّت مشكلة وُجدت في الجولة الحقيقية أو الموقع."""
from datetime import date, datetime, timedelta

from rasid.classify.chain import Budget, classify
from rasid.classify.providers import CallResult, Provider
from rasid.classify.schema import Field, Verdict, check_verdict
from rasid.entities import Aggregator, Channel, Entity, agg_sites
from rasid.fetch import _CA_ISSUERS, Block, _issuer_url, _rss_blocks
from rasid.notify.outbox import Outbox
from rasid.notify.templates import reminders, render
from rasid.programs import Change, Program, program_status
from rasid.publish import build_results
from rasid.run import FOLLOW_TRIES, TRAINING, State, run_once, saudi_list
from tests.test_run import T0, World

GOV = Entity("ncgr", "المركز الوطني لنظم الموارد الحكومية", 3, 2, [Channel("web", "https://ncgr.gov.sa/news")])
POST = "https://ncgr.gov.sa/news/coop-1448"
FEED = Aggregator("موقع تجميع", "https://agg.example.com/feed")
AGG = agg_sites([FEED])


class FlakyWorld(World):
    """صفحة متبوعة ترفض السحابة حتى يُسمح لها."""
    def __init__(self):
        super().__init__()
        self.blocked = {POST}

    def fetch(self, ch):
        if ch.url in self.blocked:
            from rasid.fetch import FetchResult
            return FetchResult(False, ch.url, error_ar="محجوب")
        return super().fetch(ch)


def _gov_world():
    w = FlakyWorld()
    w.pages[GOV.channels[0].url] = ["أخبار المركز"]
    w.links[GOV.channels[0].url] = [("برنامج التدريب التعاوني ١٤٤٨", POST)]
    w.pages[POST] = ["برنامج التدريب التعاوني لعام 2027 يقفل 31 أكتوبر"]
    return w


# ---------- ١ و٤: الرابط المتبوع الفاشل لا يضيع، والسنة بالأرقام العربية تُعرف ----------

def test_failed_followed_link_is_retried_and_goes_to_home_list():
    w, st = _gov_world(), State()
    run_once(T0, [GOV], st, w.deps())  # أول مرة: «١٤٤٨» في العنوان فيُفتح، لكنه محجوب
    assert POST in st.meta["follow_fail"] and POST in saudi_list(st)
    w.blocked.clear()
    run_once(T0 + timedelta(hours=2), [GOV], st, w.deps())
    assert POST in w.fetched and POST not in st.meta["follow_fail"]
    assert any("31 أكتوبر" in t for t in w.classified)


def test_followed_link_is_given_up_after_a_day_of_failures():
    w, st = _gov_world(), State()
    for i in range(FOLLOW_TRIES):
        run_once(T0 + timedelta(hours=2 * i), [GOV], st, w.deps())
    assert POST not in st.meta["follow_fail"] and POST not in saudi_list(st)
    w.blocked.clear()
    run_once(T0 + timedelta(hours=2 * FOLLOW_TRIES), [GOV], st, w.deps())
    assert POST not in w.fetched


def test_vanished_failed_link_leaves_home_list_after_three_days():
    st = State()
    st.meta["follow_fail"] = {POST: [1, (T0 - timedelta(days=4)).isoformat()]}
    run_once(T0, [], st, World().deps())
    assert st.meta["follow_fail"] == {}


# ---------- ٣: كلمة intern ----------

def test_intern_matches_internship_not_international_or_internal():
    assert TRAINING.search("Internship Program 2027") and TRAINING.search("Summer Interns")
    assert not TRAINING.search("International Relations") and not TRAINING.search("Internal Mobility")


# ---------- ٥: الحقل الجانبي بلا دليل يسقط وحده ----------

TEXT = "الجهة: علم\n\nالنص:\nبرنامج التدريب التعاوني، التقديم متاح حتى 4 نوفمبر 2026"


def test_side_field_with_bad_quote_is_dropped_and_verdict_kept():
    d = {"kind": "coop", "kind_quote": "برنامج التدريب التعاوني",
         "closes": {"value": "2026-11-04", "quote": "حتى 4 نوفمبر 2026"},
         "accepting_now": {"value": True, "quote": "No"},
         "entity_name": {"value": "شركة علم", "quote": "شركة علم للخدمات"},
         "stipend": {"value": "نعم", "quote": "برنامج التدريب التعاوني"},
         "majors": [{"name": "علوم الحاسب", "quote": "علوم الحاسب"}]}
    v, why = check_verdict(d, TEXT, "m")
    assert v is not None and why == ""
    assert set(v.fields) == {"closes"} and v.majors == []
    assert any("accepting_now" in n for n in v.notes)


def test_made_up_date_still_rejects_whole_verdict():
    d = {"kind": "coop", "closes": {"value": "2026-11-04", "quote": "حتى نهاية الشهر"}}
    assert check_verdict(d, TEXT, "m")[0] is None


# ---------- ٢: المصنّف يعرف تاريخ اليوم، ومنشور التجميع القديم لا يُعلن مفتوحاً ----------

def test_classifier_is_told_todays_date():
    seen = []

    def call(p, system, user):
        seen.append(system)
        return CallResult(True, {"kind": "irrelevant"})
    classify(TEXT, [Provider("r", "gemini", "m1", "K", daily=9, role="reader")], Budget(), call,
             today=date(2026, 10, 22))
    assert seen and seen[0].endswith("تاريخ اليوم: 2026-10-22")


def test_rss_publish_date_is_kept_outside_the_fingerprint():
    xml = ("<rss><channel><item><title>شركة علم تعلن التدريب التعاوني</title><link>https://agg.example.com/1</link>"
           "<pubDate>Tue, 20 Oct 2026 08:00:00 +0300</pubDate></item>"
           "<entry><title>تدريب صيفي</title><published>2026-09-01T10:00:00Z</published></entry></channel></rss>")
    a, b = _rss_blocks(xml)
    assert (a.date, b.date) == ("2026-10-20", "2026-09-01")
    assert a.hash == Block(a.text).hash


def _agg_world(published):
    w = World()
    post = "https://agg.example.com/post-1"
    w.pages[FEED.url] = [Block("شركة سيمنس تفتح التدريب التعاوني", post, published)]
    w.pages[post] = ["شركة سيمنس تفتح باب التسجيل في التدريب التعاوني"]
    w.verdicts["سيمنس تفتح باب"] = lambda: Verdict("coop", "m", {"accepting_now": Field(True, "q"),
                                                                   "entity_name": Field("شركة سيمنس", "q")})
    return w


def test_old_aggregator_post_saying_open_is_not_announced_as_open():
    w, st = _agg_world((T0 - timedelta(days=40)).date().isoformat()), State()
    st.seen[FEED.url] = []  # الموقع مقروء سابقاً، فالمنشور «جديد» عليه
    run_once(T0, [], st, w.deps(), aggregators=[FEED])
    (p,) = st.programs.items.values()
    assert program_status(p, T0.date()) == "listed"
    assert not any(c == "group" and "سيمنس" in t for c, t in w.sent)
    assert "تاريخ النشر: " in w.classified[0]


def test_fresh_aggregator_post_saying_open_is_announced():
    w, st = _agg_world(T0.date().isoformat()), State()
    st.seen[FEED.url] = []
    run_once(T0, [], st, w.deps(), aggregators=[FEED])
    assert any(c == "group" and "سيمنس" in t for c, t in w.sent)


# ---------- ٩ و١٠: نص التذكير، ولا تذكير مع التنبيه في نفس الجولة ----------

def _prog(closes, sources=("https://ncgr.gov.sa/coop",)):
    return Program("ncgr:student:2026-10", "ncgr", "student", "coop", "2026-10", "t", "t", list(sources),
                   {"closes": {"value": closes, "quote": "q"}}, [], ["m"])


def test_reminder_says_two_days_in_arabic():
    (msg_id, text), = reminders([_prog("2026-10-24")], date(2026, 10, 22), {"ncgr": "المركز"})
    assert msg_id.startswith("rem3:") and text.startswith("⏰ باقي يومين على إغلاق المركز")


def test_no_closing_reminder_in_the_same_run_as_the_alert():
    w, st = World(), State()
    w.pages = {GOV.channels[0].url: ["برنامج التدريب التعاوني يقفل 28 أكتوبر"]}
    w.verdicts["يقفل 28"] = lambda: Verdict("coop", "m", {"closes": Field(date(2026, 10, 28), "يقفل 28 أكتوبر")})
    st.seen[GOV.channels[0].url] = []
    run_once(T0, [GOV], st, w.deps())
    group = [t for c, t in w.sent if c == "group" and not t.startswith("☀️")]  # بلا الملخص الصباحي
    assert len(group) == 1 and "باقي يومين على الإغلاق" in group[0]
    run_once(T0 + timedelta(hours=2), [GOV], st, w.deps())
    assert not any("⏰" in t for c, t in w.sent)


# ---------- ١١ و١٢: المصدر الرسمي قبل موقع التجميع ----------

def test_alert_cites_official_source_and_labels_aggregator_only_source():
    p = _prog("2026-10-31", ["https://ncgr.gov.sa/coop"])
    assert "المصدر: https://ncgr.gov.sa/coop" in render(Change("new", p.key), p, "المركز", date(2026, 10, 22), AGG)
    p.sources = ["https://agg.example.com/post-1"]
    assert "المصدر (موقع تجميع): https://agg.example.com/post-1" in render(Change("new", p.key), p, "المركز",
                                                                           date(2026, 10, 22), AGG)


def test_run_puts_official_sources_before_aggregator_ones():
    st = State()
    p = _prog("2026-10-31", ["https://agg.example.com/post-1", "https://careers.ncgr.gov.sa/coop"])
    st.programs.items[p.key] = p
    run_once(T0, [], st, World().deps(), aggregators=[FEED])
    assert p.sources == ["https://careers.ncgr.gov.sa/coop", "https://agg.example.com/post-1"]


def test_site_apply_button_gets_official_url_only():
    st = State()
    p = _prog("2026-10-31", ["https://agg.example.com/post-1"])
    st.programs.items[p.key] = p
    res = build_results(st, [GOV], T0, AGG)
    assert res["programs"][0]["official_url"] is None
    p.fields["apply_url"] = {"value": "https://jadarat.sa/coop", "quote": "q"}
    assert build_results(st, [GOV], T0, AGG)["programs"][0]["official_url"] == "https://jadarat.sa/coop"
    p.fields["apply_url"] = {"value": "https://agg.example.com/apply", "quote": "q"}
    p.sources.append("https://ncgr.gov.sa/coop")
    assert build_results(st, [GOV], T0, AGG)["programs"][0]["official_url"] == "https://ncgr.gov.sa/coop"


# ---------- ٦: الشهادة الناقصة ----------

def test_issuer_link_is_read_from_certificate_bytes():
    url = b"http://secure.globalsign.com/cacert/gsgccr46ovtlsca2025.crt"
    der = b"\x30\x82junk" + _CA_ISSUERS + bytes([len(url)]) + url + b"\x30\x0dmore"
    assert _issuer_url(der) == url.decode()
    assert _issuer_url(b"no issuer here") is None


# ---------- ١٧: الإيصالات لا تكبر بلا حد ----------

def test_outbox_trims_oldest_receipts_and_skip_blocks_later_sending():
    ob = Outbox()
    ob.receipts = {f"m{i}": i for i in range(10)}
    ob.trim(4)
    assert list(ob.receipts) == ["m6", "m7", "m8", "m9"]
    ob.skip("rem3:x")
    ob.enqueue("rem3:x", "group", "نص", datetime(2026, 10, 22, 10, 0))
    assert "rem3:x" not in ob.pending
