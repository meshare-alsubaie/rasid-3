"""الجالب: يجيب صفحة أو موجز ويحوّله لكتل نصية. لا يرمي استثناءً أبداً؛ الفشل يرجع برسالة عربية."""
from __future__ import annotations

import hashlib
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin

import httpx
import lxml.html
import trafilatura

from rasid.dates import riyadh_now
from rasid.entities import Channel

# نعرّف أنفسنا بصدق أولاً (موقع أرامكو يقبل هذا ويرفض التنكّر)، ثم هوية متصفح لمن يرفض البوتات
HONEST_UA = "RasidBot/1.0 (+https://github.com/meshare-alsubaie/rasid-3)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
IDENTITIES = [
    {"User-Agent": HONEST_UA},
    {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml",
     "Accept-Language": "ar,en;q=0.8"},
]
TIMEOUT = 30.0
_BOILERPLATE = re.compile(r"موقع حكومي مسجل|جميع الحقوق محفوظة|قد تم حظر هذا المحتوى|الرجاء إعطاء الموافقة")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def block_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.translate(_DIGITS)).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class Block:
    text: str
    link: str | None = None

    @property
    def hash(self) -> str:
        return block_hash(self.text)


@dataclass
class FetchResult:
    ok: bool
    url: str
    blocks: list[Block] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    error_ar: str | None = None
    fetched_at: datetime = field(default_factory=riyadh_now)
    via: str = "direct"


def _get(client: httpx.Client, url: str) -> tuple[httpx.Response | None, str]:
    last = ""
    for headers in IDENTITIES:
        try:
            r = client.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
        except httpx.HTTPError as e:
            last = f"تعذّر الاتصال ({type(e).__name__})"
            continue
        if r.status_code == 200:
            return r, ""
        last = f"رد الموقع برمز {r.status_code}"
        if r.status_code not in (403, 406, 429, 503):
            break
    return None, last


def _html_blocks(html: str, base: str) -> tuple[list[Block], list[tuple[str, str]]]:
    text = trafilatura.extract(html, include_comments=False, favor_recall=True) or ""
    blocks = [Block(l.strip()) for l in text.splitlines()
              if len(l.strip()) > 1 and not _BOILERPLATE.search(l)]
    links: list[tuple[str, str]] = []
    try:
        doc = lxml.html.fromstring(html)
        for a in doc.iter("a"):
            href, label = a.get("href"), " ".join(a.text_content().split())
            if href and label and not href.startswith(("#", "javascript:")):
                links.append((label, urljoin(base, href)))
    except (ValueError, lxml.etree.ParserError):
        pass
    return blocks, links


def _rss_blocks(xml: str) -> list[Block]:
    root = ET.fromstring(xml)
    out = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        get = lambda n: next((c for c in item if c.tag.split("}")[-1] == n), None)  # noqa: E731
        title, link = get("title"), get("link")
        desc = get("description")
        if desc is None:
            desc = get("summary")
        href = (link.text or link.get("href")) if link is not None else None
        text = " — ".join(t for t in [(title.text if title is not None else ""),
                                       (desc.text if desc is not None else "")] if t and t.strip())
        if text:
            out.append(Block(text.strip(), href))
    return out


def _via_relay(client: httpx.Client, url: str) -> tuple[str | None, str, str]:
    """خادم جدة: للمواقع السعودية التي ترفض خوادم أمريكا. يرجع (النص، الرابط النهائي، سبب الفشل)."""
    relay = os.environ.get("RASID_RELAY_URL")
    if not relay:
        return None, url, ""
    try:
        r = client.post(relay, json={"url": url}, timeout=90,
                        headers={"X-Relay-Token": os.environ.get("RASID_RELAY_TOKEN", "")})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return None, url, f"وخادم جدة لا يرد ({type(e).__name__})"
    if r.status_code != 200 or data.get("status") != 200:
        return None, url, f"وخادم جدة رجع {data.get('status') or r.status_code} {data.get('error', '')}".strip()
    return data.get("text", ""), data.get("url", url), ""


def fetch(channel: Channel, client: httpx.Client) -> FetchResult:
    where = f"[الجالب][{channel.url}]"
    resp, err = _get(client, channel.url)
    via = "direct"
    if resp is not None:
        body, final_url = resp.text, str(resp.url)
    else:
        body, final_url, relay_err = _via_relay(client, channel.url)
        if body is None:
            return FetchResult(False, channel.url, error_ar=f"{where} فشل: {err} {relay_err}".strip())
        via = "relay"
    try:
        if channel.kind == "rss":
            blocks, links = _rss_blocks(body), []
        else:
            blocks, links = _html_blocks(body, final_url)
    except ET.ParseError as e:
        return FetchResult(False, channel.url, error_ar=f"{where} فشل: صيغة الموجز مكسورة ({e})")
    if not blocks:
        return FetchResult(False, channel.url, error_ar=f"{where} فشل: المحتوى فارغ (ربما تغيّر تصميم الصفحة)")
    return FetchResult(True, channel.url, blocks, links, via=via)
