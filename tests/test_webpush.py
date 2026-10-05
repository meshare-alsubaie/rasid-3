import json

import httpx
import pytest
import respx

from rasid.notify.telegram import DeliveryError
from rasid.notify.webpush import PushConfig, push_payload, send_push

BASE = "https://push.example.workers.dev"
CFG = PushConfig(BASE, "tok", "PRIVATE_KEY")
SUBS = [{"id": "a", "minStars": 3, "subscription": {"endpoint": "https://fcm/a", "keys": {"p256dh": "x", "auth": "y"}}},
        {"id": "b", "minStars": 5, "subscription": {"endpoint": "https://fcm/b", "keys": {"p256dh": "x", "auth": "y"}}}]


class Gone(Exception):
    def __init__(self, code):
        self.response = type("R", (), {"status_code": code})()


def test_payload_has_entity_for_deep_link_and_stars_for_filter():
    p = json.loads(push_payload("أرامكو السعودية", "aramco", 5, "تدريب تعاوني جديد", "يفتح بعد 21 يوماً"))
    assert p == {"title": "أرامكو السعودية: تدريب تعاوني جديد", "body": "يفتح بعد 21 يوماً", "entity": "aramco", "stars": 5}


@respx.mock
def test_sends_only_to_devices_whose_star_threshold_allows():
    respx.get(f"{BASE}/subs").mock(return_value=httpx.Response(200, json=SUBS))
    sent = []
    n = send_push(CFG, push_payload("x", "e", 4, "t", "b"), httpx.Client(), webpush=lambda **kw: sent.append(kw))
    assert n == 1 and sent[0]["subscription_info"]["endpoint"] == "https://fcm/a"
    assert sent[0]["vapid_private_key"] == "PRIVATE_KEY"
    assert "@" not in json.dumps(sent[0]["vapid_claims"])  # لا إيميل شخصي


@respx.mock
def test_dead_subscription_is_removed():
    respx.get(f"{BASE}/subs").mock(return_value=httpx.Response(200, json=SUBS[:1]))
    deleted = respx.delete(f"{BASE}/subs/a").mock(return_value=httpx.Response(200, json={"ok": True}))

    def boom(**kw):
        raise Gone(410)
    assert send_push(CFG, push_payload("x", "e", 5, "t", "b"), httpx.Client(), webpush=boom) == 0
    assert deleted.called


@respx.mock
def test_no_subscribers_is_success_not_error():
    respx.get(f"{BASE}/subs").mock(return_value=httpx.Response(200, json=[]))
    assert send_push(CFG, push_payload("x", "e", 5, "t", "b"), httpx.Client(), webpush=lambda **kw: None) == 0


@respx.mock
def test_subscription_server_down_raises_delivery_error_so_message_stays_in_outbox():
    respx.get(f"{BASE}/subs").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(DeliveryError):
        send_push(CFG, push_payload("x", "e", 5, "t", "b"), httpx.Client(), webpush=lambda **kw: None)


def test_missing_config_raises_delivery_error():
    with pytest.raises(DeliveryError):
        send_push(PushConfig("", "", ""), push_payload("x", "e", 5, "t", "b"), httpx.Client(), webpush=lambda **kw: None)
