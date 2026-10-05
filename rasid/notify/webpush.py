"""التنبيه المباشر للأجهزة (تطبيق راصد المثبّت): يجلب الاشتراكات المجهولة من خادم كلاودفلير ويرسل لكل جهاز يسمح حدّ نجومه.

الفشل الكامل (خادم الاشتراكات لا يرد) يرمي DeliveryError فتبقى الرسالة في صندوق الصادر.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import httpx

from rasid.notify.telegram import DeliveryError

# هوية المرسل في بروتوكول التنبيهات: رابط المستودع العام لا إيميل شخصي
VAPID_CLAIMS = {"sub": "https://github.com/meshare-alsubaie/rasid-3"}


@dataclass(frozen=True)
class PushConfig:
    base: str
    token: str
    vapid_private: str


def push_payload(entity_name: str, entity_id: str, stars: int, headline: str, body: str) -> str:
    return json.dumps({"title": f"{entity_name}: {headline}", "body": body, "entity": entity_id, "stars": stars},
                      ensure_ascii=False)


def _default_webpush(**kw):
    from pywebpush import webpush
    return webpush(**kw)


def send_push(cfg: PushConfig, payload: str, client: httpx.Client,
              webpush: Callable[..., object] = _default_webpush) -> int:
    if not (cfg.base and cfg.token and cfg.vapid_private):
        raise DeliveryError("[التنبيه المباشر] الإعداد ناقص (رابط الخادم أو الرمز أو مفتاح التشفير)")
    auth = {"Authorization": f"Bearer {cfg.token}"}
    try:
        subs = client.get(f"{cfg.base}/subs", headers=auth, timeout=30).raise_for_status().json()
    except (httpx.HTTPError, ValueError) as e:
        raise DeliveryError(f"[التنبيه المباشر] خادم الاشتراكات لا يرد: {type(e).__name__}") from e
    stars = json.loads(payload).get("stars", 5)
    sent = 0
    for s in subs:
        if s.get("minStars", 3) > stars:
            continue
        try:
            webpush(subscription_info=s["subscription"], data=payload, vapid_private_key=cfg.vapid_private,
                    vapid_claims=dict(VAPID_CLAIMS), ttl=86400)
            sent += 1
        except Exception as e:  # noqa: BLE001 — جهاز واحد لا يوقف البقية
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):  # الجهاز ألغى الاشتراك أو انحذف التطبيق
                try:
                    client.delete(f"{cfg.base}/subs/{s['id']}", headers=auth, timeout=15)
                except httpx.HTTPError:
                    pass
    return sent
