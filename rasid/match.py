"""مطابقة اسم جهة مذكور في إعلان (من مواقع التجميع) بجهة من القائمة. بلا ذكاء: أطول اسم مطابق يفوز."""
from __future__ import annotations

import re

from rasid.entities import Entity

_ARABIC = re.compile(r"[؀-ۿ]")
_DIACRITICS = re.compile(r"[ً-ْـ]")
_LETTERS = str.maketrans("أإآىة", "ااايه")
_GENERIC = re.compile(r"^(?:ال)?(?:شركه|مجموعه|هيئه|بنك|مصرف|مركز|وزاره)\s+")
MIN_NAME = 4  # الاسم الرسمي القصير (علم، سمة) يطابق كلمات عادية؛ يُكتب بصيغة أطول في aliases
COMMON_WORDS = {"تقنيه", "معادن", "البحري", "مرافق", "تحكم"}  # أسماء رسمية هي كلمات عادية، فتطابق بالـ aliases فقط


def norm(s: str) -> str:
    s = _DIACRITICS.sub("", s.lower()).translate(_LETTERS)
    return " " + re.sub(r"[^\w]+", " ", s).strip() + " "


def _names(e: Entity) -> list[str]:
    core = norm(e.name_ar).strip()
    official = [e.name_ar] if len(core) >= MIN_NAME and core not in COMMON_WORDS else []
    return [norm(n) for n in official + e.aliases if norm(n).strip()]


# كلمات تتكرر في أسماء جهات كثيرة، فاشتراك اسمين فيها لا يعني أنهما جهة واحدة
_ORG_WORDS = {"شركه", "مجموعه", "هيئه", "بنك", "مصرف", "مركز", "وزاره", "صندوق", "مؤسسه", "اكاديميه",
              "وطنيه", "وطني", "سعوديه", "سعودي", "عامه", "عام", "عربيه", "ملك", "تنميه", "ماليه", "معلومات",
              "اتصالات", "تقنيه", "خدمات", "تطوير", "استثمار", "صناعيه", "تامين", "تعاونيه", "حلول", "طيران",
              "خطوط", "جويه", "bank", "saudi", "arabia", "arabian", "company", "group", "the", "for", "and",
              "national", "fund", "authority", "ministry", "general", "corporation", "holding", "ksa",
              "international", "center", "centre", "development", "services", "solutions"}
# كلمة بجوار اسم الجهة تجعله شركة أخرى تابعة لها: «الراجحي المالية»، «تكافل الراجحي»، «أرامكو ديجيتال»
_SUBSIDIARY = {"ماليه", "كابيتال", "capital", "استثمار", "تامين", "تكافل", "takaful", "ديجيتال", "digital",
               "تجاره", "trading", "تمويل", "finance", "insurance", "ventures", "فنتشرز"}
# كلمات عامة تُتخطى بين اسم الجهة وكلمة الشركة التابعة: «Al Rajhi Company for Cooperative Insurance»
_FILLER = _ORG_WORDS - _SUBSIDIARY | {"of", "cooperative"}


def _bare(w: str) -> str:
    """الكلمة بلا «و» و«لـ» و«لل» و«ال» في أولها: «لأرامكو» أرامكو، «للتأمين» تأمين."""
    w = w[2:] if w.startswith("لل") and len(w) > 4 else w[1:] if w[:1] in ("و", "ل") and len(w) > 3 else w
    return w[2:] if w.startswith("ال") and len(w) > 4 else w


def _unprefix(w: str) -> str:
    """الكلمة بلا حرف جر أو عطف ملتصق في أولها: «لأرامكو» أرامكو، «للراجحي» الراجحي، «بشركة» شركة."""
    return "ال" + w[2:] if w.startswith("لل") and len(w) > 4 else w[1:] if w[:1] in "ولبف" and len(w) > 3 else w


def _words(s: str, bare: bool = False) -> set[str]:
    """كلمات الاسم المميزة. bare يضيف كل كلمة بلا حروفها الأولى أيضاً («لأرامكو» أرامكو)؛ يُستعمل للاسم
    المستخرج فقط ويقارَن بكلمات الجهة كما هي، فلا تصير «وزارة» «زارة» تشترك فيها كل الوزارات."""
    ws = set()
    for w in norm(s).split():
        ws |= {w[2:] if w.startswith("ال") and len(w) > 4 else w, *([_bare(w)] if bare else [])}
    return {w for w in ws if len(w) >= 3 and w not in _ORG_WORDS}


def _names_words(e: Entity) -> set[str]:
    return set().union(*({_bare(w) for w in norm(n).split()} for n in [e.name_ar, *e.aliases]))


def shares_name(named: str, e: Entity) -> bool:
    """الاسم الذي استخرجه المصنّف يشترك مع أسماء الجهة في كلمة مميزة («علم» و«شركة علم»). الاسم الإنجليزي
    يقارَن بأسماء الجهة الإنجليزية («SAFE» ليس «PIF») وبحروفه الأولى («Saudi Electricity Company» هي «SEC»)،
    وجهة بلا اسم إنجليزي لا يمكن مقارنتها فيُقبل."""
    if not _ARABIC.search(named) and all(_ARABIC.search(a) for a in e.aliases):
        return True
    own = set().union(*(_words(n) for n in [e.name_ar, *e.aliases]))
    initials = "".join(w[0] for w in norm(named).split() if w not in ("of", "the", "and", "for"))
    return bool(_words(named, bare=True) & own) or initials in {norm(a).strip() for a in e.aliases}


def subsidiary_of(text: str, e: Entity) -> bool:
    """بجوار اسم الجهة في النص كلمة شركة تابعة ليست في أسمائها: «الراجحي المالية» و«Al Rajhi Takaful» ليستا
    مصرف الراجحي. الجوار فقط، بعد تخطي الكلمات العامة: «مصرف الراجحي يعلن تدريب المالية» و«الراجحي المصرفية
    للاستثمار» للمصرف."""
    t, sub = norm(text).split(), _SUBSIDIARY - _names_words(e)

    def near(words: list[str]) -> bool:
        for w in words[:4]:
            if _bare(w) in sub:
                return True
            if _bare(w) not in _FILLER:
                return False
        return False
    for k in (n.split() for n in _names(e)):
        for i in range(len(t) - len(k) + 1):
            if k[0] in (t[i], _unprefix(t[i])) and t[i + 1:i + len(k)] == k[1:] and (
                    near(t[i + len(k):]) or near(t[:i][::-1])):
                return True
    return False


def find_named(named: str, entities: list[Entity]) -> Entity | None:
    """جهة الاسم الذي استخرجه المصنّف، ولو بحرف جر في أوله: «لوزارة المالية»، «بشركة علم»، «للخطوط السعودية»."""
    if (e := find_entity(named, entities)) is not None:
        return e
    w = norm(named).split()
    if not w:
        return None
    return find_entity(" ".join([_unprefix(w[0]), *w[1:]]), entities)


def find_entity(text: str, entities: list[Entity]) -> Entity | None:
    t = norm(text)
    best: tuple[int, Entity] | None = None
    for e in entities:
        for n in _names(e):
            if n in t and (best is None or len(n) > best[0]):
                best = (len(n), e)
    return best[1] if best else None


def outside_id(name: str) -> str | None:
    """معرّف ثابت لجهة خارج القائمة، حتى تُدمج إعلاناتها من عدة مواقع في بطاقة واحدة."""
    core = _GENERIC.sub("", norm(name).strip())
    return "x:" + "-".join(core.split())[:40] if core else None
