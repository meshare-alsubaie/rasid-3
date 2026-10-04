"""البرامج: مفتاح السجل هو «البرنامج» لا الرابط، فالبرنامج الواحد من عدة مصادر بطاقة واحدة."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from rasid.classify.schema import Verdict

ChangeKind = Literal["new", "hint", "important_update"]
FAMILY = {"coop": "student", "university": "student", "hint": "student",
          "grad_program": "grad", "job": "job"}
ATTACH_WINDOW = timedelta(days=90)
CLOSING_SOON = 3


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
