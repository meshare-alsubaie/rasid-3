"""شكل حكم المصنّف والتحقق منه: أي اقتباس غير موجود في النص، أو تاريخ يناقض اقتباسه، يُسقط الحكم كله."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hijridate import Hijri

from rasid.dates import parse_dates

KINDS = {"coop", "university", "grad_program", "job", "hint", "irrelevant"}
RELEVANT = {"coop", "university", "grad_program", "hint"}
DATE_FIELDS = {"opens", "closes", "training_starts"}
BOOL_FIELDS = {"open_to_all_majors", "stipend", "housing", "medical", "transport", "no_courses_allowed"}
TEXT_FIELDS = {"title", "min_gpa", "apply_url", "cities"}


@dataclass(frozen=True)
class Field:
    value: Any
    quote: str


@dataclass
class Verdict:
    kind: str
    model: str
    fields: dict[str, Field] = field(default_factory=dict)
    majors: list[dict] = field(default_factory=list)
    kind_quote: str | None = None
    uncertain: bool = False
    needs_recheck: bool = False


def normalize(s: str) -> str:
    """الحروف والأرقام فقط: النماذج تحذف الترقيم ونقاط القوائم عند الاقتباس، وهذا ليس اختلاقاً."""
    s = re.sub(r"[ً-ْـ]", "", s)
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    return re.sub(r"[^\w]+", " ", s).strip().lower()


def _quoted(quote: Any, haystack: str) -> bool:
    return isinstance(quote, str) and bool(normalize(quote)) and normalize(quote) in haystack


def _to_date(v: Any) -> date | None:
    if not isinstance(v, str):
        return None
    m = re.fullmatch(r"(H:)?(\d{4})-(\d{1,2})-(\d{1,2})", v.strip())
    if not m:
        return None
    y, mo, d = int(m[2]), int(m[3]), int(m[4])
    try:
        return Hijri(y, mo, d).to_gregorian() if m[1] else date(y, mo, d)
    except (ValueError, OverflowError):
        return None


def parse_verdict(d: Any, input_text: str, model: str) -> Verdict | None:
    """يرجع الحكم إذا كان سليماً تماماً، وإلا None (فيُجرَّب النموذج التالي)."""
    if not isinstance(d, dict) or d.get("kind") not in KINDS:
        return None
    hay = normalize(input_text)
    kq = d.get("kind_quote")
    if kq and not _quoted(kq, hay):
        return None
    v = Verdict(kind=d["kind"], model=model, kind_quote=kq)
    for name in DATE_FIELDS | BOOL_FIELDS | TEXT_FIELDS:
        f = d.get(name)
        if not isinstance(f, dict) or f.get("value") in (None, "", []):
            continue
        quote, value = f.get("quote"), f["value"]
        if not _quoted(quote, hay):
            return None
        if name in DATE_FIELDS:
            value = _to_date(value)
            if value is None:
                return None
            in_quote = [x.date for x in parse_dates(quote)]
            if in_quote and value not in in_quote:
                return None
        elif name in BOOL_FIELDS and not isinstance(value, bool):
            return None
        v.fields[name] = Field(value, quote)
    for m in d.get("majors") or []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        if m.get("quote") and not _quoted(m["quote"], hay):
            return None
        v.majors.append({"name": m["name"], "seats": m.get("seats"), "quote": m.get("quote")})
    return v
