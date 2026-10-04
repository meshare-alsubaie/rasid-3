import httpx
import respx

from rasid.entities import Channel
from rasid.fetch import fetch
from relay.server import check_request

PAGE = "<html><body><main><p>برنامج التدريب التعاوني لطلاب الجامعات يفتح قريباً.</p></main></body></html>"
URL = "https://careers.sdaia.gov.sa/coop"
RELAY = "https://relay.example.test/fetch"


# ---------- العميل: الجالب يلجأ لخادم جدة عند الحجب ----------

@respx.mock
def test_blocked_site_is_fetched_through_relay(monkeypatch):
    monkeypatch.setenv("RASID_RELAY_URL", RELAY)
    monkeypatch.setenv("RASID_RELAY_TOKEN", "t0ken")
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    relay = respx.post(RELAY).mock(return_value=httpx.Response(200, json={
        "status": 200, "url": URL, "text": PAGE}))
    r = fetch(Channel("web", URL), httpx.Client())
    assert r.ok and "التدريب التعاوني" in r.blocks[0].text and r.via == "relay"
    assert relay.calls[0].request.headers["x-relay-token"] == "t0ken"


@respx.mock
def test_no_relay_configured_reports_failure(monkeypatch):
    monkeypatch.delenv("RASID_RELAY_URL", raising=False)
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    r = fetch(Channel("web", URL), httpx.Client())
    assert not r.ok


@respx.mock
def test_relay_down_reports_both_reasons(monkeypatch):
    monkeypatch.setenv("RASID_RELAY_URL", RELAY)
    monkeypatch.setenv("RASID_RELAY_TOKEN", "t")
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    respx.post(RELAY).mock(side_effect=httpx.ConnectError("down"))
    r = fetch(Channel("web", URL), httpx.Client())
    assert not r.ok and "جدة" in r.error_ar


@respx.mock
def test_direct_success_does_not_use_relay(monkeypatch):
    monkeypatch.setenv("RASID_RELAY_URL", RELAY)
    respx.get(URL).mock(return_value=httpx.Response(200, html=PAGE))
    relay = respx.post(RELAY)
    r = fetch(Channel("web", URL), httpx.Client())
    assert r.ok and r.via == "direct" and relay.call_count == 0


# ---------- الخادم: حماية من إساءة الاستخدام ----------

def test_server_rejects_wrong_token():
    assert check_request({"url": URL}, "bad", "good", resolve=lambda h: "1.2.3.4")[0] == 403


def test_server_rejects_non_http():
    assert check_request({"url": "file:///etc/passwd"}, "k", "k", resolve=lambda h: "1.2.3.4")[0] == 400


def test_server_blocks_internal_addresses():
    for ip in ["169.254.169.254", "127.0.0.1", "10.0.0.5", "192.168.1.1", "::1"]:
        assert check_request({"url": "http://evil.example/"}, "k", "k", resolve=lambda h, ip=ip: ip)[0] == 400


def test_server_accepts_public_address():
    assert check_request({"url": URL}, "k", "k", resolve=lambda h: "45.1.2.3") == (200, URL)
