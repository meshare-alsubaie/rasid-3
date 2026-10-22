"""المنسّق: جولة واحدة كاملة. كل مصدر معزول، ولا يُعلَّم شيء «تمّ» إلا بعد نجاح حقيقي."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import cached_property
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from rasid.classify.chain import CONTEXT_MARK, Pending
from rasid.classify.schema import RELEVANT, Verdict
from rasid.dates import _DIGITS
from rasid.diff import new_blocks
from rasid.entities import Aggregator, Channel, Entity, agg_sites, official_first, site_of
from rasid.fetch import Block, FetchResult, block_hash
from rasid.match import find_entity, outside_id
from rasid.notify.outbox import Outbox
from rasid.notify.templates import KIND_AR, countdown, days_ar, reminders, render, update_detail
from rasid.notify.webpush import push_payload
from rasid.programs import FAMILY, Change, Program, Programs, program_status
from rasid.queue import QueueItem, RetryQueue

MAX_INPUT = 9000          # حد طول النص المرسل للمصنّف
MAX_FRESH = 6000          # حصة الجديد منه، والباقي سياق من بقية الصفحة
SEEN_CAP = 3000           # أقصى بصمات محفوظة لكل قناة
DEAD_AFTER = timedelta(hours=72)
DIGEST_HOUR = 7
FETCH_WORKERS = 8
FOLLOW_MAX = 3            # روابط تدريب جديدة تُفتح من كل صفحة في الجولة
FOLLOW_RUN_MAX = 40       # وحد أعلى للجولة كلها حماية لحصة الذكاء
FOLLOW_TRIES = 12         # رابط متبوع فشل جلبه يُعاد (وجهاز المؤسس يجلبه) يوماً كاملاً قبل تركه
AGG_MAX = 8               # إعلانات تُقرأ من كل موقع تجميع في الجولة
AGG_STALE_DAYS = 14       # منشور تجميع أقدم من هذا: «التسجيل مفتوح» فيه خبر قديم لا يُعتمد
RECEIPTS_CAP = 5000       # إيصالات الرسائل المحفوظة لمنع التكرار (الأقدم يُحذف)
QUEUE_MAX_AGE = timedelta(days=7)
VERDICT_LOG = 400
AGG = "_agg"              # معرّف مواقع التجميع في الطابور والسجل
LIVE = ("announced", "open", "closing_soon")

# عنوان رابط يدل على برنامج تدريب أو تخرج يستحق فتح صفحته
TRAINING = re.compile(r"تعاوني|تدريب|co-?op\b|intern(?:s|ships?)?\b|trainee|تمهير|حديثي التخرج|graduate|خريجين"
                      r"|summer|صيفي", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:202[6-9]|144[7-9])\b")  # يُطبَّق بعد تحويل الأرقام العربية (١٤٤٨)
_ATS = re.compile(r"hr\.cloud\.sap|successfactors|taleo|oraclecloud|myworkdayjobs|workday|jobs\.|careers?\.",
                  re.IGNORECASE)


@dataclass
class Deps:
    fetch: Callable[[Channel], FetchResult]
    classify: Callable[[str], Verdict | Pending]
    send: Callable[[str, str], int]  # (group|owner|push, نص) -> رقم الرسالة


@dataclass
class RunReport:
    fetch_ok: int = 0
    fetch_fail: int = 0
    new_items: int = 0
    verdicts: int = 0
    pending: int = 0
    sent: int = 0
    deferred: int = 0
    followed: int = 0
    kinds: Counter = field(default_factory=Counter)
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


@dataclass
class Ctx:
    """ما تحتاجه الجولة كلها: الحالة، الأدوات، الوقت، الجهات، والتقرير."""
    st: State
    deps: Deps
    now: datetime
    entities: list[Entity]
    rep: RunReport
    over: Callable[[], bool]
    follows_left: int = FOLLOW_RUN_MAX
    agg_sites: frozenset[str] = frozenset()

    @cached_property
    def names(self) -> dict[str, str]:
        return {e.id: e.name_ar for e in self.entities}

    def name_of(self, p: Program) -> str:
        return self.names.get(p.entity_id) or (p.fields.get("entity_name") or {}).get("value") or p.entity_id

    def stars_of(self, entity_id: str) -> int:
        return next((e.stars_manual or 3 for e in self.entities if e.id == entity_id), 3)


def _id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _safe_classify(deps: Deps, text: str) -> Verdict | Pending:
    try:
        return deps.classify(text)
    except Exception as e:  # noqa: BLE001 — أي انهيار في المصنّف يصير «معلّق» لا «ضائع»
        return Pending(f"[المصنّف] انهيار: {e}")


def _upcoming(fields: dict, today) -> bool:
    """فيه نافذة تقديم مفتوحة أو قادمة بتاريخ صريح، أو قال المصدر إن التسجيل مفتوح الآن."""
    dates = [v["value"] for k, v in fields.items() if k in ("opens", "closes") and v.get("value")]
    if dates:
        return any(datetime.fromisoformat(d).date() >= today for d in dates)
    return (fields.get("accepting_now") or {}).get("value") is True


HEADLINE = {"new": "جديد", "dates": "أعلنت المواعيد", "opened": "فتح التسجيل", "hint": "تلميح غير مؤكّد",
            "important_update": "تحديث مهم"}


def _push_text(change: Change, p: Program, name: str, stars: int, today) -> str:
    """نص التنبيه المباشر للجوال: سطران، والضغط يفتح بطاقة الجهة (entity)."""
    head = HEADLINE.get(change.kind, "جديد")
    if change.kind == "new":
        head = f"{KIND_AR.get(p.kind, 'فرصة')} جديد"
    cd = countdown((p.fields.get("opens") or {}).get("value"), (p.fields.get("closes") or {}).get("value"), today)
    body = (cd or "").replace("⏱️ ", "") or update_detail(change.detail_ar) or "اضغط لتفاصيل البرنامج ورابط التقديم"
    return push_payload(name, p.entity_id, stars, head, body)


def _alert(c: Ctx, change: Change, p: Program) -> None:
    name = c.name_of(p)
    msg_id = f"{change.kind}:{p.key}:{_id(change.detail_ar)}"
    c.st.outbox.enqueue(msg_id, "group", render(change, p, name, c.now.date(), c.agg_sites), c.now)
    c.st.outbox.enqueue("push:" + msg_id, "push", _push_text(change, p, name, c.stars_of(p.entity_id), c.now.date()),
                        c.now)
    c.st.meta["new_since_digest"].append(p.key)
    if program_status(p, c.now.date()) in LIVE:
        p.alerted = True


def _log(c: Ctx, entity_id: str, url: str, r: Verdict | Pending, note: str = "") -> None:
    """سجل الأحكام: لماذا رأى راصد ما رأى. يبقى آخر ٤٠٠ في الحالة."""
    if isinstance(r, Pending):
        row = {"kind": "pending", "why": r.reason_ar[:200]}
    else:
        f = lambda k: (r.fields.get(k).value if r.fields.get(k) else None)  # noqa: E731
        row = {"kind": r.kind, "model": r.model, "title": f("title"), "opens": str(f("opens") or "") or None,
               "closes": str(f("closes") or "") or None, "open_now": f("accepting_now"),
               "why": " | ".join(r.notes[-2:])[:300] or None}
    c.rep.kinds[row["kind"]] += 1
    log = c.st.meta.setdefault("verdicts", [])
    log.append({"at": c.now.isoformat(timespec="minutes"), "entity": entity_id, "url": url, **row,
                **({"note": note} if note else {})})
    del log[:-VERDICT_LOG]


Resolver = Callable[[Verdict, str], "tuple[str, str] | None"]


def _handle(c: Ctx, entity_id: str, url: str, text: str, item_id: str,
            queued: QueueItem | None = None, first_sight: bool = False, resolve: Resolver | None = None,
            stale: bool = False) -> None:
    st, now = c.st, c.now
    r = _safe_classify(c.deps, text)
    if stale and not isinstance(r, Pending):  # منشور قديم: «التسجيل مفتوح» فيه خبر مضى
        r.fields.pop("accepting_now", None)
    recheck_of = queued.recheck_of if queued else None
    if isinstance(r, Pending) or (recheck_of and r.needs_recheck):
        c.rep.pending += 1
        reason = r.reason_ar if isinstance(r, Pending) else "المؤكّد ما زال غير متاح"
        if queued:
            st.queue.fail(queued.id, reason, now)
        else:
            st.queue.add(item_id, entity_id, url, text, reason, now)
        _log(c, entity_id, url, r if isinstance(r, Pending) else Pending(reason))
        return
    c.rep.verdicts += 1
    if queued:
        st.queue.mark_done(queued.id)
    if resolve is not None:  # إعلان من موقع تجميع: صاحبه يُعرف من نصه
        who = resolve(r, text) if r.kind != "irrelevant" else None
        _log(c, who[0] if who else entity_id, url, r, note="من موقع تجميع")
        if who is None:
            return
        entity_id, name = who
    else:
        _log(c, entity_id, url, r)
        name = c.names.get(entity_id, entity_id)
    if recheck_of and r.kind != recheck_of and recheck_of in RELEVANT:
        st.outbox.enqueue(f"fix:{item_id}", "group",
                          f"🔁 تصحيح: {name}\nالتصنيف السابق «{KIND_AR.get(recheck_of, recheck_of)}» "
                          f"غير دقيق، والصحيح «{KIND_AR.get(r.kind, 'غير ذي صلة')}».", now)
    p, change = st.programs.merge(entity_id, r, url, now)
    if p is not None:
        p.sources = official_first(p.sources, c.agg_sites)
    # أول مرة نرى الصفحة: لا ننبّه إلا لنافذة مفتوحة أو قادمة (الصفحات الدائمة والبرامج المنتهية تُحفظ بهدوء)
    closed = p is not None and program_status(p, now.date()) == "closed"
    quiet = closed or (first_sight and p is not None and not _upcoming(p.fields, now.date()))
    if change and p and p.family == "student" and not quiet:
        _alert(c, change, p)
    if r.needs_recheck and not recheck_of:
        st.queue.add("re:" + item_id, entity_id if resolve is None else AGG, url, text,
                     "إعادة فحص بالنموذج الأساسي", now, recheck_of=r.kind)


def _resolver(entities: list[Entity]) -> Resolver:
    """صاحب الإعلان: اسم الجهة الذي استخرجه المصنّف، ثم عنوان الإعلان. جهة خارج القائمة تُقبل للبرامج الطلابية فقط."""
    def resolve(v: Verdict, text: str) -> tuple[str, str] | None:
        named = (v.fields.get("entity_name").value if v.fields.get("entity_name") else "") or ""
        title = next((l.split(":", 1)[1] for l in text.splitlines() if l.startswith("عنوان الإعلان:")), "")
        e = find_entity(named, entities) or find_entity(title, entities)
        if e is not None:
            return e.id, e.name_ar
        oid = outside_id(named) if named else None
        if oid and FAMILY.get(v.kind) == "student":
            return oid, named
        return None
    return resolve


def _safe_fetch(deps: Deps, ch: Channel, label: str) -> FetchResult:
    try:
        return deps.fetch(ch)
    except Exception as ex:  # noqa: BLE001 — مصدر واحد لا يسقط الجولة
        return FetchResult(False, ch.url, error_ar=f"[الجالب][{label}][{ch.url}] انهيار: {ex}")


def _record_health(c: Ctx, entity_id: str, name: str, url: str, res: FetchResult) -> bool:
    h = c.st.health.setdefault(url, {"entity": entity_id, "name": name, "last_success": None,
                                     "last_error_ar": None, "consecutive_failures": 0, "first_failure": None})
    if not res.ok:
        c.rep.fetch_fail += 1
        h["consecutive_failures"] += 1
        h["first_failure"] = h["first_failure"] or c.now.isoformat()
        h.update(last_error_ar=res.error_ar, junk=res.junk)
        c.rep.errors.append(res.error_ar or "")
        return False
    c.rep.fetch_ok += 1
    h.update(last_success=c.now.isoformat(), consecutive_failures=0, first_failure=None, last_error_ar=None,
             via=res.via, junk=False)
    return True


def _context_text(name: str, url: str, fresh: list[Block], res: FetchResult) -> str:
    """الجديد أولاً، ثم بقية الصفحة سياقاً: سطر «التقديم من ٢٦ أكتوبر» وحده لا يكفي ليُفهم."""
    fresh_ids = {id(b) for b in fresh}
    new = "\n".join(b.text for b in fresh)[:MAX_FRESH]
    rest = "\n".join(b.text for b in res.blocks if id(b) not in fresh_ids)
    head = f"الجهة: {name}\nالرابط: {url}\n\n"
    if rest:
        body = f"الجديد في الصفحة:\n{new}\n\n{CONTEXT_MARK}\n{rest[:max(0, MAX_INPUT - len(new))]}"
    else:
        body = f"النص:\n{new}"
    links = "\n".join(f"{t}: {u}" for t, u in res.links[:40])
    return head + body + (f"\n\nروابط الصفحة:\n{links}" if links else "")


LINKS_SCANNED = "L*"  # علامة: روابط هذه الصفحة فُحصت مرة، فكل رابط بعدها جديد فعلاً


def _link_key(url: str) -> str:
    return "L" + block_hash(url)


def _follow_candidates(ch: Channel, res: FetchResult, prev: set[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """روابط تدريب جديدة في الصفحة (نفس الموقع أو بوابة توظيف). أول مرة: ما فيه سنة حالية فقط، والباقي يُحفظ مقروءاً."""
    first = LINKS_SCANNED not in prev
    home = site_of(ch.url)
    pairs = list(res.links) + [(b.text, b.link) for b in res.blocks if b.link]
    out, keys, seen_urls = [], [], set()
    for label, link in pairs:
        u = link.split("#")[0]
        p = urlparse(u)
        if p.scheme not in ("http", "https") or u in seen_urls or u.rstrip("/") == ch.url.rstrip("/") \
                or p.path.lower().endswith((".pdf", ".jpg", ".png", ".docx")) or not TRAINING.search(label):
            continue
        if site_of(u) != home and not _ATS.search(p.netloc):
            continue
        seen_urls.add(u)
        key = _link_key(u)
        if key in prev:
            continue
        keys.append(key)
        if not first or _YEAR.search(label.translate(_DIGITS)):
            out.append((label[:200], u))
    return out, keys


def _follow(c: Ctx, e: Entity, ch: Channel, res: FetchResult, prev: set[str], first_sight: bool) -> list[str]:
    """يفتح صفحات روابط التدريب الجديدة ويصنّفها لنفس الجهة. يرجع بصمات الروابط التي انتهى منها.
    الرابط الذي فشل جلبه لا يُعلَّم مقروءاً: يُعاد كل جولة، ويدخل قائمة جهاز المؤسس، حتى يُقرأ أو تنتهي محاولاته."""
    fails = c.st.meta.setdefault("follow_fail", {})
    cands, keys = _follow_candidates(ch, res, prev)
    cands.sort(key=lambda x: x[1] in fails)  # الجديد قبل ما فشل سابقاً
    wanted = {u for _, u in cands}
    first_links = LINKS_SCANNED not in prev
    done = [k for k in keys if k not in {_link_key(u) for u in wanted}]  # روابط عادية تُحفظ مقروءة
    if first_links:
        done.append(LINKS_SCANNED)
    taken = 0
    for label, u in cands:
        if taken >= FOLLOW_MAX or c.follows_left <= 0 or c.over():
            break  # الباقي يُفتح في الجولة التالية
        taken += 1
        c.follows_left -= 1
        c.rep.followed += 1
        d = _safe_fetch(c.deps, Channel("web", u), e.name_ar)
        if not d.ok:
            n, first = fails.get(u, [0, c.now.isoformat()])
            fails[u] = [n + 1, first]
            if n + 1 >= FOLLOW_TRIES:
                del fails[u]
                done.append(_link_key(u))
            continue
        fails.pop(u, None)
        done.append(_link_key(u))
        body = "\n".join(b.text for b in d.blocks)[:MAX_INPUT]
        text = f"الجهة: {e.name_ar}\nالرابط: {u}\n\nعنوان الرابط في صفحة الجهة: {label}\n\nالنص:\n{body}"
        _handle(c, e.id, u, text, _id(u, body), first_sight=first_sight or first_links)
    return done


def _process_channel(c: Ctx, e: Entity, ch: Channel, res: FetchResult) -> None:
    if not _record_health(c, e.id, e.name_ar, ch.url, res):
        return
    prev = c.st.seen.get(ch.url, [])
    prev_set = set(prev)
    first_sight = ch.url not in c.st.seen
    if c.over():  # انتهت ميزانية الوقت: يُترك للجولة التالية ولا يُعلَّم مقروءاً
        if new_blocks(prev_set, res):
            c.rep.deferred += 1
        return
    links_done = _follow(c, e, ch, res, prev_set, first_sight)
    fresh = new_blocks(prev_set, res)
    if fresh:
        c.rep.new_items += 1
        body = "\n".join(b.text for b in fresh)[:MAX_INPUT]
        _handle(c, e.id, ch.url, _context_text(e.name_ar, ch.url, fresh, res), _id(ch.url, body),
                first_sight=first_sight)
    # تُعلَّم مقروءة فقط بعد حكم أو دخول الطابور (النص محفوظ فيه، فلا ضياع)
    c.st.seen[ch.url] = (prev + [b.hash for b in fresh] + links_done)[-SEEN_CAP:]


def _process_aggregator(c: Ctx, agg: Aggregator, res: FetchResult, resolve: Resolver) -> None:
    """كل إعلان تدريب جديد في موقع التجميع: تُفتح صفحته، ويُصنَّف، ويُنسب لجهته."""
    if not _record_health(c, AGG, agg.name, agg.url, res):
        return
    prev = c.st.seen.get(agg.url, [])
    prev_set = set(prev)
    first_sight = agg.url not in c.st.seen
    done, taken = [], 0
    for b in new_blocks(prev_set, res):
        if not b.link or not TRAINING.search(b.text):
            done.append(b.hash)
            continue
        if taken >= AGG_MAX or c.over():
            c.rep.deferred += 1
            continue
        taken += 1
        c.rep.new_items += 1
        d = _safe_fetch(c.deps, Channel("web", b.link), agg.name)
        body = "\n".join(x.text for x in d.blocks)[:MAX_INPUT] if d.ok else b.text
        text = (f"المصدر: موقع تجميع ({agg.name})\nالرابط: {b.link}\n"
                + (f"تاريخ النشر: {b.date}\n" if b.date else "")
                + f"\nعنوان الإعلان: {b.text[:300]}\n\nالنص:\n{body}")
        stale = bool(b.date) and (c.now.date() - date.fromisoformat(b.date)).days > AGG_STALE_DAYS
        # منشور قديم يُحفظ بهدوء مثل أول مرة: لا تنبيه إلا لموعد قادم صريح
        _handle(c, AGG, b.link, text, _id(b.link, b.text), first_sight=first_sight or stale, resolve=resolve,
                stale=stale)
        done.append(b.hash)
    c.st.seen[agg.url] = (prev + done)[-SEEN_CAP:]


def _safety_net(c: Ctx) -> None:
    """برنامج مفتوح أو بموعد قادم ولم يصل القروب تنبيهه (خلل سابق أو أُضيف بهدوء): يُنبَّه مرة واحدة."""
    for p in c.st.programs.items.values():
        if p.family != "student" or p.alerted or program_status(p, c.now.date()) not in LIVE:
            continue
        has_dates = any((p.fields.get(k) or {}).get("value") for k in ("opens", "closes"))
        _alert(c, Change("dates" if has_dates else "opened", p.key), p)


REMINDER_TAGS = ("open0", "open1", "rem3", "rem1")


def _pending_program(msg_id: str, items: dict[str, Program]) -> tuple[str, str] | None:
    """(نوع الرسالة، مفتاح البرنامج) لتنبيه أو تذكير في الصندوق، وإلا None. المعرّف: النوع:المفتاح:بصمة أو تاريخ."""
    kind, _, rest = msg_id.removeprefix("push:").partition(":")
    if kind not in HEADLINE and kind not in REMINDER_TAGS:
        return None
    key = rest if rest in items else rest.rsplit(":", 1)[0]
    return (kind, key) if key in items else None


def _refresh_pending(c: Ctx) -> None:
    """قبل الإرسال (الرسائل تنتظر ساعات الهدوء): نص التنبيه المنتظر يُكتب من بيانات البرنامج الآن، والتذكير يُلغى
    إذا كان تنبيه نفس البرنامج منتظراً (فيه العدّ التنازلي)، وتنبيه المواعيد أو الفتح يُلغى إذا لم يعد البرنامج
    مفتوحاً أو قادماً."""
    ob, items, today = c.st.outbox, c.st.programs.items, c.now.date()
    refs = {m: r for m in ob.pending if (r := _pending_program(m, items))}
    alerted = {key for kind, key in refs.values() if kind in HEADLINE}
    for msg_id, (kind, key) in refs.items():
        p = items[key]
        if kind in REMINDER_TAGS:
            if key in alerted:
                ob.drop(msg_id)
        elif kind in ("dates", "opened") and program_status(p, today) not in LIVE:
            ob.drop(msg_id)
            c.st.meta["new_since_digest"] = [k for k in c.st.meta["new_since_digest"] if k != key]
        elif kind in ("new", "dates", "opened"):  # هذه بلا تفاصيل في المعرّف، فإعادة كتابتها لا تغيّر معناها
            change, name = Change(kind, key), c.name_of(p)
            ob.pending[msg_id]["text"] = (
                _push_text(change, p, name, c.stars_of(p.entity_id), today) if msg_id.startswith("push:")
                else render(change, p, name, today, c.agg_sites))


def _digests(c: Ctx, aggregators: list[Aggregator]) -> None:
    st, now, today = c.st, c.now, c.now.date()
    if now.hour < DIGEST_HOUR or st.meta.get("last_digest") == today.isoformat():
        return
    open_now, closing, soon = [], [], []
    for p in st.programs.items.values():
        if p.family != "student":
            continue
        s, name = program_status(p, today), c.name_of(p)
        opens = (p.fields.get("opens") or {}).get("value")
        if s == "closing_soon":
            closing.append(name)
        elif s == "open":
            open_now.append(name)
        elif s == "announced" and opens:
            soon.append((opens, f"{name} (بعد {days_ar((datetime.fromisoformat(opens).date() - today).days)})"))
    lines = ["☀️ ملخّص راصد الصباحي"]
    if closing:
        lines.append("⏳ يقفل قريباً: " + "، ".join(sorted(set(closing))))
    if open_now:
        lines.append("🟢 مفتوح الآن: " + "، ".join(sorted(set(open_now))))
    if soon:
        lines.append("📅 يفتح قريباً: " + "، ".join(x for _, x in sorted(set(soon))))
    new = len(set(st.meta["new_since_digest"]))
    lines.append(f"🆕 جديد منذ أمس: {new}" if new else "ما فيه جديد منذ أمس.")
    watched = [e for e in c.entities if e.channels]
    readable = sum(1 for e in watched if any(_healthy(st.health.get(ch.url)) for ch in e.channels))
    agg_ok = sum(1 for a in aggregators if _healthy(st.health.get(a.url)))
    lines.append(f"👁️ يقرأ راصد الآن مواقع {readable} جهة من {len(c.entities)}"
                 + (f"، ومواقع التجميع {agg_ok} من {len(aggregators)}." if aggregators else "."))
    st.outbox.enqueue(f"digest:{today}", "group", "\n".join(lines), now)

    total = len(st.health)
    bad = [h for h in st.health.values() if h["consecutive_failures"]]
    dead = [h for u, h in st.health.items() if h["first_failure"]
            and now - datetime.fromisoformat(h["first_failure"]) >= DEAD_AFTER]
    day_ago = (now - timedelta(days=1)).isoformat()
    kinds = Counter(v["kind"] for v in st.meta.get("verdicts", []) if v["at"] >= day_ago[:16])
    owner = [f"🛠️ تقرير المحرّك اليومي ({today})",
             f"المصادر السليمة: {total - len(bad)} من {total} (غير صالحة: {sum(1 for h in bad if h.get('junk'))}، "
             f"محجوبة أو معطلة: {sum(1 for h in bad if not h.get('junk'))})",
             f"جهات تُقرأ: {readable} من {len(c.entities)}، بلا أي مصدر: {len(c.entities) - len(watched)}",
             "أحكام آخر ٢٤ ساعة: " + ("، ".join(f"{KIND_AR.get(k, k)} {n}" for k, n in kinds.most_common()) or "لا شيء"),
             f"طابور الإعادة: {len(st.queue.items)} (العالق: {len(st.queue.stuck(now))})",
             f"رسائل تنتظر الإرسال: {len(st.outbox.pending)}"]
    if dead:
        owner.append(f"مصادر لا تُقرأ منذ ٣ أيام أو أكثر: {len(dead)}")
        owner += [f"• {h['name']}: {(h['last_error_ar'] or '')[-120:]}" for h in dead[:10]]
    st.outbox.enqueue(f"owner-digest:{today}", "owner", "\n".join(owner), now)
    st.meta["last_digest"] = today.isoformat()
    st.meta["new_since_digest"] = []


def _healthy(h: dict | None) -> bool:
    return bool(h) and h["consecutive_failures"] == 0 and bool(h["last_success"])


def saudi_list(st: State) -> list[str]:
    """المصادر التي يجلبها جهاز المؤسس: كل ما فشل من السحابة، وما يُقرأ أصلاً عبر الجهاز، وروابط التدريب المتبوعة التي فشلت."""
    channels = {u for u, h in st.health.items() if h["consecutive_failures"] > 0 or h.get("via") == "home"}
    follows = list(st.meta.get("follow_fail", {}))[:FOLLOW_RUN_MAX]
    return sorted(channels | set(follows))


def run_once(now: datetime, entities: list[Entity], st: State, deps: Deps,
             deadline: Callable[[], bool] | None = None, checkpoint: Callable[[], None] | None = None,
             checkpoint_every: int = 25, aggregators: list[Aggregator] | None = None) -> RunReport:
    """deadline: إذا رجعت True يتوقف التصنيف بنظافة ويُترك الباقي للجولة التالية.
    checkpoint: حفظ دوري أثناء الجولة حتى لا يضيع شيء لو قُتلت."""
    aggregators = aggregators or []
    st.meta.setdefault("new_since_digest", [])
    c = Ctx(st, deps, now, entities, RunReport(), deadline or (lambda: False), agg_sites=agg_sites(aggregators))
    resolve = _resolver(entities)
    jobs = [(e, ch) for e in entities for ch in e.channels if ch.kind in ("web", "rss")]
    feeds = [Channel(a.kind, a.url) for a in aggregators]
    # رابط حُذف من الملفات لا يبقى في الصحة: لا يُعدّ ميتاً في التقرير، ولا يجلبه جهاز المؤسس
    current = {ch.url for _, ch in jobs} | {ch.url for ch in feeds}
    for url in [u for u in st.health if u not in current]:
        del st.health[url]
    fails = st.meta.setdefault("follow_fail", {})  # رابط متبوع اختفى من صفحته لا يبقى في قائمة الجهاز للأبد
    for url in [u for u, (_, first) in fails.items() if now - datetime.fromisoformat(first) > timedelta(days=3)]:
        del fails[url]
    for p in st.programs.items.values():  # المصدر الرسمي أولاً في الرسائل والموقع
        p.sources = official_first(p.sources, c.agg_sites)
    st.outbox.trim(RECEIPTS_CAP)
    # الجلب بالتوازي (المواقع المحجوبة بطيئة)، والمعالجة بالترتيب حتى تبقى الحالة متسقة
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(lambda j: _safe_fetch(deps, j[1], j[0].name_ar), jobs))
        agg_results = list(pool.map(lambda ch: _safe_fetch(deps, ch, "موقع تجميع"), feeds))
    for agg, res in zip(aggregators, agg_results):
        _process_aggregator(c, agg, res, resolve)
    for i, ((e, ch), res) in enumerate(zip(jobs, results), 1):
        _process_channel(c, e, ch, res)
        if checkpoint and i % checkpoint_every == 0:
            checkpoint()
    for it in st.queue.due(now):
        if c.over():
            break
        if now - it.first_seen > QUEUE_MAX_AGE:  # أسبوع بلا حكم: يُسجَّل ويُرمى بدل الإعادة للأبد
            _log(c, it.entity_id, it.url, Pending(f"انتهت مهلة الطابور بعد {it.attempts} محاولات: {it.reason_ar}"))
            st.queue.mark_done(it.id)
            continue
        _handle(c, it.entity_id, it.url, it.text, it.id, queued=it,
                resolve=resolve if it.entity_id == AGG else None)
    _safety_net(c)
    for msg_id, text in reminders(list(st.programs.items.values()), now.date(), c.names):
        legacy = msg_id.rsplit(":", 1)[0]  # معرّف قديم بلا تاريخ، أُرسل أو ينتظر قبل إضافة التاريخ
        if legacy in st.outbox.receipts or legacy in st.outbox.pending:
            continue
        p = st.programs.items[legacy.split(":", 1)[1]]
        st.outbox.enqueue(msg_id, "group", text, now)
        st.outbox.enqueue("push:" + msg_id, "push",
                          push_payload(c.name_of(p), p.entity_id, c.stars_of(p.entity_id), "تذكير",
                                       text.splitlines()[0].replace("⏰ ", "").replace("🔔 ", "")), now)
    for it in st.queue.stuck(now):
        st.outbox.enqueue(f"stuck:{it.id}", "owner",
                          f"⚠️ عالق في طابور الإعادة: {c.names.get(it.entity_id, it.entity_id)}\n"
                          f"المحاولات: {it.attempts}\nالسبب: {it.reason_ar}", now)
    _refresh_pending(c)
    _digests(c, aggregators)
    c.rep.sent = st.outbox.flush(now, deps.send)
    return c.rep
