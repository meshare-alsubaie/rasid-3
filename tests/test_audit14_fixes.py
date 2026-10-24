"""اختبارات إصلاح الفحص الرابع عشر (٢٤ أكتوبر): إعلان شركة تابعة لا يُنسب لجهتها الأم المذكورة في العنوان."""
from pathlib import Path

from rasid.classify.schema import Field, Verdict
from rasid.entities import load_entities
from rasid.match import shares_name
from rasid.run import _resolver

ES = load_entities(Path(__file__).resolve().parents[1] / "config/entities.yaml")
BY_ID = {e.id: e for e in ES}


def _text(title: str) -> str:
    return f"المصدر: موقع تجميع (ت)\nالرابط: https://agg.example.com/1\n\nعنوان الإعلان: {title}\n\nالنص:\n..."


def _coop(named: str) -> Verdict:
    return Verdict("coop", "m", {"entity_name": Field(named, "q")})


def test_subsidiary_named_by_the_classifier_is_not_its_parent():
    resolve = _resolver(ES)
    owner = resolve(_coop("الشركة الوطنية للخدمات الأمنية – سيف (SAFE)"),
                    _text("شركة سيف إحدى شركات صندوق الاستثمارات العامة تعلن برنامج التدريب التعاوني"))
    assert owner is not None and owner[0].startswith("x:") and owner[0] != "pif"


def test_short_or_variant_name_still_resolves_through_the_title():
    resolve = _resolver(ES)
    assert resolve(_coop("علم"), _text("شركة علم تعلن التدريب التعاوني"))[0] == "elm"
    assert resolve(_coop(""), _text("شركة علم تعلن التدريب التعاوني"))[0] == "elm"


def test_shares_name_ignores_generic_words():
    assert shares_name("علم", BY_ID["elm"])
    assert not shares_name("الشركة الوطنية للخدمات الأمنية", BY_ID["nca"])  # «الوطنية» وحدها لا تكفي
    assert not shares_name("الشركة الوطنية للخدمات الأمنية – سيف (SAFE)", BY_ID["pif"])


# ---------- رابط تقديم لا يعمل إلا داخل جلسة الموقع ----------
SESSION = "https://career.elm.sa/talentcommunity/apply/1373472157/?locale=en_GB"


def test_session_only_apply_link_is_not_kept():
    from datetime import date

    from rasid.run import State, _good_apply, run_once
    from tests.test_audit_fixes import ELM
    from tests.test_programs import T0
    from tests.test_run import World
    assert not _good_apply("Apply now", SESSION, "https://career.elm.sa/elm/job/x/1/")
    w, st = World(), State()
    w.pages[ELM.channels[0].url] = ["برنامج علم للتدريب التعاوني، التقديم حتى 4 نوفمبر"]
    w.verdicts["برنامج علم"] = lambda: Verdict("coop", "m", {"closes": Field(date(2026, 11, 4), "q"),
                                                          "apply_url": Field(SESSION, "q")})
    run_once(T0, [ELM], st, w.deps())
    (p,) = st.programs.items.values()
    assert "apply_url" not in p.fields  # الموقع يعرض صفحة الإعلان نفسها (المصدر) وفيها زر التقديم


def test_stored_session_only_link_is_cleaned():
    from rasid.programs import Program
    from rasid.run import State, run_once
    from tests.test_programs import T0
    from tests.test_run import World
    st = State()
    p = Program("elm:job:x", "elm", "job", "job", "", T0.isoformat(), T0.isoformat(),
                ["https://career.elm.sa/elm/job/x/1/"])
    p.fields["apply_url"] = {"value": SESSION, "quote": "Apply"}
    st.programs.items[p.key] = p
    run_once(T0, [], st, World().deps())
    assert "apply_url" not in st.programs.items["elm:job:x"].fields


def test_deleted_successfactors_posting_is_an_error_page():
    from rasid.fetch import Block, junk_reason
    u = "https://career23.sapsf.com/sfcareer/jobreqcareer?jobId=4306&company=saudiara02"
    for text in ("- An error occurred while processing your request. Please go back to your original page.",
                 "This job cannot be viewed at the moment. It has either been deleted or is no longer available."):
        assert junk_reason([Block(text), Block("SuccessFactors")], u, u).startswith("الصفحة رسالة خطأ")
