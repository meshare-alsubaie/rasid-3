import httpx
import respx

from rasid.diff import new_blocks
from rasid.entities import Channel
from rasid.fetch import HONEST_UA, fetch

PAGE = """<html><head><title>x</title></head><body>
<header><div class="gov-banner">موقع حكومي مسجل لدى هيئة الحكومة الرقمية</div><nav>الرئيسية | عن الهيئة</nav></header>
<main><article>
<h1>برنامج التدريب التعاوني</h1>
<p>تعلن الهيئة عن فتح باب التسجيل في برنامج التدريب التعاوني لطلاب الجامعات للفصل الدراسي الثاني.</p>
<p>يبدأ التسجيل يوم الأحد 5 يوليو 2026 ويستمر حتى 12 يوليو 2026 عبر البوابة الإلكترونية للهيئة.</p>
<p><a href="https://apply.example.com/coop">قدّم الآن</a></p>
</article></main>
<footer>جميع الحقوق محفوظة</footer></body></html>"""

URL = "https://agency.example.com/coop"
WEB = Channel("web", URL)


@respx.mock
def test_extracts_main_text_without_banner():
    respx.get(URL).mock(return_value=httpx.Response(200, html=PAGE))
    r = fetch(WEB, httpx.Client())
    assert r.ok
    text = "\n".join(b.text for b in r.blocks)
    assert "التدريب التعاوني" in text and "5 يوليو 2026" in text
    assert "موقع حكومي" not in text
    assert ("قدّم الآن", "https://apply.example.com/coop") in r.links


@respx.mock
def test_honest_identity_first():
    route = respx.get(URL).mock(return_value=httpx.Response(200, html=PAGE))
    fetch(WEB, httpx.Client())
    assert route.calls[0].request.headers["user-agent"] == HONEST_UA


@respx.mock
def test_falls_back_to_browser_identity():
    route = respx.get(URL).mock(side_effect=[httpx.ConnectError("reset"), httpx.Response(200, html=PAGE)])
    r = fetch(WEB, httpx.Client())
    assert r.ok and route.call_count == 2
    assert "Mozilla" in route.calls[1].request.headers["user-agent"]


@respx.mock
def test_failure_is_reported_in_arabic_not_raised():
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    r = fetch(WEB, httpx.Client())
    assert not r.ok and r.blocks == []
    assert "[الجالب]" in r.error_ar and URL in r.error_ar


@respx.mock
def test_http_error_status():
    respx.get(URL).mock(return_value=httpx.Response(503))
    r = fetch(WEB, httpx.Client())
    assert not r.ok and "503" in r.error_ar


@respx.mock
def test_empty_page_is_a_failure_not_silence():
    respx.get(URL).mock(return_value=httpx.Response(200, html="<html><body></body></html>"))
    r = fetch(WEB, httpx.Client())
    assert not r.ok and "فارغ" in r.error_ar


@respx.mock
def test_no_personal_data_in_request():
    route = respx.get(URL).mock(return_value=httpx.Response(200, html=PAGE))
    fetch(WEB, httpx.Client())
    headers = " ".join(f"{k}:{v}" for k, v in route.calls[0].request.headers.items())
    assert "@" not in headers


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>فتح التسجيل في التدريب التعاوني</title><link>https://a.example.com/1</link><description>للطلاب</description></item>
<item><title>خبر آخر</title><link>https://a.example.com/2</link></item>
</channel></rss>"""


@respx.mock
def test_rss_items_become_blocks():
    respx.get("https://a.example.com/feed").mock(return_value=httpx.Response(200, text=RSS))
    r = fetch(Channel("rss", "https://a.example.com/feed"), httpx.Client())
    assert r.ok and len(r.blocks) == 2
    assert r.blocks[0].link == "https://a.example.com/1"
    assert "للطلاب" in r.blocks[0].text  # الوصف لا يضيع


@respx.mock
def test_new_blocks_only_returns_unseen():
    respx.get(URL).mock(return_value=httpx.Response(200, html=PAGE))
    r = fetch(WEB, httpx.Client())
    seen = {b.hash for b in r.blocks[:-1]}
    assert new_blocks(seen, r) == [r.blocks[-1]]


def test_hash_ignores_whitespace_and_digit_style():
    from rasid.fetch import block_hash
    assert block_hash("يبدأ  التسجيل ٥ يوليو") == block_hash("يبدأ التسجيل 5 يوليو")
