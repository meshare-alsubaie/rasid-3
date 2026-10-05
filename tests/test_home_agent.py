import json
from datetime import datetime, timedelta

import httpx
import respx

from rasid.dates import RIYADH
from rasid.entities import Channel
from rasid.fetch import fetch, set_inbox
from relay.home_agent import build_inbox

URL = "https://careers.sdaia.gov.sa/coop"
PAGE = "<html><body><main><p>برنامج التدريب التعاوني لطلاب الجامعات يفتح قريباً بإذن الله.</p></main></body></html>"
NOW = datetime(2026, 10, 4, 15, 0, tzinfo=RIYADH)


def teardown_function():
    set_inbox({})


# ---------- جهاز المؤسس: يجلب القائمة ويبني صندوقاً صغيراً ----------

@respx.mock
def test_agent_fetches_list_and_stores_text_not_html():
    respx.get(URL).mock(return_value=httpx.Response(200, html=PAGE))
    inbox = build_inbox([URL], httpx.Client(), NOW)
    e = inbox[URL]
    assert e["ok"] and "التدريب التعاوني" in "\n".join(e["blocks"]) and "<html" not in json.dumps(e)
    assert e["fetched_at"] == NOW.isoformat()


@respx.mock
def test_agent_records_failure_without_crashing():
    respx.get(URL).mock(side_effect=httpx.ConnectError("x"))
    inbox = build_inbox([URL], httpx.Client(), NOW)
    assert not inbox[URL]["ok"] and inbox[URL]["error_ar"]


def test_agent_refuses_non_http_and_internal_urls():
    inbox = build_inbox(["file:///etc/passwd", "http://127.0.0.1/admin"], httpx.Client(), NOW)
    assert all(not v["ok"] for v in inbox.values())


# ---------- المحرّك: يستخدم الصندوق إذا كان حديثاً ----------

@respx.mock
def test_engine_uses_fresh_inbox_when_site_blocks_cloud(monkeypatch):
    monkeypatch.delenv("RASID_RELAY_URL", raising=False)
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    set_inbox({URL: {"ok": True, "blocks": ["برنامج التدريب التعاوني"], "links": [],
                     "fetched_at": (datetime.now(RIYADH) - timedelta(hours=2)).isoformat()}})
    r = fetch(Channel("web", URL), httpx.Client())
    assert r.ok and r.via == "home" and r.blocks[0].text == "برنامج التدريب التعاوني"


@respx.mock
def test_engine_ignores_stale_inbox(monkeypatch):
    monkeypatch.delenv("RASID_RELAY_URL", raising=False)
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    set_inbox({URL: {"ok": True, "blocks": ["قديم"], "links": [],
                     "fetched_at": (datetime.now(RIYADH) - timedelta(hours=13)).isoformat()}})
    r = fetch(Channel("web", URL), httpx.Client())
    assert not r.ok and "جهاز" in r.error_ar


# ---------- الحارس المستقل: جهاز المؤسس يراقب نبضة المحرّك ----------

def test_watchdog_silent_when_engine_fresh():
    from relay.home_agent import watchdog_alerts
    assert watchdog_alerts((NOW - timedelta(hours=3)).isoformat(), NOW, None) == []


def test_watchdog_alerts_owner_and_group_when_engine_stale():
    from relay.home_agent import watchdog_alerts
    alerts = watchdog_alerts((NOW - timedelta(hours=10)).isoformat(), NOW, None)
    chats = {c for c, _ in alerts}
    assert chats == {"owner", "group"}
    assert all("10 ساعات" in t or "10" in t for _, t in alerts)


def test_watchdog_alerts_once_per_day():
    from relay.home_agent import watchdog_alerts
    assert watchdog_alerts((NOW - timedelta(hours=10)).isoformat(), NOW, NOW.date().isoformat()) == []


def test_watchdog_alerts_when_engine_never_ran():
    from relay.home_agent import watchdog_alerts
    assert {c for c, _ in watchdog_alerts(None, NOW, None)} == {"owner"}


def test_upload_creates_inbox_branch_when_missing(monkeypatch):
    """خطأ حقيقي: عند غياب الفرع يطبع غيت هاب رسالة خطأ، فقُرئت كأنها معرّف ملف ولم يُنشأ الفرع."""
    import subprocess
    from relay import home_agent
    calls = []

    def fake_gh(*args, stdin=None):
        calls.append(args)
        if "contents/inbox.json?ref=inbox" in args[1]:
            return subprocess.CompletedProcess(args, 1, '{"message":"No commit found for the ref inbox"}', "404")
        if args[1].endswith("git/ref/heads/main"):
            return subprocess.CompletedProcess(args, 0, "abc123\n", "")
        return subprocess.CompletedProcess(args, 0, "{}", "")
    monkeypatch.setattr(home_agent, "_gh", fake_gh)
    assert home_agent.upload({"u": {"ok": True}}) == "تم"
    assert any(a[1].endswith("git/refs") for a in calls)
    put = next(a for a in calls if "-X" in a)
    assert '"sha"' not in json.dumps(put)


@respx.mock
def test_agent_fetches_in_parallel():
    import time
    urls = [f"https://s{i}.example.sa/p" for i in range(8)]
    for u in urls:
        respx.get(u).mock(side_effect=lambda req: (time.sleep(0.4), httpx.Response(200, html=PAGE))[1])
    t0 = time.time()
    inbox = build_inbox(urls, httpx.Client(), NOW, resolve=lambda h: "45.1.2.3")
    assert len(inbox) == 8 and time.time() - t0 < 2.0


def test_backup_trigger_when_github_schedule_skipped():
    from relay.home_agent import should_trigger_engine
    assert should_trigger_engine((NOW - timedelta(hours=3, minutes=30)).isoformat(), NOW) is True
    assert should_trigger_engine((NOW - timedelta(hours=1)).isoformat(), NOW) is False
    assert should_trigger_engine(None, NOW) is True
