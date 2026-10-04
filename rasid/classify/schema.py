"""شكل حكم المصنّف والتحقق منه: أي اقتباس غير موجود في النص، أو تاريخ يناقض اقتباسه، يُسقط الحكم كله."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hijridate import Gregorian, Hijri

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


_GREG_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
            "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
_GREG_EN = ["january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december"]


def _date_mentioned(value: date, quote: str) -> bool:
    """هل التاريخ مذكور في اقتباسه؟ يقبل المدى بسنة مشتركة («1 سبتمبر - 31 أكتوبر 2025»)."""
    found = [x.date for x in parse_dates(quote)]
    if not found or value in found:
        return True
    q = normalize(quote)
    tokens = set(q.split())
    if str(value.day) not in tokens or str(value.year) not in tokens:
        return False
    h = Gregorian(value.year, value.month, value.day).to_hijri()
    names = {normalize(_GREG_AR[value.month - 1]), _GREG_EN[value.month - 1], normalize(h.month_name("ar"))}
    return any(n in q for n in names) or str(h.day) in tokens and normalize(h.month_name("ar")) in q


def parse_verdict(d: Any, input_text: str, model: str) -> Verdict | None:
    """يرجع الحكم إذا كان سليماً تماماً، وإلا None (فيُجرَّب النموذج التالي)."""
    return check_verdict(d, input_text, model)[0]


def check_verdict(d: Any, input_text: str, model: str) -> tuple[Verdict | None, str]:
    """مثل parse_verdict لكن يرجع سبب الرفض بالعربي حتى يظهر في السجل."""
    if not isinstance(d, dict) or d.get("kind") not in KINDS:
        return None, f"نوع غير معروف: {d.get('kind') if isinstance(d, dict) else type(d).__name__}"
    hay = normalize(input_text)
    kq = d.get("kind_quote")
    if kq and not _quoted(kq, hay):
        return None, "اقتباس النوع غير موجود في النص"
    v = Verdict(kind=d["kind"], model=model, kind_quote=kq)
    for name in DATE_FIELDS | BOOL_FIELDS | TEXT_FIELDS:
        f = d.get(name)
        if not isinstance(f, dict) or f.get("value") in (None, "", []):
            continue
        quote, value = f.get("quote"), f["value"]
        if not _quoted(quote, hay):
            return None, f"اقتباس {name} غير موجود في النص: {str(quote)[:80]}"
        if name in DATE_FIELDS:
            value = _to_date(value)
            if value is None:
                return None, f"صيغة تاريخ {name} غير صالحة: {f['value']}"
            if not _date_mentioned(value, quote):
                return None, f"تاريخ {name}={value} لا يطابق اقتباسه: {quote[:80]}"
        elif name in BOOL_FIELDS and not isinstance(value, bool):
            return None, f"{name} لازم صح أو خطأ"
        v.fields[name] = Field(value, quote)
    for m in d.get("majors") or []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        if m.get("quote") and not _quoted(m["quote"], hay):
            return None, f"اقتباس التخصص {m['name']} غير موجود في النص"
        v.majors.append({"name": m["name"], "seats": m.get("seats"), "quote": m.get("quote")})
    return v, ""
