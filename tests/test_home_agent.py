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


def _fake_gh(calls, ref_exists):
    import subprocess

    def fake_gh(*args, stdin=None):
        calls.append((args, stdin))
        if "PATCH" in args and not ref_exists:
            return subprocess.CompletedProcess(args, 1, '{"message":"Reference does not exist"}', "422")
        return subprocess.CompletedProcess(args, 0, f"sha-{len(calls)}\n", "")
    return fake_gh


def test_upload_replaces_inbox_with_one_commit_without_history(monkeypatch):
    """الفرع لا يكبر: كل رفع التزام جديد بلا أب يحل محل السابق بالقوة."""
    from relay import home_agent
    calls = []
    monkeypatch.setattr(home_agent, "_gh", _fake_gh(calls, ref_exists=True))
    assert home_agent.upload({"u": {"ok": True}}) == "تم"
    commit = json.loads(next(stdin for a, stdin in calls if a[3].endswith("git/commits")))
    assert commit["parents"] == [] and commit["tree"] == "sha-2"
    patch = next((a, stdin) for a, stdin in calls if "PATCH" in a)
    assert json.loads(patch[1]) == {"sha": "sha-3", "force": True}


def test_upload_creates_inbox_branch_when_missing(monkeypatch):
    """خطأ حقيقي سابق: غياب الفرع أول مرة. يُنشأ الفرع على الالتزام الجديد."""
    from relay import home_agent
    calls = []
    monkeypatch.setattr(home_agent, "_gh", _fake_gh(calls, ref_exists=False))
    assert home_agent.upload({"u": {"ok": True}}) == "تم"
    create = json.loads(calls[-1][1])
    assert calls[-1][0][3].endswith("git/refs") and create == {"ref": "refs/heads/inbox", "sha": "sha-3"}


def test_upload_reports_failure(monkeypatch):
    import subprocess
    from relay import home_agent
    monkeypatch.setattr(home_agent, "_gh", lambda *a, stdin=None: subprocess.CompletedProcess(a, 1, "", "boom"))
    assert home_agent.upload({}).startswith("فشل الرفع")


@respx.mock
def test_agent_reads_feed_as_feed_and_keeps_item_links_and_dates():
    """موقع تجميع دخل قائمة الجهاز: يُقرأ موجزاً، ورابط كل إعلان وتاريخه يصلان للمحرّك."""
    feed = ("<?xml version='1.0'?><rss><channel><item><title>شركة علم تعلن برنامج التدريب التعاوني</title>"
            "<link>https://agg.example/1</link><pubDate>Tue, 20 Oct 2026 08:00:00 +0300</pubDate></item>"
            "</channel></rss>")
    respx.get("https://agg.example/feed").mock(return_value=httpx.Response(200, text=feed))
    inbox = build_inbox(["https://agg.example/feed"], httpx.Client(), NOW, resolve=lambda h: "93.184.216.34")
    e = inbox["https://agg.example/feed"]
    assert e["ok"] and e["block_links"] == ["https://agg.example/1"] and e["block_dates"] == ["2026-10-20"]
    set_inbox({"https://agg.example/feed": {**e, "fetched_at": datetime.now(RIYADH).isoformat()}})
    respx.get("https://agg.example/feed").mock(return_value=httpx.Response(403))
    res = fetch(Channel("rss", "https://agg.example/feed"), httpx.Client())
    assert res.ok and res.via == "home" and res.blocks[0].link == "https://agg.example/1"
    assert res.blocks[0].date == "2026-10-20"


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
