"""المنسّق: جولة واحدة كاملة. كل مصدر معزول، ولا يُعلَّم شيء «تمّ» إلا بعد نجاح حقيقي."""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from rasid.classify.chain import Pending
from rasid.classify.schema import RELEVANT, Verdict
from rasid.diff import new_blocks
from rasid.entities import Channel, Entity
from rasid.fetch import FetchResult
from rasid.notify.outbox import Outbox
from rasid.notify.templates import KIND_AR, reminders, render
from rasid.programs import Programs, status_of
from rasid.queue import QueueItem, RetryQueue

MAX_INPUT = 9000          # حد طول النص المرسل للمصنّف
SEEN_CAP = 3000           # أقصى بصمات محفوظة لكل قناة
DEAD_AFTER = timedelta(hours=72)
DIGEST_HOUR = 7
FETCH_WORKERS = 8


@dataclass
class Deps:
    fetch: Callable[[Channel], FetchResult]
    classify: Callable[[str], Verdict | Pending]
    send: Callable[[str, str], int]  # (group|owner, نص) -> رقم الرسالة


@dataclass
class RunReport:
    fetch_ok: int = 0
    fetch_fail: int = 0
    new_items: int = 0
    verdicts: int = 0
    pending: int = 0
    sent: int = 0
    errors: list[str] = field(default_factory=list)


class State:
    def __init__(self) -> None:
        self.seen: dict[str, list[str]] = {}
        self.health: dict[str, dict] = {}
        self.programs = Programs()
        self.queue = RetryQueue()
        self.outbox = Outbox()
        self.meta: dict = {"last_digest": None, "new_since_digest": []}

    def save(self, path: Path) -> None:
        """حفظ ذرّي: يُكتب ملف مؤقت ثم يُستبدل، فالانهيار وسط الحفظ لا يفسد الملف القديم."""
        data = json.dumps({"seen": self.seen, "health": self.health, "programs": self.programs.to_dict(),
                           "queue": self.queue.to_dict(), "outbox": self.outbox.to_dict(),
                           "meta": self.meta}, ensure_ascii=False, indent=1)
        path = Path(path)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> State:
        st = cls()
        if not Path(path).exists():
            return st
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        st.seen, st.health, st.meta = d["seen"], d["health"], d["meta"]
        st.programs = Programs.from_dict(d["programs"])
        st.queue = RetryQueue.from_dict(d["queue"])
        st.outbox = Outbox.from_dict(d["outbox"])
        return st


def _id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _safe_classify(deps: Deps, text: str) -> Verdict | Pending:
    try:
        return deps.classify(text)
    except Exception as e:  # noqa: BLE001 — أي انهيار في المصنّف يصير «معلّق» لا «ضائع»
        return Pending(f"[المصنّف] انهيار: {e}")


def _upcoming(fields: dict, today) -> bool:
    """فيه نافذة تقديم مفتوحة أو قادمة بتاريخ صريح."""
    dates = [v["value"] for k, v in fields.items() if k in ("opens", "closes") and v.get("value")]
    return any(datetime.fromisoformat(d).date() >= today for d in dates)


def _handle(st: State, deps: Deps, now: datetime, entity_id: str, name: str, url: str, text: str,
            item_id: str, rep: RunReport, queued: QueueItem | None = None, first_sight: bool = False) -> None:
    r = _safe_classify(deps, text)
    recheck_of = queued.recheck_of if queued else None
    if isinstance(r, Pending) or (recheck_of and r.needs_recheck):
        rep.pending += 1
        reason = r.reason_ar if isinstance(r, Pending) else "المؤكّد ما زال غير متاح"
        if queued:
            st.queue.fail(queued.id, reason, now)
        else:
            st.queue.add(item_id, entity_id, url, text, reason, now)
        return
    rep.verdicts += 1
    if queued:
        st.queue.mark_done(queued.id)
    if recheck_of and r.kind != recheck_of and recheck_of in RELEVANT:
        st.outbox.enqueue(f"fix:{item_id}", "group",
                          f"🔁 تصحيح: {name}\nالتصنيف السابق «{KIND_AR.get(recheck_of, recheck_of)}» "
                          f"غير دقيق، والصحيح «{KIND_AR.get(r.kind, 'غير ذي صلة')}».", now)
    p, change = st.programs.merge(entity_id, r, url, now)
    # أول مرة نرى الصفحة: لا ننبّه إلا لنافذة مفتوحة أو قادمة (الصفحات الدائمة والبرامج المنتهية تُحفظ بهدوء)
    closes = (p.fields.get("closes") or {}).get("value") if p else None
    already_closed = bool(closes) and datetime.fromisoformat(closes).date() < now.date()
    quiet = already_closed or (first_sight and p is not None and not _upcoming(p.fields, now.date()))
    if change and p and p.family == "student" and not quiet:
        st.outbox.enqueue(f"{change.kind}:{p.key}:{_id(change.detail_ar)}", "group", render(change, p, name, now.date()), now)
        st.meta["new_since_digest"].append(p.key)
    if r.needs_recheck and not recheck_of:
        st.queue.add("re:" + item_id, entity_id, url, text, "إعادة فحص بالنموذج الأساسي", now, recheck_of=r.kind)


def _safe_fetch(deps: Deps, e: Entity, ch: Channel) -> FetchResult:
    try:
        return deps.fetch(ch)
    except Exception as ex:  # noqa: BLE001 — مصدر واحد لا يسقط الجولة
        return FetchResult(False, ch.url, error_ar=f"[الجالب][{e.name_ar}][{ch.url}] انهيار: {ex}")


