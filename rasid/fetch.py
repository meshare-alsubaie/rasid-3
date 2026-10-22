"""الجالب: يجيب صفحة أو موجز ويحوّله لكتل نصية. لا يرمي استثناءً أبداً؛ الفشل يرجع برسالة عربية."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import ssl
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import certifi
import httpx
import lxml.html
import trafilatura
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

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
INBOX_MAX_AGE_H = 12
# صندوق جهاز المؤسس: نصوص صفحات سعودية جلبها جهازه (المواقع الحكومية ترفض خوادم أمريكا)
_INBOX: dict[str, dict] = {}


def set_inbox(inbox: dict[str, dict]) -> None:
    _INBOX.clear()
    _INBOX.update(inbox)


def _from_inbox(url: str, rss: bool = False) -> tuple["FetchResult | None", str]:
    e = _INBOX.get(url)
    if not e:
        return None, "ولم يصل من جهاز المؤسس بعد"
    age = (riyadh_now() - datetime.fromisoformat(e["fetched_at"])).total_seconds() / 3600
    if age > INBOX_MAX_AGE_H:
        return None, f"ونسخة جهاز المؤسس قديمة (منذ {int(age)} ساعة، الجهاز مطفي غالباً)"
    if not e.get("ok"):
        return None, f"وجهاز المؤسس فشل أيضاً: {e.get('error_ar', '')}"
    texts, hrefs, days = e.get("blocks", []), e.get("block_links") or [], e.get("block_dates") or []
    blocks = [Block(t, hrefs[i] if i < len(hrefs) else None, days[i] if i < len(days) else None)
              for i, t in enumerate(texts) if not _is_boilerplate(t)]
    links = [tuple(x) for x in e.get("links", [])]
    junk = None if rss else junk_reason(blocks, url, e.get("final_url") or url)
    if junk:
        return None, f"ونسخة جهاز المؤسس غير صالحة: {junk}"
    return FetchResult(True, url, blocks, links, via="home", final_url=e.get("final_url") or url), ""


# سطور قصيرة تتكرر في كل صفحة (شريط المواقع الحكومية، التقييم، الكوكيز، تاريخ آخر تعديل).
# حذفها يمنع «جديد» وهمي كل جولة، ويكشف الصفحة الفارغة التي لا تحوي إلا هذه السطور.
_BOILERPLATE = re.compile(
    r"موقع حكومي (?:مسجل|رسمي)|جميع الحقوق محفوظة|قد تم حظر هذا المحتوى|الرجاء إعطاء الموافقة"
    r"|كيف تتحقق|روابط المواقع ال[اإ]لكترونية الرسمية|جميع روابط المواقع الرسمية|المواقع ال[اإ]لكترونية الآمنة"
    r"|مسجل لدى هيئة الحكومة الرقمية|تحقق من أن الموقع يستخدم|government website registered"
    r"|official saudi government websites|website belongs to an official"
    r"|هل (?:كانت هذه الصفحة مفيدة|أعجبك المحتوى|استفدت من المعلومات)|أعجبهم المحتوى|قالوا نعم من|من الزوار أعجبهم"
    r"|تاريخ آخر (?:تحديث|تعديل)|last modified date|was this page useful|of users said yes"
    r"|ملفات تعريف الارتباط|\bcookies?\b|skip to main content|skip navigation links"
    r"|(?:تخطي|الانتقال|انتقل|تجاوز) إلى المحتوى|تكبير حجم الخط|عكس الألوان|الأوامر الصوتية"
    r"|^حجم النص$|تباين عالي|وضع التدرج الرمادي"
    r"|(?:تستخدم|يستخدم|use|using)\s*(?:بروتوكول\s*)?https|بروتوكول ?https|https protocol|المواقع ال[اإ]لكترونية الحكومية تستخدم|^https$|للتشفير و ?الأمان|^gov\.sa$|^how to know$|official (?:reliable )?website"
    r"|secured governments? websites|registered (?:on|with) (?:the )?digital government"
    r"|^\d{8,}$|^\d{1,3} ?%$|^[-•]?\s*(?:استطلاع الرأي|أدوات التحكم|تصويت)$|قالو(?:ا)? نعم"
    r"|سيتم قراءة النص|^(?:تحميل|loading)(?:\.{3}| page)?$|^نسخة تجريبية$|^ok cancel$"
    r"|عزيزي الزائر لضمان|^(?:جوجل كروم|فايرفوكس|سفاري|مايكروسوفت إيدج)$|نسخ رابط الصفحة|page link is copied"
    r"|لإضافة الصفحة للمفضلة|(?:إرسال|استلام|بتقديم) ملاحظاتك|بيان المشاركة ال[اإ]لكترونية|^التعليقات والاقتراحات$"
    r"|يرجى إخبارنا بالسبب|شكر\S* لملاحظاتك|^أنا$|add this page as favou?rite|^please select$"
    r"|^الرجاء الضغط على$|^log ?in$|^home page$|skiptomaincontent|^change language to:?$"
    r"|links to official saudi websites|^encryption$|^and security\.?$|^للمزيد\s+من المعلومات$",
    re.IGNORECASE)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _is_boilerplate(line: str) -> bool:
    return len(line) < 250 and bool(_BOILERPLATE.search(line))


# صفحة تردّ بنجاح لكنها لا تحمل المحتوى: رسالة خطأ، تسجيل دخول، تحويل للرئيسية، أو تطبيق يحتاج متصفحاً كاملاً
_ERROR_PAGE = re.compile(
    r"حدث خطأ ما في طلبك|الصفحة (?:المطلوبة )?غير موجودة|لم يتم العثور على الصفحة|page not found"
    r"|page (?:was moved|no longer exists|you requested)|the requested url was rejected|access denied"
    r"|تم رفض الوصول|انتهت صلاحية|لم نستطع إيجاد الصفحة|لم نتمكن من العثور على|no longer available|لم تعد متاحة|404 not found|error 404"
    r"|something went wrong|support id is|request unsuccessful|attention required|just a moment"
    r"|checking your browser|think you were a bot|are you a robot|verify you are (?:a )?human|unusual traffic",
    re.IGNORECASE)
_NEEDS_JS = re.compile(r"enable javascript|javascript (?:is )?required|requires javascript|without javascript"
                       r"|يتطلب جافا ?سكريبت|تفعيل (?:ال)?جافا ?سكريبت|\{\{\s*[\w.]+\s*\}\}", re.IGNORECASE)
_JS_PATH = re.compile(r"^/\S+\.js(?:\?\S*)?$")
_LOGIN = re.compile(r"nafath|/log-?in\b|/sign-?in\b|/sso\b|/auth/|/oauth", re.IGNORECASE)
_LOGIN_TEXT = re.compile(r"تطبيق نفاذ|رقم الهوية/|sign in to continue", re.IGNORECASE)
_NOT_FOUND_PATH = re.compile(r"/(?:errors?/)?404\b|/not-?found\b", re.IGNORECASE)
_HOME_PARTS = {"", "ar", "en", "ar-sa", "en-us", "en-gb", "en-sa", "home", "pages", "default.aspx", "home.aspx",
               "default1.aspx", "index.html", "index-rtl.html", "index.php", "web", "page"}
JUNK_TEXT_LIMIT = 800  # رسائل الخطأ قصيرة؛ الصفحة الطويلة لا تُحكم بكلمة عابرة فيها
NEAR_EMPTY = 20  # بعد حذف السطور المتكررة؛ أقصر نص سليم («لا توجد شواغر») أطول من هذا


def _is_home(url: str) -> bool:
    return all(part.lower() in _HOME_PARTS for part in urlparse(url).path.split("/"))


def junk_reason(blocks: list[Block], requested: str, final: str) -> str | None:
    """سبب عربي إذا كانت الصفحة غير صالحة للقراءة رغم ردها بنجاح، وإلا None."""
    if _LOGIN.search(final) and not _LOGIN.search(requested):
        return "تحوّلت لصفحة تسجيل دخول"
    if _NOT_FOUND_PATH.search(final) and not _NOT_FOUND_PATH.search(requested):
        return "تحوّلت لصفحة «غير موجودة»"
    if _is_home(final) and not _is_home(requested):
        return "تحوّلت للصفحة الرئيسية (الرابط القديم انتهى غالباً)"
    text = "\n".join(b.text for b in blocks)
    if len(text) < JUNK_TEXT_LIMIT:
        if _LOGIN_TEXT.search(text):
            return "الصفحة صفحة تسجيل دخول"
        if m := _ERROR_PAGE.search(text):
            return f"الصفحة رسالة خطأ: «{m.group(0)}»"
        if _NEEDS_JS.search(text) or (len(text) < 400 and any(_JS_PATH.match(b.text) for b in blocks)):
            return "الصفحة تحتاج متصفحاً كاملاً (جافاسكربت)، ونصها لا يظهر"
    if len(text) < NEAR_EMPTY:
        return "الصفحة شبه فارغة (غالباً محتواها يُحمَّل بجافاسكربت)"
    return None


def block_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.translate(_DIGITS)).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class Block:
    text: str
    link: str | None = None
    date: str | None = None  # تاريخ نشر عنصر الموجز (YYYY-MM-DD)، لا يدخل في البصمة

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
    final_url: str | None = None
    junk: bool = False  # الصفحة وصلت لكنها غير صالحة (خطأ، دخول، فارغة): جهاز المؤسس لن يفيد فيها


# بعض المواقع (نورنت، حلول من stc) ترسل شهادة وسيطة خاطئة. المتصفح يكمل السلسلة بتنزيل الوسيط من الرابط
# المكتوب في شهادة الموقع، وراصد يفعل مثله. الوسيط يُستعمل لبناء السلسلة فقط، والجذر يبقى من القائمة الموثوقة.
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
_CA_ISSUERS = bytes.fromhex("06082b0601050507300286")  # معرّف «رابط شهادة المُصدِر» ثم وسم نص الرابط
_issuer_tried: set[str] = set()


def make_client() -> httpx.Client:
    return httpx.Client(verify=SSL_CTX)


def _issuer_url(der: bytes) -> str | None:
    i = der.find(_CA_ISSUERS)
    if i < 0:
        return None
    start = i + len(_CA_ISSUERS) + 1
    n = der[start - 1]
    return der[start:start + n].decode("ascii", "replace") if n < 0x80 else None


@functools.cache
def _roots() -> Store:
    with warnings.catch_warnings():  # جذر قديم في القائمة برقم تسلسلي غير قياسي؛ تحذير لا يهمنا
        warnings.simplefilter("ignore")
        return Store(x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes()))


def _add_missing_issuer(host: str) -> bool:
    """مرة لكل موقع في الجولة: يُنزَّل الوسيط الناقص، ولا يُضاف إلا إذا صارت سلسلة الموقع معه سليمة حتى جذر
    موثوق ولنفس اسم الموقع. يرجع True إذا أُضيف فتستحق إعادة المحاولة."""
    if host in _issuer_tried:
        return False
    _issuer_tried.add(host)
    try:
        leaf = ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate((host, 443), timeout=15))
        url = _issuer_url(leaf)
        if not url:
            return False
        body = httpx.get(url, timeout=15, follow_redirects=True).content
        issuer = (x509.load_pem_x509_certificate(body) if body.startswith(b"-----BEGIN")
                  else x509.load_der_x509_certificate(body))
        PolicyBuilder().store(_roots()).build_server_verifier(x509.DNSName(host)).verify(
            x509.load_der_x509_certificate(leaf), [issuer])
        SSL_CTX.load_verify_locations(cadata=issuer.public_bytes(Encoding.PEM).decode("ascii"))
        return True
    except (OSError, ValueError, httpx.HTTPError, VerificationError):
        return False


def _get(client: httpx.Client, url: str) -> tuple[httpx.Response | None, str]:
    last = ""
    for headers in IDENTITIES:
        try:
            r = client.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
        except httpx.ConnectError as e:
            if "unable to get local issuer certificate" in str(e) and _add_missing_issuer(urlparse(url).hostname or ""):
                return _get(client, url)
            last = f"تعذّر الاتصال ({type(e).__name__})"
            continue
        except httpx.HTTPError as e:
            last = f"تعذّر الاتصال ({type(e).__name__})"
            continue
        if r.status_code == 200:
            return r, ""
        last = f"رد الموقع برمز {r.status_code}"
        if r.status_code not in (202, 403, 406, 429, 503):
            break
    return None, last


def _html_blocks(html: str, base: str) -> tuple[list[Block], list[tuple[str, str]]]:
    if html.lstrip()[:1] in ("[", "{"):  # بعض المواقع ترد ببيانات خام بدل صفحة (أخبار الإسكان)
        try:
            return _json_blocks(json.loads(html)), []
        except ValueError:
            pass
    text = trafilatura.extract(html, include_comments=False, favor_recall=True) or ""
    blocks = [Block(l.strip()) for l in text.splitlines()
              if len(l.strip()) > 1 and not _is_boilerplate(l.strip())]
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


_JSON_TEXT_KEYS = {"title", "name", "content", "description", "summary", "body", "text", "details"}


def _plain(x: str) -> str:
    """نص بلا وسوم HTML (أوصاف الموجزات وحقول الردود الخام تحمل وسوماً أحياناً)."""
    if "<" not in x:
        return x
    try:
        return lxml.html.fromstring(x).text_content()
    except (ValueError, lxml.etree.ParserError):
        return x


def _json_blocks(data) -> list[Block]:
    """نصوص الحقول المقروءة فقط من رد خام، بلا وسوم HTML داخلها."""
    out: list[Block] = []

    def walk(x, key=None):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, str(k).lower())
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str) and key in _JSON_TEXT_KEYS and x.strip():
            for line in _plain(x).splitlines():
                if len(line.strip()) > 1 and not _is_boilerplate(line.strip()):
                    out.append(Block(" ".join(line.split())))

    walk(data)
    return out


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
        parts = [" ".join(_plain(n.text).split()) for n in (title, desc) if n is not None and n.text]
        text = " — ".join(t for t in parts if t)
        when = next((n.text for n in map(get, ("pubDate", "published", "updated", "date"))
                     if n is not None and n.text), None)
        if text:
            out.append(Block(text.strip(), href, _iso_day(when)))
    return out


def _iso_day(s: str | None) -> str | None:
    """تاريخ النشر في الموجز (RFC 822 أو ISO) إلى YYYY-MM-DD، أو None إذا لم يُفهم."""
    if not s:
        return None
    try:
        return parsedate_to_datetime(s.strip()).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


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
    """صفحة غير صالحة من السحابة (خطأ، حجب مقنّع) تُجرَّب نسختها من جهاز المؤسس قبل إعلان الفشل."""
    where = f"[الجالب][{channel.url}]"
    resp, err = _get(client, channel.url)
    via, junk = "direct", None
    if resp is not None:
        body, final_url = resp.text, str(resp.url)
        parsed = _parse(channel, body, final_url)
        if isinstance(parsed, FetchResult):
            return parsed
        junk = parsed
        err = f"{junk}"
    home, home_err = _from_inbox(channel.url, channel.kind == "rss")
    if home is not None:
        return home
    if junk is None:
        body, final_url, relay_err = _via_relay(client, channel.url)
        if body is not None:
            parsed = _parse(channel, body, final_url, via="relay")
            if isinstance(parsed, FetchResult):
                return parsed
            junk, relay_err = parsed, ""
            err = junk
    else:
        relay_err = ""
    return FetchResult(False, channel.url, error_ar=f"{where} فشل: {err} {home_err} {relay_err}".strip(),
                       junk=junk is not None)


def _parse(channel: Channel, body: str, final_url: str, via: str = "direct") -> "FetchResult | str":
    """نتيجة سليمة، أو سبب عربي لعدم صلاحية الصفحة."""
    try:
        if channel.kind == "rss":
            blocks, links = _rss_blocks(body), []
        else:
            blocks, links = _html_blocks(body, final_url)
    except ET.ParseError as e:
        return f"صيغة الموجز مكسورة ({e})"
    if not blocks:
        return "المحتوى فارغ (ربما تغيّر تصميم الصفحة)"
    if channel.kind != "rss" and (why := junk_reason(blocks, channel.url, final_url)):
        return why
    return FetchResult(True, channel.url, blocks, links, via=via, final_url=final_url)
