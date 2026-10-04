"""يبني config/entities.yaml من قائمة راصد ٢ بعد التحقق الحي من كل قناة بجالب راصد ٣.

الاستخدام: uv run python scripts/seed_entities.py <مسار organisations.json>
ينتج أيضاً docs/sources-health.md: تقرير صادق بكل قناة لم تُقرأ وسببها.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rasid.entities import Channel  # noqa: E402
from rasid.fetch import fetch  # noqa: E402

TIER_STARS = {"S": 5, "A": 4, "B": 3, "C": 2}
# قرب أولي من الأمن السيبراني (اقتراح يراجعه المؤسس)
CYBER3 = {"nca", "ncac", "site", "sdaia", "elm", "ncdc", "dga", "citc", "ncai", "sama"}
CYBER2 = {"stc", "mobily", "zain", "takamol", "taqnia", "mcit", "deloitte_sa", "kpmg_sa", "pwc_sa", "ey_sa", "tadawul"}
MAX_CHANNELS = 6


def pick_sources(org: dict) -> list[str]:
    seen, out = set(), []
    ranked = sorted(org.get("sources", []), key=lambda s: (s.get("provenance") != "official",
                                                           not s.get("coopConfirmed"), len(s["url"])))
    for s in ranked:
        u = s["url"].strip()
        if u in seen or not u.startswith("http"):
            continue
        seen.add(u)
        out.append(u)
        if len(out) == MAX_CHANNELS:
            break
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    orgs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    plan = [(o, u) for o in orgs for u in pick_sources(o)]
    client = httpx.Client()

    def check(item):
        o, u = item
        try:
            r = fetch(Channel("web", u), client)
            return o["id"], u, r.ok, r.error_ar or f"{len(r.blocks)} كتلة"
        except Exception as e:  # noqa: BLE001
            return o["id"], u, False, f"انهيار: {e}"

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check, plan))
    ok_by_org: dict[str, list[str]] = {}
    bad: list[tuple[str, str, str]] = []
    for oid, u, ok, note in results:
        if ok:
            ok_by_org.setdefault(oid, []).append(u)
        else:
            bad.append((oid, u, note))

    entities = []
    for o in orgs:
        z = o.get("requiresZeroCourses") or {}
        e = {"id": o["id"], "name_ar": o["nameAr"],
             "stars_manual": TIER_STARS.get(o.get("tier")),
             "cyber": 3 if o["id"] in CYBER3 else 2 if o["id"] in CYBER2 else 1,
             "hires_after": 1,
             "fulltime_history": "yes" if z.get("value") is True else "unknown",
             "channels": [{"kind": "web", "url": u} for u in ok_by_org.get(o["id"], [])]}
        if z.get("value") is True and z.get("quote"):
            e["fulltime_evidence"] = z["quote"]
        entities.append({k: v for k, v in e.items() if v is not None})
    header = ("# ملف الجهات. عدّله بحرية؛ أي خطأ يُرفض آلياً برسالة عربية تسمّي السطر.\n"
              "# stars_manual: النجوم من 1 إلى 5 | cyber: القرب من الأمن السيبراني 0-3 | hires_after: التوظيف بعد التدريب 0-3\n"
              "# fulltime_history: هل اشترطت التفرغ سابقاً yes/no/unknown | channels: القنوات الرسمية (web/rss/x/linkedin/email)\n\n")
    (ROOT / "config/entities.yaml").write_text(
        header + yaml.safe_dump(entities, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")

    no_channel = [o["nameAr"] for o in orgs if not ok_by_org.get(o["id"])]
    lines = ["# صحة المصادر عند البذر", "",
             f"- الجهات: {len(orgs)}، القنوات المجرّبة: {len(plan)}، المقروءة: {len(plan) - len(bad)}، الفاشلة: {len(bad)}",
             f"- جهات بلا أي قناة مقروءة ({len(no_channel)}): " + "، ".join(no_channel), "", "## القنوات الفاشلة", ""]
    lines += [f"- {oid}: {u}\n  - {note}" for oid, u, note in bad]
    (ROOT / "docs/sources-health.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"جهات {len(orgs)} | قنوات {len(plan)} | مقروءة {len(plan) - len(bad)} | فاشلة {len(bad)} | بلا قناة {len(no_channel)}")


if __name__ == "__main__":
    main()
