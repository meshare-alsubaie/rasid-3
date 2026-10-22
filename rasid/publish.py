"""الناشر: يبني results.json العام الذي يقرأه التطبيق («حبّ القهوة الجاهز»).

يحوي المعلومات ودليلها فقط: لا نصوص صفحات، لا حسابات، لا مفاتيح، لا رسائل أخطاء تفصيلية.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from rasid.entities import Entity, site_of
from rasid.programs import Program, program_status
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
    return "not_announced" if p is None else program_status(p, today)


def _watch(total: int, ok: int) -> str:
    """هل راصد يرى هذه الجهة فعلاً؟ «none» بلا مصادر، «blind» مصادرها لا تُقرأ الآن، «ok» يُقرأ منها شيء."""
    return "none" if total == 0 else "ok" if ok else "blind"


def _official_url(p: Program, agg: frozenset[str]) -> str | None:
    """رابط التقديم، وإلا أول مصدر رسمي. None إذا لم يصل البرنامج إلا من مواقع التجميع."""
    urls = [(p.fields.get("apply_url") or {}).get("value"), *p.sources]
    return next((u for u in urls if isinstance(u, str) and u.startswith("http") and site_of(u) not in agg), None)


def build_results(st: State, entities: list[Entity], now: datetime, agg_sites: frozenset[str] = frozenset()) -> dict:
    today = now.date()
    student = [p for p in st.programs.items.values() if p.family == "student"]
    latest = {}
    rank = {"closing_soon": 0, "open": 1, "announced": 2, "listed": 3, "closed": 4}
    # البطاقة تعرض أهم برنامج للجهة: المفتوح ثم القادم ثم الأحدث
    for p in sorted(student, key=lambda p: (-rank[program_status(p, today)], p.updated)):
        latest[p.entity_id] = p
    out_entities = []
    for e in entities:
        urls = [c.url for c in e.channels if c.kind in ("web", "rss")]
        hs = [st.health[u] for u in urls if u in st.health]
        p = latest.get(e.id)
        past = [p2.fields["opens"]["value"] for p2 in student if p2.entity_id == e.id and "opens" in p2.fields]
        ok = sum(1 for h in hs if h["consecutive_failures"] == 0 and h["last_success"])
        out_entities.append({
            "id": e.id, "name": e.name_ar, "stars": compute_stars(e, p), "cyber": e.cyber,
            "hires_after": e.hires_after, "fulltime_history": e.fulltime_history,
            "fulltime_evidence": e.fulltime_evidence, "expected_month": expected_month(e, past),
            "status": _status(p, today), "program": p.key if p else None,
            "sources_total": len(urls),
            "sources_ok": ok, "watch": _watch(len(urls), ok), "outside": False,
            "last_success": max((h["last_success"] for h in hs if h["last_success"]), default=None),
            "via_home": any(h.get("via") == "home" for h in hs),
        })
    # جهات خارج القائمة وصلت إعلاناتها من مواقع التجميع
    for eid in sorted({p.entity_id for p in student if p.entity_id.startswith("x:")}):
        p = latest[eid]
        out_entities.append({
            "id": eid, "name": (p.fields.get("entity_name") or {}).get("value") or eid[2:], "stars": 3, "cyber": 0,
            "hires_after": 0, "fulltime_history": "unknown", "fulltime_evidence": None, "expected_month": None,
            "status": _status(p, today), "program": p.key, "sources_total": 0, "sources_ok": 0,
            "watch": "outside", "outside": True, "last_success": None, "via_home": False,
        })
    programs = [{
        "key": p.key, "entity": p.entity_id, "family": p.family, "kind": p.kind,
        "title": (p.fields.get("title") or {}).get("value"),
        "opens": (p.fields.get("opens") or {}).get("value"), "closes": (p.fields.get("closes") or {}).get("value"),
        "status": _status(p, today), "fields": p.fields, "majors": p.majors, "sources": p.sources,
        "official_url": _official_url(p, agg_sites),
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
