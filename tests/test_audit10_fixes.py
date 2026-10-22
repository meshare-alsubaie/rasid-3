"""اختبارات إصلاح الفحص العاشر (٢٢ أكتوبر): موقع لا يصل اسمه لعنوان ليس «رابطاً غير مسموح»."""
from datetime import datetime

import httpx

from rasid.dates import RIYADH
from rasid.entities import load_entities
from relay.home_agent import build_inbox

NOW = datetime(2026, 10, 22, 19, 5, tzinfo=RIYADH)


def _no_dns(host):
    raise OSError("getaddrinfo failed")


def test_dead_dns_is_reported_as_site_down_not_forbidden():
    e = build_inbox(["https://career.dga.gov.sa/ar/"], httpx.Client(), NOW, resolve=_no_dns)["https://career.dga.gov.sa/ar/"]
    assert not e["ok"] and e["error_ar"] == "تعذّر العثور على الموقع (معطّل غالباً)"


def test_internal_address_is_still_forbidden():
    e = build_inbox(["http://router.local/admin"], httpx.Client(), NOW, resolve=lambda h: "192.168.1.1")
    assert e["http://router.local/admin"]["error_ar"] == "رابط غير مسموح"


def test_ministry_of_finance_watches_its_new_site():
    from pathlib import Path
    (mof,) = [e for e in load_entities(Path("config/entities.yaml")) if e.id == "mof"]
    assert [c.url for c in mof.channels] == ["https://www.mof.gov.sa/ar/", "https://www.mof.gov.sa/ar/employment",
                                             "https://www.mof.gov.sa/ar/news"]
