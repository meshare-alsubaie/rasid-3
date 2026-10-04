"""فحص تشخيصي: يجرّب كل قنوات ملف الجهات من الجهاز الحالي ويطبع تقريراً (يُستخدم من خوادم غيت هاب لكشف الحجب الجغرافي)."""
from __future__ import annotations

import collections
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rasid.entities import load_entities  # noqa: E402
from rasid.fetch import fetch  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    chans = [(e.id, c) for e in load_entities(ROOT / "config/entities.yaml") for c in e.channels]
    client = httpx.Client()
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda ec: (ec[0], ec[1].url, fetch(ec[1], client)), chans))
    bad = [(eid, u, r.error_ar) for eid, u, r in res if not r.ok]
    gov = [b for b in bad if urlparse(b[1]).hostname and urlparse(b[1]).hostname.endswith(".sa")]
    print(f"القنوات {len(res)} | المقروءة {len(res) - len(bad)} | الفاشلة {len(bad)} | منها نطاقات سعودية {len(gov)}")
    kinds = collections.Counter(b[2].split("فشل:")[-1].split("(")[0].strip() for b in bad)
    print("أسباب:", dict(kinds))
    ok_hosts = {urlparse(u).hostname for _, u, r in res if r.ok}
    print("نطاقات فاشلة كلياً:", sorted({urlparse(u).hostname for _, u, _ in bad} - ok_hosts))


if __name__ == "__main__":
    main()
