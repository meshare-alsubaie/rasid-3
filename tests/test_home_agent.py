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
