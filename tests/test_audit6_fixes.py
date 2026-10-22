"""اختبارات إصلاحات الفحص السادس (٢٢ أكتوبر): المواعيد، رابط التقديم، التلميح المكرر، قِدم منشور الطابور."""
from datetime import date, datetime, timedelta
from pathlib import Path

from rasid.classify.chain import Pending
from rasid.classify.schema import Field, Verdict
from rasid.entities import Channel, Entity
from rasid.fetch import Block
from rasid.run import AGG, State, _apply_link, run_once
from relay.home_agent import should_trigger_engine
from tests.test_audit_fixes import ELM, FEED
from tests.test_run import ARAMCO, T0, World

ROOT = Path(__file__).resolve().parents[1]
POST = "https://agg.example.com/post-1"


def _alerts(w):
    """رسائل القروب عدا الملخص الصباحي."""
    return [t for c, t in w.sent if c == "group" and not t.startswith("☀️")]


# ---------- ١: المحرّك كل ساعة، والجهاز يتدخل بعد موعد واحد ساقط ----------

def test_engine_runs_hourly_and_home_agent_covers_one_dropped_slot():
    assert 'cron: "17 * * * *"' in (ROOT / ".github/workflows/engine.yml").read_text(encoding="utf-8")
    assert should_trigger_engine((T0 - timedelta(minutes=108)).isoformat(), T0)
    assert not should_trigger_engine((T0 - timedelta(minutes=48)).isoformat(), T0)


# ---------- ٢: رابط التقديم من روابط الإعلان إذا لم يذكره النموذج ----------

def test_apply_link_skips_same_site_and_social_links():
    text = (f"الرابط: {POST}\n\nروابط التقديم في الإعلان:\nللتقديم: https://agg.example.com/other\n"
            "قدم الآن عبر واتساب: https://wa.me/966\nاضغط هنا للتقديم: https://jobs.oraclecloud.com/590")
    f = _apply_link(text, POST)
    assert f.value == "https://jobs.oraclecloud.com/590" and f.quote in text


def test_aggregator_post_gets_its_apply_link():
    w = World()
    w.pages[FEED.url] = [Block("شركة علم تطلق برنامج التدريب التعاوني", POST)]
    w.pages[POST] = ["شركة علم تعلن التدريب التعاوني"]
    w.links[POST] = [("واتساب", "https://wa.me/966"), ("اضغط هنا للتقديم", "https://jobs.oraclecloud.com/590")]
    w.verdicts["شركة علم تعلن"] = lambda: Verdict("coop", "m", {"closes": Field(date(2026, 11, 4), "q"),
                                                                "entity_name": Field("شركة علم", "q")})
    st = State()
    run_once(T0, [ELM], st, w.deps(), aggregators=[FEED])
    (p,) = st.programs.items.values()
    assert p.fields["apply_url"]["value"] == "https://jobs.oraclecloud.com/590"
    assert "روابط التقديم في الإعلان" in w.classified[-1]


def test_model_apply_link_is_kept():
    w = World()
    w.pages[FEED.url] = [Block("شركة علم تطلق برنامج التدريب التعاوني", POST)]
    w.pages[POST] = ["شركة علم تعلن التدريب التعاوني"]
    w.links[POST] = [("للتقديم", "https://jobs.oraclecloud.com/590")]
    w.verdicts["شركة علم تعلن"] = lambda: Verdict("coop", "m", {"apply_url": Field("https://career.elm.sa/a", "q"),
                                                                "entity_name": Field("شركة علم", "q")})
    st = State()
    run_once(T0, [ELM], st, w.deps(), aggregators=[FEED])
    (p,) = st.programs.items.values()
    assert p.fields["apply_url"]["value"] == "https://career.elm.sa/a"


# ---------- ٣: التلميح لا يُرسل مع تنبيه مؤكد لنفس البرنامج ----------

def test_hint_is_dropped_when_a_firm_alert_for_the_same_program_waits_with_it():
    news, prog = "https://nca/news", "https://nca/programs"
    nca = Entity("nca", "الأمن السيبراني", 3, 2, [Channel("web", news), Channel("web", prog)])
    w = World()
    w.pages[news], w.pages[prog] = ["خبر قديم"], ["صفحة البرامج"]
    st = State()
    run_once(T0 - timedelta(hours=2), [nca], st, w.deps())
    w.pages[news] = ["خبر قديم", "إطلاق برنامج تدريبي للطلاب"]
    w.pages[prog] = ["صفحة البرامج", "البرنامج التدريبي للمرحلة الجامعية"]
    w.verdicts["إطلاق برنامج"] = lambda: Verdict("hint", "m")
    w.verdicts["للمرحلة الجامعية"] = lambda: Verdict("university", "m")
    run_once(T0, [nca], st, w.deps())
    group = _alerts(w)
    assert len(group) == 1 and "جديد" in group[0]
    assert not any(k.startswith(("hint:", "push:hint:")) for k in st.outbox.pending)


# ---------- ٤: الطابور يحفظ قِدم المنشور وهدوء أول مرة ----------

def test_queued_old_aggregator_post_does_not_reopen_its_program():
    old = (T0.date() - timedelta(days=37)).isoformat()
    text = (f"المصدر: موقع تجميع (ت)\nالرابط: {POST}\nتاريخ النشر: {old}\n\n"
            "عنوان الإعلان: شركة علم التدريب التعاوني\n\nالنص:\nشركة علم تفتح التدريب التعاوني")
    st, w = State(), World()
    st.queue.add("re:x", AGG, POST, text, "إعادة فحص بالنموذج الأساسي", T0 - timedelta(hours=13), recheck_of="coop")
    w.verdicts["تفتح التدريب"] = lambda: Verdict("coop", "confirmer", {"accepting_now": Field(True, "q"),
                                                                      "entity_name": Field("شركة علم", "q")})
    run_once(T0, [ELM], st, w.deps(), aggregators=[])
    (p,) = st.programs.items.values()
    assert "accepting_now" not in p.fields and not _alerts(w)


def test_first_sight_quiet_survives_the_queue():
    w, st = World(), State()
    w.verdicts["التعاوني"] = Pending("كل النماذج متعطلة")
    run_once(T0, [ARAMCO], st, w.deps())
    assert next(iter(st.queue.items.values())).quiet
    w.verdicts["التعاوني"] = lambda: Verdict("coop", "m")  # صفحة دائمة بلا موعد
    run_once(T0 + timedelta(hours=2), [ARAMCO], st, w.deps())
    assert st.programs.items and not _alerts(w)
