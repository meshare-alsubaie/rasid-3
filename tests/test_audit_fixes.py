"""اختبارات إصلاحات فحص ٢٢ أكتوبر: كل اختبار يثبّت سبباً حقيقياً فوّت إعلاناً أو ضلّل المستخدم."""
from datetime import date, datetime, timedelta

import httpx
import respx

from rasid.classify.chain import CONTEXT_MARK, Pending, strong_keywords
from rasid.classify.schema import Field, Verdict
from rasid.dates import RIYADH
from rasid.entities import Aggregator, Channel, Entity
from rasid.fetch import Block, fetch, junk_reason
from rasid.match import find_entity, outside_id
from rasid.notify.templates import reminders
from rasid.programs import Program, Programs, program_status
from rasid.run import State, run_once
from tests.test_run import ARAMCO, T0, World, coop

ELM = Entity("elm", "علم", 3, 2, [Channel("web", "https://career.elm.sa/go/coop")], aliases=["شركة علم", "Elm"])


# ---------- السياق: الجديد يصل للمصنّف ومعه بقية الصفحة ----------

def test_new_line_reaches_classifier_with_page_context():
    w = World()
    w.pages["https://aramco/x"] = ["برنامج التدريب التعاوني لطلاب الجامعات"]
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    w.pages["https://aramco/x"].append("التقديم من 26 أكتوبر إلى 2 نوفمبر")
    run_once(T0 + timedelta(hours=3), [ARAMCO], st, w.deps())
    text = w.classified[-1]
    new, ctx = text.split(CONTEXT_MARK)
    assert "التقديم من 26 أكتوبر" in new and "التدريب التعاوني" in ctx


def test_strong_keywords_ignore_context_part():
    assert strong_keywords(f"الجديد في الصفحة:\nتاريخ آخر زيارة\n\n{CONTEXT_MARK}\nالتدريب التعاوني") is None
    assert strong_keywords("الجديد في الصفحة:\nفتح باب التدريب التعاوني") == "coop"


# ---------- فتح روابط التدريب الجديدة ----------

def test_new_training_link_is_opened_and_its_dates_alert():
    w = World()
    w.pages["https://career.elm.sa/go/coop"] = ["فرص التدريب في علم"]
    st = State()
    run_once(T0, [ELM], st, w.deps())
    post = "https://career.elm.sa/job/coop-2027"
    w.links["https://career.elm.sa/go/coop"] = [("Elm Co-op Training Program (January Intake)", post)]
    w.pages[post] = ["برنامج علم للتدريب التعاوني، التقديم مفتوح حتى 4 نوفمبر"]
    w.verdicts["حتى 4 نوفمبر"] = lambda: Verdict("coop", "m", {"closes": Field(date(2026, 11, 4), "q")})
    run_once(T0 + timedelta(hours=3), [ELM], st, w.deps())
    assert post in w.fetched
    assert any(c == "group" and "علم" in t and "نوفمبر" in t for c, t in w.sent)
    run_once(T0 + timedelta(hours=6), [ELM], st, w.deps())
    assert w.fetched.count(post) == 1  # الرابط لا يُفتح مرتين


def test_first_sight_opens_only_links_with_current_year():
    w = World()
    url = "https://career.elm.sa/go/coop"
    w.pages[url] = ["فرص التدريب في علم"]
    w.links[url] = [("برنامج التدريب التعاوني 2027", "https://career.elm.sa/a"),
                    ("التدريب الصيفي", "https://career.elm.sa/b"),
                    ("تدريب في موقع آخر 2027", "https://other.example.com/c")]
    w.pages["https://career.elm.sa/a"] = ["تفاصيل"]
    run_once(T0, [ELM], State(), w.deps())
    assert "https://career.elm.sa/a" in w.fetched
    assert "https://career.elm.sa/b" not in w.fetched and "https://other.example.com/c" not in w.fetched


# ---------- مواقع التجميع ----------

FEED = Aggregator("موقع تجميع", "https://agg.example.com/feed")


def _agg_world(title, post_text, verdict):
    w = World()
    post = "https://agg.example.com/post-1"
    w.pages[FEED.url] = [Block(title, post), Block("وظائف مبيعات في الرياض", "https://agg.example.com/post-2")]
    w.pages[post] = [post_text]
    w.verdicts[post_text[:10]] = verdict
    return w, post


def test_aggregator_post_is_attributed_to_matching_entity():
    v = lambda: Verdict("coop", "m", {"closes": Field(date(2026, 11, 4), "q"),  # noqa: E731
                                      "entity_name": Field("شركة علم", "q")})
    w, post = _agg_world("شركة علم تطلق برنامج التدريب التعاوني 2027", "شركة علم تعلن التدريب التعاوني", v)
    st = State()
    run_once(T0, [ELM], st, w.deps(), aggregators=[FEED])
    assert [p.entity_id for p in st.programs.items.values()] == ["elm"]
    assert post in st.programs.items["elm:student:seen-2026-10-26"].sources
    assert "https://agg.example.com/post-2" not in w.fetched  # ليس إعلان تدريب
    assert any(c == "group" and "علم" in t for c, t in w.sent)


