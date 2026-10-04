"""طابور الإعادة: كل نص لم يُحكم عليه يبقى هنا ظاهراً حتى يُحكم. لا شيء يُحذف بسبب فشل."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

STUCK_ATTEMPTS = 5
STUCK_AGE = timedelta(hours=24)


@dataclass
class QueueItem:
    id: str
    entity_id: str
    url: str
    text: str
    reason_ar: str
    first_seen: datetime
    attempts: int = 1
    last_try: datetime | None = None
    recheck_of: str | None = None  # نوع الحكم السابق إن كانت هذه إعادة فحص بالنموذج الأساسي


class RetryQueue:
    def __init__(self) -> None:
        self.items: dict[str, QueueItem] = {}

    def add(self, item_id: str, entity_id: str, url: str, text: str, reason_ar: str,
            now: datetime, recheck_of: str | None = None) -> None:
        if item_id in self.items:
            return
        self.items[item_id] = QueueItem(item_id, entity_id, url, text, reason_ar, now,
                                        last_try=now, recheck_of=recheck_of)

    def fail(self, item_id: str, reason_ar: str, now: datetime) -> None:
        it = self.items[item_id]
        it.attempts += 1
        it.reason_ar = reason_ar
        it.last_try = now

    def due(self, now: datetime) -> list[QueueItem]:
        """تأخير متزايد: ساعة، ساعتان، أربع... بحد أقصى ١٢ ساعة."""
        out = []
        for it in self.items.values():
            wait = timedelta(hours=min(2 ** (it.attempts - 1), 12))
            if it.last_try is None or now - it.last_try >= wait:
                out.append(it)
        return out

    def stuck(self, now: datetime) -> list[QueueItem]:
        return [it for it in self.items.values()
                if it.attempts >= STUCK_ATTEMPTS or now - it.first_seen >= STUCK_AGE]

    def mark_done(self, item_id: str) -> None:
        self.items.pop(item_id, None)

    def to_dict(self) -> dict:
        return {k: {**asdict(v), "first_seen": v.first_seen.isoformat(),
                    "last_try": v.last_try.isoformat() if v.last_try else None}
                for k, v in self.items.items()}

    @classmethod
    def from_dict(cls, d: dict) -> RetryQueue:
        q = cls()
        for k, v in d.items():
            v = dict(v)
            v["first_seen"] = datetime.fromisoformat(v["first_seen"])
            v["last_try"] = datetime.fromisoformat(v["last_try"]) if v.get("last_try") else None
            q.items[k] = QueueItem(**v)
        return q
