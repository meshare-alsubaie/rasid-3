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
