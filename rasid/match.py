"""مطابقة اسم جهة مذكور في إعلان (من مواقع التجميع) بجهة من القائمة. بلا ذكاء: أطول اسم مطابق يفوز."""
from __future__ import annotations

import re

from rasid.entities import Entity

_DIACRITICS = re.compile(r"[ً-ْـ]")
_LETTERS = str.maketrans("أإآىة", "ااايه")
_GENERIC = re.compile(r"^(?:ال)?(?:شركه|مجموعه|هيئه|بنك|مصرف|مركز|وزاره)\s+")
MIN_NAME = 4  # الاسم الرسمي القصير (علم، سمة) يطابق كلمات عادية؛ يُكتب بصيغة أطول في aliases
COMMON_WORDS = {"تقنيه", "معادن", "البحري", "مرافق"}  # أسماء رسمية هي كلمات عادية، فتطابق بالـ aliases فقط


def norm(s: str) -> str:
    s = _DIACRITICS.sub("", s.lower()).translate(_LETTERS)
    return " " + re.sub(r"[^\w]+", " ", s).strip() + " "


def _names(e: Entity) -> list[str]:
    core = norm(e.name_ar).strip()
    official = [e.name_ar] if len(core) >= MIN_NAME and core not in COMMON_WORDS else []
    return [norm(n) for n in official + e.aliases if norm(n).strip()]


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
