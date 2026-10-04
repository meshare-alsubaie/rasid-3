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
from concurrent.futures import ThreadPoolExecutor
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


def _one(url: str, client: httpx.Client, now: datetime, resolve) -> dict:
    entry = {"ok": False, "fetched_at": now.isoformat(), "blocks": [], "links": []}
    if not _public(url, resolve):
        entry["error_ar"] = "رابط غير مسموح"
    else:
        resp, err = _get(client, url)
        if resp is None:
            entry["error_ar"] = err
        else:
            blocks, links = _html_blocks(resp.text, str(resp.url))
            entry.update(ok=bool(blocks), blocks=[b.text for b in blocks], links=links[:40],
                         error_ar=None if blocks else "المحتوى فارغ")
    return entry


def build_inbox(urls: list[str], client: httpx.Client, now: datetime,
                resolve=socket.gethostbyname) -> dict[str, dict]:
    """يجلب بالتوازي (٨ معاً) حتى لا تتراكم مهلات المواقع البطيئة."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(pool.map(lambda u: _one(u, client, now, resolve), urls))
    return dict(zip(urls, entries))


STALE_AFTER_H = 8


def watchdog_alerts(last_state_iso: str | None, now: datetime, last_alert_day: str | None) -> list[tuple[str, str]]:
    """الحارس المستقل: إذا المحرّك ما حفظ حالته من ٨ ساعات، ينبّه المؤسس والقروب (مرة باليوم)."""
    if last_alert_day == now.date().isoformat():
        return []
    if last_state_iso is None:
        return [("owner", "🔴 الحارس (جهازك): ما لقيت أي حالة محفوظة للمحرّك. يبدو أنه لم يعمل بعد.")]
    hours = int((now - datetime.fromisoformat(last_state_iso)).total_seconds() // 3600)
    if hours < STALE_AFTER_H:
        return []
    return [("owner", f"🔴 الحارس (جهازك): المحرّك ما اشتغل من {hours} ساعات.\n"
                      f"افتح صفحة التشغيل: https://github.com/{REPO}/actions"),
            ("group", f"⚠️ راصد متوقف مؤقتاً من {hours} ساعات. تابعوا مواقع الجهات بأنفسكم احتياطاً حتى يرجع.")]


def _watchdog(client: httpx.Client, now: datetime) -> str:
    from rasid.__main__ import load_env
    from rasid.notify.telegram import DeliveryError, send
    mark = ROOT / "state" / "watchdog_last_alert.txt"
    last_alert = mark.read_text(encoding="utf-8").strip() if mark.exists() else None
    r = _gh("api", f"repos/{REPO}/branches/state", "--jq", ".commit.commit.committer.date")
    last = r.stdout.strip() or None
    if last:
        last = datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(now.tzinfo).isoformat()
    alerts = watchdog_alerts(last, now, last_alert)
    if not alerts:
        return "الحارس: المحرّك سليم"
    env = load_env()
    chats = {"owner": env.get("TG_OWNER_CHAT", ""), "group": env.get("TG_GROUP_CHAT", "")}
    try:
        for chat, text in alerts:
            send(env.get("TELEGRAM_BOT_TOKEN", ""), chats[chat], text, client)
    except DeliveryError as e:
        return f"الحارس: فشل التنبيه {e}"
    mark.write_text(now.date().isoformat(), encoding="utf-8")
    return "الحارس: أرسل تنبيه توقف"


def _gh(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")


def upload(inbox: dict) -> str:
    """يرفع inbox.json لفرع inbox (ينشئ الفرع أول مرة)."""
    content = base64.b64encode(json.dumps(inbox, ensure_ascii=False).encode("utf-8")).decode()
    got = _gh("api", f"repos/{REPO}/contents/inbox.json?ref=inbox", "--jq", ".sha")
    # نعتمد على نجاح الطلب لا على النص: عند الفشل يطبع غيت هاب رسالة خطأ في المخرجات
    sha = got.stdout.strip() if got.returncode == 0 else ""
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
    result += " | " + _watchdog(client, now)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now:%Y-%m-%d %H:%M} | صفحات {ok}/{len(inbox)} | {result} {note}\n")
    lines = LOG.read_text(encoding="utf-8").splitlines()[-200:]  # سجل مدوّر
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