def test_aggregator_unknown_entity_becomes_outside_program():
    v = lambda: Verdict("coop", "m", {"accepting_now": Field(True, "q"),  # noqa: E731
                                      "entity_name": Field("شركة سيمنس", "q")})
    w, _ = _agg_world("شركة سيمنس تفتح التدريب التعاوني", "شركة سيمنس تفتح باب التسجيل", v)
    st = State()
    run_once(T0, [ELM], st, w.deps(), aggregators=[FEED])
    (p,) = st.programs.items.values()
    assert p.entity_id == outside_id("شركة سيمنس") and program_status(p, T0.date()) == "open"
    assert any(c == "group" and "سيمنس" in t and "خارج قائمة راصد" in t for c, t in w.sent)


def test_aggregator_job_from_unknown_entity_is_dropped():
    v = lambda: Verdict("job", "m", {"entity_name": Field("شركة مجهولة", "q")})  # noqa: E731
    w, _ = _agg_world("شركة مجهولة تعلن وظائف وتدريب", "شركة مجهولة تعلن وظائف", v)
    st = State()
    run_once(T0, [ELM], st, w.deps(), aggregators=[FEED])
    assert st.programs.items == {}
    assert st.meta["verdicts"][-1]["kind"] == "job"


def test_entity_matching_prefers_longest_and_skips_short_official_names():
    nca = Entity("nca", "الهيئة الوطنية للأمن السيبراني", 3, 1, [])
    assert find_entity("أعلنت الهيئة الوطنية للأمن السيبراني", [ELM, nca]) is nca
    assert find_entity("برنامج في علم البيانات", [ELM, nca]) is None
    assert find_entity("شركه علم تعلن", [ELM, nca]) is ELM
    taqnia = Entity("taqnia", "تقنية", 4, 1, [], aliases=["شركة تقنية"])
    assert find_entity("شركة ناشئة في تقنية المعلومات", [taqnia]) is None
    assert find_entity("شركة تقنية تعلن برنامجها", [taqnia]) is taqnia


def test_real_entity_file_attributes_common_announcement_wordings():
    from pathlib import Path
    from rasid.entities import load_entities
    es = load_entities(Path(__file__).resolve().parent.parent / "config/entities.yaml")
    cases = {"أعلنت أرامكو عن برنامج التدريب التعاوني": "aramco", "شركة علم تعلن تدريب تعاوني": "elm",
             "سدايا تفتح التسجيل": "sdaia", "إس تي سي تعلن": "stc", "ساتورب تعلن برنامج": "satorp",
             "تدريب تعاوني في الشركة السعودية للمعلومات الائتمانية (سمة)": "simah",
             "المركز الوطني لنظم الموارد الحكومية يعلن": "ncgr", "شركة ناشئة في تقنية المعلومات": None}
    for text, want in cases.items():
        got = find_entity(text, es)
        assert (got.id if got else None) == want, text


# ---------- التنبيهات ----------

def test_safety_net_alerts_live_program_that_was_never_alerted_once():
    w = World()
    st = State()
    st.programs.merge("aramco", coop(), "https://aramco/x", T0 - timedelta(days=20))
    run_once(T0 - timedelta(days=4), [ARAMCO], st, w.deps())
    run_once(T0 - timedelta(days=4, hours=-3), [ARAMCO], st, w.deps())
    alerts = [t for c, t in w.sent if c == "group" and "أعلنت المواعيد" in t]
    assert len(alerts) == 1 and "أرامكو" in alerts[0]


def _prog(opens=None, closes=None, **extra):
    f = {k: {"value": v, "quote": "q"} for k, v in (("opens", opens), ("closes", closes)) if v}
    f.update(extra)
    return Program("aramco:student:2026-10", "aramco", "student", "coop", "2026-10", "", "", [], f)


def test_reminders_day_before_and_on_opening_day():
    p = _prog("2026-10-26", "2026-11-02")
    assert [i for i, _ in reminders([p], date(2026, 10, 25), {"aramco": "أرامكو"})] == ["open1:" + p.key]
    (mid, txt), = reminders([p], date(2026, 10, 26), {"aramco": "أرامكو"})
    assert mid == "open0:" + p.key and "اليوم يفتح" in txt
    assert reminders([p], date(2026, 10, 24), {"aramco": "أرامكو"}) == []


def test_accepting_now_without_dates_is_open_for_a_month_only():
    p = _prog(accepting_now={"value": True, "quote": "فتح باب التسجيل", "at": "2026-10-01T10:00:00+03:00"})
    assert program_status(p, date(2026, 10, 20)) == "open"
    assert program_status(p, date(2026, 11, 5)) == "listed"
    assert program_status(_prog(), date(2026, 10, 20)) == "listed"


def test_permanent_page_saying_registration_opened_alerts():
    ps = Programs()
    ps.merge("sdaia", Verdict("coop", "m", {}), "u", T0)
    _, change = ps.merge("sdaia", Verdict("coop", "m", {"accepting_now": Field(True, "بدء استقبال الطلبات")}),
                         "u", T0 + timedelta(days=1))
    assert change.kind == "opened"


