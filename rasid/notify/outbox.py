"""صندوق الصادر: الرسالة تبقى فيه حتى يصل إيصالها. يحترم ساعات الهدوء، ولا يرسل نفس الرسالة مرتين."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from rasid.dates import in_quiet_hours
from rasid.notify.telegram import DeliveryError

Sender = Callable[[str, str], int]  # (القناة، النص) -> رقم الرسالة


class Outbox:
    def __init__(self) -> None:
        self.pending: dict[str, dict] = {}
        self.receipts: dict[str, int] = {}

    def enqueue(self, msg_id: str, chat: str, text: str, now: datetime, urgent: bool = False) -> None:
        if msg_id in self.receipts or msg_id in self.pending:
            return
        self.pending[msg_id] = {"chat": chat, "text": text, "created": now.isoformat(),
                                "urgent": urgent, "errors": []}

    def flush(self, now: datetime, sender: Sender) -> int:
        sent = 0
        quiet = in_quiet_hours(now)
        for msg_id, m in sorted(self.pending.items(), key=lambda kv: kv[1]["created"]):
            if quiet and not m["urgent"]:
                continue
            try:
                self.receipts[msg_id] = sender(m["chat"], m["text"])
            except DeliveryError as e:
                m["errors"] = (m["errors"] + [f"{now.isoformat()} {e}"])[-5:]
                continue
            sent += 1
        for msg_id in self.receipts:
            self.pending.pop(msg_id, None)
        return sent

    def to_dict(self) -> dict:
        return {"pending": self.pending, "receipts": self.receipts}

    @classmethod
    def from_dict(cls, d: dict) -> Outbox:
        ob = cls()
        ob.pending = dict(d.get("pending", {}))
        ob.receipts = dict(d.get("receipts", {}))
        return ob