def _fetch_channel(st: State, deps: Deps, now: datetime, e: Entity, ch: Channel, rep: RunReport,
                   res: FetchResult) -> None:
    h = st.health.setdefault(ch.url, {"entity": e.id, "name": e.name_ar, "last_success": None,
                                      "last_error_ar": None, "consecutive_failures": 0, "first_failure": None})
    if not res.ok:
        rep.fetch_fail += 1
        h["consecutive_failures"] += 1
        h["first_failure"] = h["first_failure"] or now.isoformat()
        h["last_error_ar"] = res.error_ar
        rep.errors.append(res.error_ar or "")
        return
    rep.fetch_ok += 1
    h.update(last_success=now.isoformat(), consecutive_failures=0, first_failure=None, last_error_ar=None,
             via=res.via)
    prev = st.seen.get(ch.url, [])
    fresh = new_blocks(set(prev), res)
    if not fresh:
        return
    rep.new_items += 1
    body = "\n".join(b.text for b in fresh)[:MAX_INPUT]
    links = "\n".join(f"{t}: {u}" for t, u in res.links[:40])
    text = f"الجهة: {e.name_ar}\nالرابط: {ch.url}\n\nالنص:\n{body}" + (f"\n\nروابط الصفحة:\n{links}" if links else "")
    _handle(st, deps, now, e.id, e.name_ar, ch.url, text, _id(ch.url, body), rep, first_sight=ch.url not in st.seen)
    # تُعلَّم مقروءة فقط بعد حكم أو دخول الطابور (النص محفوظ فيه، فلا ضياع)
    st.seen[ch.url] = (prev + [b.hash for b in fresh])[-SEEN_CAP:]


def _digests(st: State, now: datetime, entities: list[Entity]) -> None:
    today = now.date()
    if now.hour < DIGEST_HOUR or st.meta.get("last_digest") == today.isoformat():
        return
    names = {e.id: e.name_ar for e in entities}
    open_now, closing = [], []
    for p in st.programs.items.values():
        if p.family != "student":
            continue
        s = status_of({k: v["value"] for k, v in p.fields.items() if k in ("opens", "closes")}, today)
        (closing if s == "closing_soon" else open_now if s == "open" else []).append(names.get(p.entity_id, p.entity_id))
    new = len(set(st.meta["new_since_digest"]))
    lines = ["☀️ ملخّص راصد الصباحي"]
    if open_now:
        lines.append("🟢 مفتوح الآن: " + "، ".join(open_now))
    if closing:
        lines.append("⏳ يقفل قريباً: " + "، ".join(closing))
    lines.append(f"🆕 جديد منذ أمس: {new}" if new else "ما فيه جديد.")
    lines.append("راصد شغّال ✅")
    st.outbox.enqueue(f"digest:{today}", "group", "\n".join(lines), now)
    total = len(st.health)
    bad = [h for h in st.health.values() if h["consecutive_failures"]]
    owner = [f"🛠️ تقرير المحرّك اليومي ({today})",
             f"المصادر السليمة: {total - len(bad)} من {total}",
             f"طابور الإعادة: {len(st.queue.items)} (العالق: {len(st.queue.stuck(now))})",
             f"رسائل تنتظر الإرسال: {len(st.outbox.pending)}"]
    owner += [f"• {h['name']}: {h['last_error_ar']}" for h in bad[:8]]
    st.outbox.enqueue(f"owner-digest:{today}", "owner", "\n".join(owner), now, urgent=True)
    st.meta["last_digest"] = today.isoformat()
    st.meta["new_since_digest"] = []


def saudi_list(st: State) -> list[str]:
    """المصادر التي يجلبها جهاز المؤسس: كل ما فشل من السحابة، وما يُقرأ أصلاً عبر الجهاز."""
    return sorted(u for u, h in st.health.items() if h["consecutive_failures"] > 0 or h.get("via") == "home")


def run_once(now: datetime, entities: list[Entity], st: State, deps: Deps) -> RunReport:
    rep = RunReport()
    names = {e.id: e.name_ar for e in entities}
    jobs = [(e, ch) for e in entities for ch in e.channels if ch.kind in ("web", "rss")]
    # الجلب بالتوازي (المواقع المحجوبة بطيئة)، والمعالجة بالترتيب حتى تبقى الحالة متسقة
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(lambda j: _safe_fetch(deps, *j), jobs))
    for (e, ch), res in zip(jobs, results):
        _fetch_channel(st, deps, now, e, ch, rep, res)
    for it in st.queue.due(now):
        _handle(st, deps, now, it.entity_id, names.get(it.entity_id, it.entity_id), it.url, it.text,
                it.id, rep, queued=it)
    for msg_id, text in reminders(list(st.programs.items.values()), now.date(), names):
        st.outbox.enqueue(msg_id, "group", text, now)
    for it in st.queue.stuck(now):
        st.outbox.enqueue(f"stuck:{it.id}", "owner",
                          f"⚠️ عالق في طابور الإعادة: {names.get(it.entity_id, it.entity_id)}\n"
                          f"المحاولات: {it.attempts}\nالسبب: {it.reason_ar}", now, urgent=True)
    for url, h in st.health.items():
        if h["first_failure"] and now - datetime.fromisoformat(h["first_failure"]) >= DEAD_AFTER:
            st.outbox.enqueue(f"dead:{url}:{now.date()}", "owner",
                              f"🔴 مصدر لا يُقرأ منذ ٣ أيام: {h['name']}\n{url}\nالسبب: {h['last_error_ar']}",
                              now, urgent=True)
    _digests(st, now, entities)
    rep.sent = st.outbox.flush(now, deps.send)
    return rep
