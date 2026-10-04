"""وسيط جهاز المؤسس: يجلب الصفحات السعودية التي ترفض خوادم أمريكا، ويرفع نصها للمستودع ثم يقفل.

لا يفتح أي منفذ على الجهاز، ولا ذكاء، ولا خادم. يعمل ثوانٍ كل ٣ ساعات عبر مجدول ويندوز.
الإيقاف النهائي: زر «أوقف وسيط الجهاز» في مجلد مهام راصد.
"""
from __future__ import annotations

import base64
import json
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rasid.dates import riyadh_now  # noqa: E402
from rasid.fetch import _get, _html_blocks  # noqa: E402
from relay.server import _public  # noqa: E402

REPO = "meshare-alsubaie/rasid-3"
LIST_URL = f"https://raw.githubusercontent.com/{REPO}/state/saudi_list.json"
LOG = ROOT / "state" / "home_agent.log"


def build_inbox(urls: list[str], client: httpx.Client, now: datetime) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for url in urls:
        entry = {"ok": False, "fetched_at": now.isoformat(), "blocks": [], "links": []}
        if not _public(url, socket.gethostbyname):
            entry["error_ar"] = "رابط غير مسموح"
        else:
            resp, err = _get(client, url)
            if resp is None:
                entry["error_ar"] = err
            else:
                blocks, links = _html_blocks(resp.text, str(resp.url))
                entry.update(ok=bool(blocks), blocks=[b.text for b in blocks], links=links[:40],
                             error_ar=None if blocks else "المحتوى فارغ")
        out[url] = entry
    return out


def _gh(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")


def upload(inbox: dict) -> str:
    """يرفع inbox.json لفرع inbox (ينشئ الفرع أول مرة)."""
    content = base64.b64encode(json.dumps(inbox, ensure_ascii=False).encode("utf-8")).decode()
    sha = _gh("api", f"repos/{REPO}/contents/inbox.json?ref=inbox", "--jq", ".sha").stdout.strip()
    if not sha:
        main_sha = _gh("api", f"repos/{REPO}/git/ref/heads/main", "--jq", ".object.sha").stdout.strip()
        _gh("api", f"repos/{REPO}/git/refs", "-f", "ref=refs/heads/inbox", "-f", f"sha={main_sha}")
    body = {"message": f"inbox {riyadh_now():%Y-%m-%d %H:%M}", "content": content, "branch": "inbox",
            "committer": {"name": "rasid-home", "email": "rasid@users.noreply.github.com"}}
    if sha:
        body["sha"] = sha
    r = _gh("api", "-X", "PUT", f"repos/{REPO}/contents/inbox.json", "--input", "-", stdin=json.dumps(body))
    return "تم" if r.returncode == 0 else f"فشل الرفع: {r.stderr.strip()[:200]}"


def main() -> int:
    now = riyadh_now()
    client = httpx.Client()
    try:
        urls = client.get(LIST_URL, timeout=30).json()
    except (httpx.HTTPError, ValueError) as e:
        urls, note = [], f"تعذّر جلب القائمة: {type(e).__name__}"
    else:
        note = ""
    inbox = build_inbox(urls, client, now) if urls else {}
    result = upload(inbox) if urls else "لا قائمة"
    ok = sum(1 for v in inbox.values() if v["ok"])
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now:%Y-%m-%d %H:%M} | صفحات {ok}/{len(inbox)} | {result} {note}\n")
    lines = LOG.read_text(encoding="utf-8").splitlines()[-200:]  # سجل مدوّر
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