def test_digest_lists_upcoming_programs():
    w = World(); w.verdicts["التعاوني"] = coop
    st = State()
    run_once(T0 - timedelta(days=5), [ARAMCO], st, w.deps())
    morning = datetime(2026, 10, 22, 7, 5, tzinfo=RIYADH)
    run_once(morning, [ARAMCO], st, w.deps())
    digest = [t for c, t in w.sent if c == "group" and "الصباحي" in t][-1]
    assert "يفتح قريباً: أرامكو (بعد 4 أيام)" in digest


def test_dead_source_is_reported_in_daily_report_not_nightly_alerts():
    w = World(); w.broken.add("https://aramco/x")
    st = State()
    for h in range(0, 24 * 5, 3):
        run_once(T0 + timedelta(hours=h), [ARAMCO], st, w.deps())
    assert not any("مصدر لا يُقرأ منذ" in t for _, t in w.sent)
    assert any(c == "owner" and "لا تُقرأ منذ ٣ أيام" in t for c, t in w.sent)


def test_source_removed_from_file_leaves_health_report_and_home_list():
    from rasid.run import saudi_list
    w = World(); w.broken.add("https://aramco/x")
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    assert "https://aramco/x" in saudi_list(st)
    run_once(T0 + timedelta(hours=2), [Entity("aramco", "أرامكو السعودية", 5, 1, [])], st, w.deps())
    assert st.health == {} and saudi_list(st) == []


# ---------- الطابور والسجل ----------

def test_queue_item_older_than_a_week_is_dropped_and_logged():
    w = World(); w.verdicts["التعاوني"] = Pending("متوقف")
    st = State()
    run_once(T0, [ARAMCO], st, w.deps())
    run_once(T0 + timedelta(days=8), [ARAMCO], st, w.deps())
    assert st.queue.items == {}
    assert "انتهت مهلة الطابور" in st.meta["verdicts"][-1]["why"]


def test_verdict_log_keeps_kind_and_rejection_reasons():
    w = World()
    v = coop(); v.notes = ["[المصنّف][قارئ] جواب مرفوض: اقتباس غير موجود"]
    w.verdicts["التعاوني"] = v
    st = State()
    rep = run_once(T0, [ARAMCO], st, w.deps())
    row = st.meta["verdicts"][-1]
    assert row["kind"] == "coop" and "اقتباس" in row["why"] and rep.kinds["coop"] == 1


# ---------- صفحات تردّ بنجاح لكنها غير صالحة ----------

URL = "https://careers.example.gov.sa/go/coop/123"


@respx.mock
def test_error_page_with_status_200_is_a_failure():
    respx.get(URL).mock(return_value=httpx.Response(
        200, html="<html><body><main><p>عزيزي المستفيد، حدث خطأ ما في طلبك، نرجو تزويدنا برقم الطلب 99</p></main></body></html>"))
    r = fetch(Channel("web", URL), httpx.Client())
    assert not r.ok and r.junk and "رسالة خطأ" in r.error_ar


def test_login_and_home_redirects_and_js_shells_are_junk():
    b = [Block("صفحة التحقق من الهوية عبر النفاذ الوطني الموحد")]
    assert "تسجيل دخول" in junk_reason(b, "https://x.gov.sa/Coop", "https://x.gov.sa/en/Nafath-Verification?r=1")
    assert "الرئيسية" in junk_reason(b, "https://careers.x.gov.sa/go/coop/1", "https://www.x.gov.sa/ar-sa/Pages/default.aspx")
    assert "جافاسكربت" in junk_reason([Block("You need to enable JavaScript to run this app.")], URL, URL)
    assert "جافاسكربت" in junk_reason([Block("تم العثور على {{ totalItems }} وظيفة")], URL, URL)
    assert junk_reason([Block("لا توجد حاليًا أي مناصب شاغرة مطابقة لهذه الفئة")], URL, URL) is None
    assert junk_reason(b, "https://x.gov.sa/", "https://x.gov.sa/ar/") is None


@respx.mock
def test_gov_banner_lines_are_dropped_so_empty_page_is_detected():
    html = ("<html><body><main><p>كيف تتحقق</p><p>جميع روابط المواقع الرسمية التابعة للجهات الحكومية تنتهي بـ gov.sa</p>"
            "<p>تاريخ آخر تعديل: ٠٣/٠٩/٢٠٢٦</p></main></body></html>")
    respx.get(URL).mock(return_value=httpx.Response(200, html=html))
    assert not fetch(Channel("web", URL), httpx.Client()).ok


@respx.mock
def test_json_response_becomes_readable_text():
    respx.get(URL).mock(return_value=httpx.Response(
        200, json=[{"title": "فتح التسجيل في التدريب التعاوني", "content": "<p>للطلاب والطالبات حتى نهاية الشهر</p>"}]))
    r = fetch(Channel("web", URL), httpx.Client())
    assert r.ok and [b.text for b in r.blocks] == ["فتح التسجيل في التدريب التعاوني", "للطلاب والطالبات حتى نهاية الشهر"]
