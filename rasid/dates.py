"""التواريخ: استخراج التواريخ الهجرية (أم القرى) والميلادية من النص، وتوقيت الرياض."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from hijridate import Hijri

RIYADH = ZoneInfo("Asia/Riyadh")
QUIET_START, QUIET_END = time(0, 0), time(7, 0)

# تحويل حرف بحرف حتى تبقى مواقع النص كما هي ويكون الاقتباس جزءاً حرفياً من الأصل
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_HIJRI_MONTHS = [
    (1, r"محرم"), (2, r"صفر"),
    (3, r"ربيع\s+(?:الأول|الاول|أول)"), (4, r"ربيع\s+(?:الآخر|الاخر|الثاني|ثاني)"),
    (5, r"جماد[ىي]\s+(?:الأولى|الاولى|الأول|الاول|أولى)"),
    (6, r"جماد[ىي]\s+(?:الآخرة|الاخرة|الآخر|الثانية|الثاني|آخرة)"),
    (7, r"رجب"), (8, r"شعبان"), (9, r"رمضان"), (10, r"شوال"),
    (11, r"ذ[وي]\s+القعدة"), (12, r"ذ[وي]\s+الحجة"),
]
_GREG_AR = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "إبريل": 4, "مايو": 5,
    "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10,
    "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}
_GREG_EN = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_EN_ALT = "|".join(list(_GREG_EN) + [m[:3] for m in _GREG_EN])

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("hijri_named", re.compile(
        r"(\d{1,2})\s+(" + "|".join(f"(?:{p})" for _, p in _HIJRI_MONTHS) + r")\s+(\d{4})\s*(?:هـ|ه\b)?")),
    ("hijri_numeric", re.compile(r"\b(14\d\d)\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})\s*(?:هـ|ه)?")),
    ("greg_ar", re.compile(r"(\d{1,2})\s+(" + "|".join(_GREG_AR) + r")\s+(\d{4})\s*م?")),
    ("greg_en_mdy", re.compile(r"\b(" + _EN_ALT + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE)),
    ("greg_en_dmy", re.compile(r"\b(\d{1,2})\s+(" + _EN_ALT + r")\.?,?\s+(\d{4})\b", re.IGNORECASE)),
    ("greg_ymd", re.compile(r"\b(20\d\d)[/-](\d{1,2})[/-](\d{1,2})\b")),
    ("greg_dmy", re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d\d)\b")),
]


@dataclass(frozen=True)
class FoundDate:
    date: date
    quote: str
    calendar: Literal["hijri", "gregorian"]


def _hijri_month(name: str) -> int:
    for num, pat in _HIJRI_MONTHS:
        if re.fullmatch(pat, name):
            return num
    raise ValueError(name)


def _to_date(kind: str, g: tuple[str, ...]) -> tuple[date, Literal["hijri", "gregorian"]]:
    if kind == "hijri_named":
        return Hijri(int(g[2]), _hijri_month(g[1]), int(g[0])).to_gregorian(), "hijri"
    if kind == "hijri_numeric":
        return Hijri(int(g[0]), int(g[1]), int(g[2])).to_gregorian(), "hijri"
    if kind == "greg_ar":
        return date(int(g[2]), _GREG_AR[g[1]], int(g[0])), "gregorian"
    if kind == "greg_en_mdy":
        return date(int(g[2]), _en_month(g[0]), int(g[1])), "gregorian"
    if kind == "greg_en_dmy":
        return date(int(g[2]), _en_month(g[1]), int(g[0])), "gregorian"
    if kind == "greg_ymd":
        return date(int(g[0]), int(g[1]), int(g[2])), "gregorian"
    return date(int(g[2]), int(g[1]), int(g[0])), "gregorian"  # greg_dmy


def _en_month(name: str) -> int:
    n = name.lower()
    return _GREG_EN.get(n) or next(v for k, v in _GREG_EN.items() if k[:3] == n)


def parse_dates(text: str) -> list[FoundDate]:
    """كل التواريخ الصالحة في النص بترتيب ظهورها. الاقتباس جزء حرفي من النص الأصلي."""
    norm = text.translate(_DIGITS)
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, FoundDate]] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(norm):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            try:
                d, cal = _to_date(kind, m.groups())
            except (ValueError, OverflowError, StopIteration):
                continue
            taken.append((s, e))
            found.append((s, FoundDate(d, text[s:e].strip(), cal)))
    return [f for _, f in sorted(found, key=lambda x: x[0])]


def riyadh_now() -> datetime:
    return datetime.now(RIYADH)


def in_quiet_hours(dt: datetime) -> bool:
    t = dt.astimezone(RIYADH).time()
    return QUIET_START <= t < QUIET_END
