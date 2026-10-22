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
from rasid.dates import quota_day, riyadh_now

SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
SHORT_INPUT = 4000  # إعادة النص بهذا الطول لنموذج قال «أطول من حدي»
Caller = Callable[[Provider, str, str], CallResult]

_COOP = re.compile(r"تعاوني|تدريب\s*ميداني|co-?op\b|cooperative\s+training", re.IGNORECASE)
_UNIV = re.compile(r"تدريب\s*(?:ال)?(?:صيفي|جامعي)|internship", re.IGNORECASE)


CONTEXT_MARK = "بقية نص الصفحة (سياق فقط):"


def strong_keywords(text: str) -> str | None:
    """تُفحص الأجزاء الجديدة فقط؛ السياق المرفق لا يصعّد كل تغيير صغير في صفحة تعاوني."""
    text = text.split(CONTEXT_MARK, 1)[0]
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
                 call: Caller, day: date, qday: date, errors: list[str]) -> Verdict | None:
    """day: تاريخ اليوم بالرياض في تعليمات المصنّف. qday: يوم الحصة (يتجدد منتصف الليل بتوقيت المحيط الهادئ)."""
    system = f"{SYSTEM_PROMPT}\n\nتاريخ اليوم: {day.isoformat()}"
    for p in providers:
        if p.role != role or not budget.available(p, qday):
            continue
        budget.spend(p, qday)
        seen = text
        r = call(p, system, seen)
        if not r.ok and r.error_kind == "too_large" and len(text) > SHORT_INPUT and budget.available(p, qday):
            budget.spend(p, qday)  # الجديد في الصفحة أولاً دائماً، فأوله يكفي للحكم
            seen = text[:SHORT_INPUT]
            r = call(p, system, seen)
        if not r.ok:
            errors.append(r.message or f"{p.name}: {r.error_kind}")
            if r.error_kind in ("rate_day", "auth"):
                budget.exhaust(p, qday)
            continue
        v, why = check_verdict(r.data, seen, p.model)
        if v is None:
            kind = r.data.get("kind") if isinstance(r.data, dict) else None
            errors.append(f"[المصنّف][{p.name}] جواب مرفوض ({kind}): {why}")
            continue
        return v
    return None


def classify(text: str, providers: list[Provider], budget: Budget, call: Caller,
             today: date | None = None) -> Verdict | Pending:
    day = today or riyadh_now().date()
    qday = today or quota_day()
    errors: list[str] = []
    kw = strong_keywords(text)
    reader = _first_valid("reader", text, providers, budget, call, day, qday, errors)
    if reader is not None and reader.kind not in RELEVANT and kw is None:
        reader.notes = errors + reader.notes
        return reader
    confirmed = _first_valid("confirmer", text, providers, budget, call, day, qday, errors)
    if confirmed is not None:
        confirmed.notes = errors + confirmed.notes
        return confirmed
    if reader is not None:
        reader.needs_recheck = True
        reader.notes = errors + reader.notes
        return reader
    if kw is not None:
        return Verdict(kind=kw, model="keywords", uncertain=True, needs_recheck=True, notes=errors)
    return Pending("كل نماذج الذكاء غير متاحة الآن: " + " | ".join(errors[-3:]))
