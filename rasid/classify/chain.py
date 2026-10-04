"""سلسلة التصنيف: قارئ بحصة كبيرة يقرأ كل جديد، ومؤكّد قوي يحسم ما يبدو فرصة.

لا بوابة واحدة: الكلمات القوية تُصعَّد للمؤكّد مهما قال القارئ، وإذا تعطّل الكل
يُرسل تنبيه «غير مؤكّد» عند وجود كلمات قوية، وإلا يبقى النص معلّقاً للإعادة ولا يُرمى.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from rasid.classify.providers import CallResult, Provider
from rasid.classify.schema import RELEVANT, Verdict, check_verdict
from rasid.dates import riyadh_now

SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
Caller = Callable[[Provider, str, str], CallResult]

_COOP = re.compile(r"تعاوني|تدريب\s*ميداني|co-?op\b|cooperative\s+training", re.IGNORECASE)
_UNIV = re.compile(r"تدريب\s*(?:ال)?(?:صيفي|جامعي)|internship", re.IGNORECASE)


def strong_keywords(text: str) -> str | None:
    if _COOP.search(text):
        return "coop"
    if _UNIV.search(text):
        return "university"
    return None


@dataclass
class Pending:
    reason_ar: str


@dataclass
class Budget:
    """عدّاد الحصص اليومية بتوقيت الرياض، ومن نفدت حصته اليوم لا يُطلب مرة ثانية."""
    used: dict[tuple[str, date], int] = field(default_factory=lambda: defaultdict(int))
    exhausted: set[tuple[str, date]] = field(default_factory=set)

    def available(self, p: Provider, day: date) -> bool:
        return (p.name, day) not in self.exhausted and self.used[(p.name, day)] < p.daily

    def spend(self, p: Provider, day: date) -> None:
        self.used[(p.name, day)] += 1

    def exhaust(self, p: Provider, day: date) -> None:
        self.exhausted.add((p.name, day))

    def to_dict(self) -> dict:
        return {"used": {f"{n}|{d}": c for (n, d), c in self.used.items()},
                "exhausted": [f"{n}|{d}" for n, d in sorted(self.exhausted)]}

    @classmethod
    def from_dict(cls, d: dict, today: date) -> Budget:
        """يحمّل حصة اليوم فقط؛ الأيام القديمة تُرمى (الحصة تتجدد يومياً)."""
        b = cls()
        for k, c in d.get("used", {}).items():
            n, day = k.rsplit("|", 1)
            if date.fromisoformat(day) == today:
                b.used[(n, today)] = c
        for k in d.get("exhausted", []):
            n, day = k.rsplit("|", 1)
            if date.fromisoformat(day) == today:
                b.exhausted.add((n, today))
        return b


def _first_valid(role: str, text: str, providers: list[Provider], budget: Budget,
                 call: Caller, day: date, errors: list[str]) -> Verdict | None:
    for p in providers:
        if p.role != role or not budget.available(p, day):
            continue
        budget.spend(p, day)
        r = call(p, SYSTEM_PROMPT, text)
        if not r.ok:
            errors.append(r.message or f"{p.name}: {r.error_kind}")
            if r.error_kind in ("rate_day", "auth"):
                budget.exhaust(p, day)
            continue
        v, why = check_verdict(r.data, text, p.model)
        if v is None:
            errors.append(f"[المصنّف][{p.name}] جواب مرفوض: {why}")
            continue
        return v
    return None


def classify(text: str, providers: list[Provider], budget: Budget, call: Caller,
             today: date | None = None) -> Verdict | Pending:
    day = today or riyadh_now().date()
    errors: list[str] = []
    kw = strong_keywords(text)
    reader = _first_valid("reader", text, providers, budget, call, day, errors)
    if reader is not None and reader.kind not in RELEVANT and kw is None:
        return reader
    confirmed = _first_valid("confirmer", text, providers, budget, call, day, errors)
    if confirmed is not None:
        return confirmed
    if reader is not None:
        reader.needs_recheck = True
        return reader
    if kw is not None:
        return Verdict(kind=kw, model="keywords", uncertain=True, needs_recheck=True)
    return Pending("كل نماذج الذكاء غير متاحة الآن: " + " | ".join(errors[-3:]))
