"""مرسل تيليجرام: نجاح الإرسال يثبت بإيصال (رقم الرسالة)، وأي فشل يرمي DeliveryError بالعربي."""
from __future__ import annotations

from dataclasses import dataclass

import httpx


class DeliveryError(Exception):
    pass


@dataclass(frozen=True)
class Receipt:
    message_id: int


def send(token: str, chat_id: str, text: str, client: httpx.Client) -> Receipt:
    try:
        r = client.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                        json={"chat_id": chat_id, "text": text[:4000],
                              "disable_web_page_preview": True})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise DeliveryError(f"[تيليجرام] تعذّر الإرسال: {type(e).__name__}") from e
    if not data.get("ok"):
        raise DeliveryError(f"[تيليجرام] رفض الرسالة: {data.get('description', r.status_code)}")
    return Receipt(int(data["result"]["message_id"]))
