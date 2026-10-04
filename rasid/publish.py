"""الناشر: يبني results.json العام الذي يقرأه التطبيق («حبّ القهوة الجاهز»).

يحوي المعلومات ودليلها فقط: لا نصوص صفحات، لا حسابات، لا مفاتيح، لا رسائل أخطاء تفصيلية.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from rasid.entities import Entity
from rasid.programs import Program, status_of
from rasid.run import State

# أوزان المؤسس للنجوم المحسوبة (حين لا يضع نجوماً يدوية): الاسم ثم التوظيف ثم الأمن السيبراني ثم المزايا
WEIGHTS = {"name": 0.4, "hires": 0.3, "cyber": 0.2, "benefits": 0.1}
BENEFITS = ("stipend", "housing", "medical", "transport")


def compute_stars(e: Entity, p: Program | None) -> int:
    if e.stars_manual:
        return e.stars_manual
    benefits = 0.5
    if p is not None:
        known = [p.fields[b]["value"] for b in BENEFITS if b in p.fields]
        benefits = sum(1 for v in known if v is True) / len(BENEFITS) if known else 0.5
    score = (WEIGHTS["name"] * 0.5 + WEIGHTS["hires"] * e.hires_after / 3
             + WEIGHTS["cyber"] * e.cyber / 3 + WEIGHTS["benefits"] * benefits)
    return max(1, min(5, 1 + round(score * 4)))


def expected_month(e: Entity, past_opens: list[str]) -> int | None:
    """الشهر المتوقع للفتح: الأكثر تكراراً في تاريخ الجهة، وإلا شهرها المعتاد، وإلا غير معروف."""
    if past_opens:
        counts = Counter(date.fromisoformat(d).month for d in past_opens)
        return min(counts, key=lambda m: (-counts[m], m))
    return e.usual_months[0] if e.usual_months else None


def _status(p: Program | None, today: date) -> str:
    if p is None:
        return "not_announced"
    dates = {k: v["value"] for k, v in p.fields.items() if k in ("opens", "closes")}
    return status_of(dates, today) if dates else "listed"


def build_results(st: State, entities: list[Entity], now: datetime) -> dict:
    today = now.date()
    student = [p for p in st.programs.items.values() if p.family == "student"]
    latest = {}
    for p in sorted(student, key=lambda p: p.updated):
        latest[p.entity_id] = p
    out_entities = []
    for e in entities:
        urls = [c.url for c in e.channels if c.kind in ("web", "rss")]
        hs = [st.health[u] for u in urls if u in st.health]
        p = latest.get(e.id)
        past = [p2.fields["opens"]["value"] for p2 in student if p2.entity_id == e.id and "opens" in p2.fields]
        out_entities.append({
            "id": e.id, "name": e.name_ar, "stars": compute_stars(e, p), "cyber": e.cyber,
            "hires_after": e.hires_after, "fulltime_history": e.fulltime_history,
            "fulltime_evidence": e.fulltime_evidence, "expected_month": expected_month(e, past),
            "status": _status(p, today), "program": p.key if p else None,
            "sources_total": len(urls),
            "sources_ok": sum(1 for h in hs if h["consecutive_failures"] == 0 and h["last_success"]),
            "last_success": max((h["last_success"] for h in hs if h["last_success"]), default=None),
            "via_home": any(h.get("via") == "home" for h in hs),
        })
    programs = [{
        "key": p.key, "entity": p.entity_id, "family": p.family, "kind": p.kind,
        "title": (p.fields.get("title") or {}).get("value"),
        "opens": (p.fields.get("opens") or {}).get("value"), "closes": (p.fields.get("closes") or {}).get("value"),
        "status": _status(p, today), "fields": p.fields, "majors": p.majors, "sources": p.sources,
        "models": p.models, "uncertain": p.uncertain, "first_seen": p.first_seen, "updated": p.updated,
    } for p in st.programs.items.values()]
    ok = sum(1 for h in st.health.values() if h["consecutive_failures"] == 0 and h["last_success"])
    return {
        "generated_at": now.isoformat(),
        "health": {"sources_total": len(st.health), "sources_ok": ok,
                   "via_home": sum(1 for h in st.health.values() if h.get("via") == "home"),
                   "queue": len(st.queue.items)},
        "entities": out_entities, "programs": programs,
    }
