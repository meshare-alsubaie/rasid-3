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


def test_renamed_entities_match_their_current_names():
    from rasid.match import find_entity
    for text, want in (("المؤسسة العامة للتأمينات الاجتماعية تعلن التدريب التعاوني", "pension"),
                       ("الهيئة العامة لتنظيم الإعلام تعلن التدريب التعاوني", "gcam"),
                       ("الهيئة السعودية للمياه تعلن التدريب التعاوني", "swcc"),
                       ("وكالة الفضاء السعودية تعلن التدريب التعاوني", "ssc")):
        assert find_entity(text, ES).id == want


# ---------- مراجعة مستقلة: شركة تابعة اسمها فيه اسم الأم، واسم بحرف جر أو بالإنجليزية ----------

def test_subsidiary_containing_the_parent_name_is_its_own_entity():
    resolve = _resolver(ES)
    for named, title in (("الراجحي للتأمين التعاوني (تكافل الراجحي)", "برنامج تمهير لدى تكافل الراجحي"),
                         ("الراجحي المالية", "الراجحي المالية تعلن التدريب التعاوني"),
                         ("أرامكو ديجيتال", "أرامكو ديجيتال تعلن التدريب التعاوني")):
        owner = resolve(_coop(named), _text(title))
        assert owner is not None and owner[0].startswith("x:"), named
    for named, want in (("مصرف الراجحي", "alrajhi"), ("وزارة المالية", "mof"), ("التعاونية للتأمين", "tawuniya"),
                        ("أرامكو السعودية", "aramco")):
        assert resolve(_coop(named), _text("التدريب التعاوني"))[0] == want, named


def test_prefixed_or_latin_names_still_resolve_through_the_title():
    resolve = _resolver(ES)
    assert resolve(_coop("لأرامكو السعودية"), _text("أرامكو السعودية تفتح التدريب التعاوني"))[0] == "aramco"
    assert resolve(_coop("Saudi Electricity Company"),
                   _text("الشركة السعودية للكهرباء تعلن التدريب التعاوني"))[0] == "sec"
    assert not shares_name("صندوق التنمية الصناعية", BY_ID["adf"])  # «التنمية» كلمة عامة


def test_training_start_without_a_year_follows_the_application_window():
    from datetime import date

    from rasid.classify.schema import check_verdict
    text = "بداية التقديم: 26 أكتوبر 2026. نهاية التقديم: 2 نوفمبر 2026. مباشرة التدريب: 11 يناير"
    d = {"kind": "coop", "kind_quote": "بداية التقديم",
         "opens": {"value": "2026-10-26", "quote": "بداية التقديم: 26 أكتوبر 2026"},
         "closes": {"value": "2026-11-02", "quote": "نهاية التقديم: 2 نوفمبر 2026"},
         "training_starts": {"value": "2026-01-11", "quote": "مباشرة التدريب: 11 يناير"}}
    assert check_verdict(d, text, "m")[0].fields["training_starts"].value == date(2027, 1, 11)
    text += " 2026"  # السنة مكتوبة في الاقتباس: لا تُغيَّر
    d["training_starts"]["quote"] = "مباشرة التدريب: 11 يناير 2026"
    assert check_verdict(d, text, "m")[0].fields["training_starts"].value == date(2026, 1, 11)


def test_new_short_aliases_resolve():
    resolve = _resolver(ES)
    for named, eid in [("هيئة حقوق الإنسان", "hrc"), ("الهلال الأحمر", "srca"), ("إي واي", "ey_sa"),
                       ("هيئة تنمية الصادرات", "saudi_exports"), ("شركة زين", "zain_ksa")]:
        assert resolve(_coop(named), _text("تدريب تعاوني"))[0] == eid, named


def test_english_subsidiary_names_do_not_go_to_the_parent():
    resolve = _resolver(ES)
    safe = _text("شركة سيف إحدى شركات صندوق الاستثمارات العامة تعلن برنامج التدريب التعاوني")
    for named in ["SAFE", "SAFE Company", "Sela", "Savvy Games Group"]:
        assert resolve(_coop(named), safe)[0] != "pif", named
    for named in ["Takaful Al Rajhi", "Al Rajhi Takaful", "Al Rajhi Capital"]:
        assert resolve(_coop(named), _text("برنامج تمهير لدى تكافل الراجحي"))[0] != "alrajhi", named


def test_subsidiary_in_the_title_is_not_the_parent():
    resolve = _resolver(ES)
    assert resolve(_coop(""), _text("الراجحي المالية تعلن التدريب التعاوني")) is None
    assert resolve(_coop(""), _text("أرامكو ديجيتال تعلن التدريب التعاوني")) is None
    assert resolve(_coop(""), _text("مصرف الراجحي يعلن التدريب التعاوني لتخصصات المالية"))[0] == "alrajhi"
    assert resolve(_coop("شركة الراجحي المصرفية للاستثمار"), _text("تدريب تعاوني"))[0] == "alrajhi"


def test_prefixed_or_english_name_of_an_entity_without_english_names():
    resolve = _resolver(ES)
    assert resolve(_coop("لوزارة المالية"), _text("وزارة المالية تفتح التدريب التعاوني"))[0] == "mof"
    assert resolve(_coop("Ministry of Finance"), _text("وزارة المالية تفتح التدريب التعاوني"))[0] == "mof"
    assert resolve(_coop("Saudi Pro League"), _text("SPL تعلن التدريب التعاوني"))[0] != "spl"
    assert resolve(_coop("Zain Kuwait"), _text("Zain Kuwait training"))[0] != "zain_ksa"


def test_prefixed_or_long_subsidiary_names_are_not_the_parent():
    resolve = _resolver(ES)
    for named in ["لأرامكو ديجيتال", "للراجحي المالية", "بالراجحي كابيتال", "والراجحي المالية",
                  "Al Rajhi Company for Cooperative Insurance", "Al Rajhi Cooperative Insurance Company"]:
        owner = resolve(_coop(named), _text("تدريب تعاوني"))
        assert owner is not None and owner[0].startswith("x:"), named
    for named, eid in [("للراجحي", "alrajhi"), ("Al Rajhi Banking and Investment Corporation", "alrajhi"),
                       ("لأرامكو السعودية", "aramco")]:
        assert resolve(_coop(named), _text("تدريب تعاوني"))[0] == eid, named


def test_field_of_study_before_the_name_is_not_a_subsidiary():
    resolve = _resolver(ES)
    for title, eid in [("التدريب التعاوني لتخصص المالية – أرامكو السعودية", "aramco"),
                       ("تدريب تعاوني تخصصات المالية والتأمين | مصرف الراجحي", "alrajhi")]:
        assert resolve(_coop(""), _text(title))[0] == eid, title
    assert resolve(_coop(""), _text("برنامج تمهير لدى تكافل الراجحي")) is None
