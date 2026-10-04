"""ملف الجهات: تحميله والتحقق منه. أي خطأ يُبلَّغ بالعربي مع رقم السطر، والمحرّك يكمل بآخر نسخة سليمة."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml

ChannelKind = Literal["web", "rss", "x", "linkedin", "email"]
KINDS = {"web", "rss", "x", "linkedin", "email"}
FULLTIME = {"yes", "no", "unknown"}


class EntityFileError(Exception):
    def __init__(self, line: int, message_ar: str):
        super().__init__(f"[ملف الجهات] السطر {line}: {message_ar}")
        self.line = line
        self.message_ar = message_ar


@dataclass(frozen=True)
class Channel:
    kind: ChannelKind
    url: str


@dataclass(frozen=True)
class Entity:
    id: str
    name_ar: str
    cyber: int
    hires_after: int
    channels: list[Channel]
    stars_manual: int | None = None
    fulltime_history: Literal["yes", "no", "unknown"] = "unknown"
    fulltime_evidence: str | None = None
    usual_months: list[int] = field(default_factory=list)


class _LineLoader(yaml.SafeLoader):
    """يحفظ رقم السطر لكل عنصر حتى تسمّي رسائل الخطأ مكانه."""


def _construct_mapping(loader, node, deep=False):
    m = yaml.SafeLoader.construct_mapping(loader, node, deep=deep)
    m["__line__"] = node.start_mark.line + 1
    m["__lines__"] = {k.value: k.start_mark.line + 1 for k, _ in node.value}
    return m


_LineLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _int_in(d: dict, key: str, lo: int, hi: int, required: bool) -> int | None:
    line = d["__lines__"].get(key, d["__line__"])
    if key not in d or d[key] is None:
        if required:
            raise EntityFileError(d["__line__"], f"الحقل {key} ناقص")
        return None
    v = d[key]
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise EntityFileError(line, f"قيمة {key} لازم رقم من {lo} إلى {hi}، والمكتوب: {v}")
    return v


def _url_ok(u: object) -> bool:
    if not isinstance(u, str):
        return False
    p = urlparse(u.strip())
    return p.scheme in ("http", "https", "mailto") and bool(p.netloc or p.path)


def _parse_entity(d: dict) -> Entity:
    if not isinstance(d, dict):
        raise EntityFileError(1, "كل جهة لازم تبدأ بسطر - id:")
    for key in ("id", "name_ar"):
        if not isinstance(d.get(key), str) or not d[key].strip():
            raise EntityFileError(d["__line__"], f"الحقل {key} ناقص أو فارغ")
    channels: list[Channel] = []
    for c in d.get("channels") or []:
        if not isinstance(c, dict) or c.get("kind") not in KINDS:
            line = c.get("__line__", d["__line__"]) if isinstance(c, dict) else d["__line__"]
            raise EntityFileError(line, f"نوع القناة لازم واحد من: {', '.join(sorted(KINDS))}")
        if not _url_ok(c.get("url")):
            raise EntityFileError(c["__lines__"].get("url", c["__line__"]), f"رابط غير صالح: {c.get('url')}")
        channels.append(Channel(c["kind"], c["url"].strip()))
    ft = str(d.get("fulltime_history", "unknown"))
    if ft not in FULLTIME:
        raise EntityFileError(d["__lines__"].get("fulltime_history", d["__line__"]),
                              "fulltime_history لازم yes أو no أو unknown")
    months = d.get("usual_months") or []
    if not all(isinstance(m, int) and 1 <= m <= 12 for m in months):
        raise EntityFileError(d["__lines__"].get("usual_months", d["__line__"]), "الأشهر لازم أرقام من 1 إلى 12")
    return Entity(
        id=d["id"].strip(), name_ar=d["name_ar"].strip(),
        cyber=_int_in(d, "cyber", 0, 3, True), hires_after=_int_in(d, "hires_after", 0, 3, True),
        channels=channels, stars_manual=_int_in(d, "stars_manual", 1, 5, False),
        fulltime_history=ft, fulltime_evidence=d.get("fulltime_evidence"), usual_months=list(months),
    )


def load_entities(path: Path) -> list[Entity]:
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_LineLoader)
    except yaml.MarkedYAMLError as e:
        line = (e.problem_mark.line + 1) if e.problem_mark else 1
        raise EntityFileError(line, f"صياغة الملف مكسورة ({e.problem})") from e
    if not isinstance(data, list):
        raise EntityFileError(1, "الملف لازم يكون قائمة جهات، كل جهة تبدأ بـ - id:")
    out: list[Entity] = []
    seen: set[str] = set()
    for d in data:
        e = _parse_entity(d)
        if e.id in seen:
            raise EntityFileError(d["__line__"], f"المعرّف {e.id} مكرر")
        seen.add(e.id)
        out.append(e)
    return out


def load_entities_safe(path: Path, last_good: Path) -> tuple[list[Entity], str | None]:
    """يرجع الجهات ورسالة خطأ إن وُجد. عند الخطأ يستخدم آخر نسخة سليمة ولا يتوقف."""
    try:
        entities = load_entities(path)
    except EntityFileError as err:
        return load_entities(last_good), str(err)
    shutil.copyfile(path, last_good)
    return entities, None
