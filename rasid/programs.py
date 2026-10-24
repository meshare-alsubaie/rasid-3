"""البرامج: مفتاح السجل هو «البرنامج» لا الرابط، فالبرنامج الواحد من عدة مصادر بطاقة واحدة."""
from __future__ import annotations

import re
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
OPENS_ONLY_DAYS = 21       # فتح بلا إغلاق: «مفتوح» ثلاثة أسابيع، وبعدها لا نعرف، فهو صفحة برنامج


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


_TRACK_SEP = re.compile(r"\s+[-–—|]\s+")


def _track_base(title) -> str:
    """«برنامج علم (دفعة يناير) - علوم الحاسب» أساسه «برنامج علم (دفعة يناير)»: المسار بعد الفاصل."""
    return _TRACK_SEP.split(str(title or ""), 1)[0].strip()


def _union_majors(old: list[dict], new: list[dict], url) -> list[dict]:
    """كل مصدر يذكر بعض التخصصات (مسار واحد لكل إعلان مثلاً)، فالتخصصات تُجمع ولا يمحو الأخير ما قبله."""
    out = {m["name"].strip().lower(): dict(m) for m in old}
    for m in new:
        k = m["name"].strip().lower()
        out[k] = {**out.get(k, {}), **m, **({"url": url} if url else {})}
    return list(out.values())


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
    accepting = _accepting(p.fields, today)
    if dates:
        s = status_of(dates, today)
        stale = (s == "open" and "closes" not in dates
                 and (today - date.fromisoformat(dates["opens"])).days > OPENS_ONLY_DAYS)
        return "listed" if stale and not accepting else s
    return "open" if accepting else "listed"


class Programs:
    def __init__(self) -> None:
        self.items: dict[str, Program] = {}

    def _find(self, entity_id: str, family: str, cycle: str | None, now: datetime,
              v_closes: date | None = None) -> Program | None:
        same = [p for p in self.items.values() if p.entity_id == entity_id and p.family == family]
        if cycle:
            for p in same:
                if p.cycle == cycle:
                    return p
        closes = v_closes.isoformat() if v_closes else None
        recent = [p for p in same if now - datetime.fromisoformat(p.updated) <= ATTACH_WINDOW
                  and (cycle is None or not p.fields.get("opens"))
                  # إغلاق قادم لا يُلصق ببرنامج أقفل: هذه دورة جديدة
                  and not (closes and closes > now.date().isoformat()
                           and program_status(p, now.date()) == "closed")]
        return max(recent, key=lambda p: p.updated) if recent else None

    def merge(self, entity_id: str, v: Verdict, source_url: str, now: datetime,
              listing: str | None = None) -> tuple[Program | None, Change | None]:
        """listing: صفحة الجهة التي فُتح منها الإعلان (صفحة كل المسارات) إن كان رابطاً متبوعاً."""
        family = FAMILY.get(v.kind)
        if family is None:
            return None, None
        opens = v.fields.get("opens")
        cycle = opens.value.strftime("%Y-%m") if opens else None
        closes = v.fields.get("closes")
        p = self._find(entity_id, family, cycle, now, closes.value if closes else None)
        stamp = now.isoformat()
        new_fields = {k: {"value": _jsonable(f.value), "quote": f.quote} for k, f in v.fields.items()}
        if "accepting_now" in new_fields:
            new_fields["accepting_now"]["at"] = stamp
        track_url = v.fields["apply_url"].value if v.fields.get("apply_url") else None
        if p is None:
            key = f"{entity_id}:{family}:{cycle or now.strftime('seen-%Y-%m-%d')}"
            p = Program(key, entity_id, family, v.kind, cycle or "", stamp, stamp, [source_url],
                        new_fields, _union_majors([], v.majors, track_url), [v.model], v.uncertain)
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
        old_title, new_title = (p.fields.get("title") or {}).get("value"), (new_fields.get("title") or {}).get("value")
        if old_title and new_title and old_title != new_title and _track_base(old_title) == _track_base(new_title):
            # مسار آخر من نفس البرنامج: العنوان أساسه، ورابط التقديم العام صفحة كل المسارات لا رابط هذا المسار
            new_fields["title"] = {"value": _track_base(new_title), "quote": _track_base(new_title)}
            if listing:
                new_fields["apply_url"] = {"value": listing, "quote": "صفحة برامج التدريب في موقع الجهة"}
            elif p.fields.get("apply_url"):
                new_fields.pop("apply_url", None)
        p.fields.update(new_fields)
        if cycle and not p.cycle:
            p.cycle = cycle
        if v.majors:
            p.majors = _union_majors(p.majors, v.majors, track_url)
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
