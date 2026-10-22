"""اختبارات إصلاح الفحص السابع (٢٢ أكتوبر): رابط قناة التواصل لا يصير رابط التقديم."""
from datetime import date

from rasid.classify.schema import Field, Verdict
from rasid.fetch import Block
from rasid.run import State, run_once
from tests.test_audit2_fixes import _prog
from tests.test_audit6_fixes import POST
from tests.test_audit_fixes import ELM, FEED
from tests.test_run import T0, World

WA = "https://whatsapp.com/channel/0029VaCjpQ3FSAtBdd2BK20s"


def _tm_world(verdict):
    """منشور تجميع مثل وظائف تي إم: «للتقديم (اضغط هنا)» لقناة واتساب، ورابط التقديم الحقيقي بعده."""
    w = World()
    w.pages[FEED.url] = [Block("شركة علم تطلق برنامج التدريب التعاوني", POST)]
    w.pages[POST] = ["شركة علم تعلن التدريب التعاوني"]
    w.links[POST] = [("للتقديم (اضغط هنا)", WA), ("اضغط هنا للتقديم", "https://career.elm.sa/coop")]
    w.verdicts["شركة علم تعلن"] = verdict
    return w


def test_social_channel_never_reaches_the_classifier_as_an_apply_link():
    w = _tm_world(lambda: Verdict("coop", "m", {"entity_name": Field("شركة علم", "q")}))
    st = State()
    run_once(T0, [ELM], st, w.deps(), aggregators=[FEED])
    assert WA not in w.classified[-1]
    (p,) = st.programs.items.values()
    assert p.fields["apply_url"]["value"] == "https://career.elm.sa/coop"


def test_model_social_apply_link_is_replaced_by_the_real_one():
    w = _tm_world(lambda: Verdict("coop", "m", {"apply_url": Field(WA, "q"), "entity_name": Field("شركة علم", "q"),
                                                "closes": Field(date(2026, 11, 4), "q")}))
    st = State()
    run_once(T0, [ELM], st, w.deps(), aggregators=[FEED])
    (p,) = st.programs.items.values()
    assert p.fields["apply_url"]["value"] == "https://career.elm.sa/coop"
    assert not any(WA in t for _, t in w.sent)


def test_stored_social_apply_link_is_cleaned_on_the_next_run():
    st, w = State(), World()
    p = _prog("2026-10-28")
    p.fields["apply_url"] = {"value": WA, "quote": "للتقديم (اضغط هنا)"}
    st.programs.items[p.key] = p
    run_once(T0, [], st, w.deps())
    assert "apply_url" not in p.fields
