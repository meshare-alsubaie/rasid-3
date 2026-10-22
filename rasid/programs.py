"""البرامج: مفتاح السجل هو «البرنامج» لا الرابط، فالبرنامج الواحد من عدة مصادر بطاقة واحدة."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from rasid.classify.schema import Verdict

ChangeKind = Literal["new", "hint", "dates", "opened", "important_update"]
FAMILY = {"coop": "student", "university": "student", "hint": "student",
          "grad_program": "grad", "job": "job"}
ATTACH_WINDOW = timedelta(days=90)
CLOSING_SOON = 3
ACCEPTING_FRESH_DAYS = 30  # «التسجيل مفتوح» بلا تواريخ يُصدَّق شهراً من آخر مرة قيل فيها


@dataclass
class Change:
    kind: ChangeKind
    program_key: str
    detail_ar: str = ""


@dataclass
class Program:
    key: str
    entity_id: str
    family: str
    kind: str
    cycle: str
    first_seen: str
    updated: str
    sources: list[str] = field(default_factory=list)
    fields: dict[str, dict] = field(default_factory=dict)
    majors: list[dict] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    uncertain: bool = False
    alerted: bool = False  # وصل القروب تنبيه فيه موعد أو «فتح التسجيل»؛ شبكة الأمان تنبّه لما فاته


def _jsonable(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def status_of(fields: dict, today: date) -> str:
    """يقبل قيم الحقول كنصوص تاريخ (كما تُحفظ)."""
    opens = date.fromisoformat(fields["opens"]) if fields.get("opens") else None
    closes = date.fromisoformat(fields["closes"]) if fields.get("closes") else None
    if closes and today > closes:
        return "closed"
    if opens and today < opens:
        return "announced"
    if closes and (closes - today).days <= CLOSING_SOON:
        return "closing_soon"
    if opens or closes:
        return "open"
    return "announced"


def _accepting(fields: dict, today: date) -> bool:
    f = fields.get("accepting_now") or {}
    return (f.get("value") is True and bool(f.get("at"))
            and (today - date.fromisoformat(f["at"][:10])).days <= ACCEPTING_FRESH_DAYS)


def program_status(p: Program, today: date) -> str:
    """الحالة المعروضة: بالتواريخ إن وُجدت، وإلا «مفتوح» إذا قال المصدر حديثاً إن التسجيل مفتوح، وإلا «صفحة برنامج»."""
    dates = {k: v["value"] for k, v in p.fields.items() if k in ("opens", "closes") and v.get("value")}
    if dates:
        return status_of(dates, today)
    return "open" if _accepting(p.fields, today) else "listed"


class Programs:
    def __init__(self) -> None:
        self.items: dict[str, Program] = {}

    def _find(self, entity_id: str, family: str, cycle: str | None, now: datetime) -> Program | None:
        same = [p for p in self.items.values() if p.entity_id == entity_id and p.family == family]
        if cycle:
            for p in same:
                if p.cycle == cycle:
                    return p
        recent = [p for p in same if now - datetime.fromisoformat(p.updated) <= ATTACH_WINDOW
                  and (cycle is None or not p.fields.get("opens"))]
        return max(recent, key=lambda p: p.updated) if recent else None

    def merge(self, entity_id: str, v: Verdict, source_url: str,
              now: datetime) -> tuple[Program | None, Change | None]:
        family = FAMILY.get(v.kind)
        if family is None:
            return None, None
        opens = v.fields.get("opens")
        cycle = opens.value.strftime("%Y-%m") if opens else None
        p = self._find(entity_id, family, cycle, now)
        stamp = now.isoformat()
        new_fields = {k: {"value": _jsonable(f.value), "quote": f.quote} for k, f in v.fields.items()}
        if "accepting_now" in new_fields:
            new_fields["accepting_now"]["at"] = stamp
        if p is None:
            key = f"{entity_id}:{family}:{cycle or now.strftime('seen-%Y-%m-%d')}"
            p = Program(key, entity_id, family, v.kind, cycle or "", stamp, stamp, [source_url],
                        new_fields, list(v.majors), [v.model], v.uncertain)
            self.items[key] = p
            return p, Change("hint" if v.kind == "hint" else "new", key)
        change: Change | None = None
        if p.kind == "hint" and v.kind != "hint":
            change = Change("new", p.key)
            p.kind = v.kind
        elif v.kind != "hint" and p.kind != v.kind and family == "student":
            p.kind = v.kind  # المؤكّد يصحّح التصنيف
        had_dates = any(p.fields.get(k, {}).get("value") for k in ("opens", "closes"))
        gets_dates = any(new_fields.get(k, {}).get("value") for k in ("opens", "closes"))
        if change is None and not had_dates and gets_dates:
            change = Change("dates", p.key)  # برنامج معروف نزلت مواعيده لأول مرة: هذا هو الإعلان الفعلي
        was_open = _accepting(p.fields, now.date())
        if (change is None and not had_dates and not gets_dates and not was_open
                and (new_fields.get("accepting_now") or {}).get("value") is True):
            change = Change("opened", p.key)  # صفحة برنامج دائمة صارت تقول «التسجيل مفتوح»
        for name in ("opens", "closes"):
            old, new = p.fields.get(name, {}).get("value"), new_fields.get(name, {}).get("value")
            if change is None and old and new and old != new:
                change = Change("important_update", p.key, f"تغيّر {name}: من {old} إلى {new}")
        p.fields.update(new_fields)
        if cycle and not p.cycle:
            p.cycle = cycle
        if v.majors:
            p.majors = list(v.majors)
        if source_url not in p.sources:
            p.sources.append(source_url)
        if v.model not in p.models:
            p.models.append(v.model)
        p.uncertain = p.uncertain and v.uncertain
        p.updated = stamp
        return p, change

    def to_dict(self) -> dict:
        return {k: asdict(p) for k, p in self.items.items()}

    @classmethod
    def from_dict(cls, d: dict) -> Programs:
        ps = cls()
        ps.items = {k: Program(**p) for k, p in d.items()}
        return ps
