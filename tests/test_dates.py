from datetime import date, datetime, timezone

from rasid.dates import in_quiet_hours, parse_dates, riyadh_now


def _dates(text):
    return [f.date for f in parse_dates(text)]


def test_hijri_with_arabic_indic_digits():
    assert _dates("التقديم من الاثنين ١٥ جمادى الأولى ١٤٤٨") == [date(2026, 10, 26)]


def test_hijri_with_western_digits_and_variant_spelling():
    assert _dates("حتى 22 جمادى الاولى 1448هـ") == [date(2026, 11, 2)]


def test_hijri_numeric_form():
    assert _dates("يبدأ التسجيل 1447/10/11هـ") == [date(2026, 3, 30)]


def test_gregorian_month_name():
    assert _dates("الإثنين 26 أكتوبر 2026م") == [date(2026, 10, 26)]


def test_gregorian_numeric():
    assert _dates("2026/10/26") == [date(2026, 10, 26)]


def test_english_month_name():
    assert _dates("at 08:00 AM on October 26, 2026 until November 2, 2026") == [
        date(2026, 10, 26), date(2026, 11, 2)]


def test_quote_is_exact_substring():
    text = "ينتهي الساعة 3:00 مساءً يوم الإثنين 2 نوفمبر 2026م."
    found = parse_dates(text)
    assert found[0].quote in text
    assert found[0].calendar == "gregorian"


def test_aramco_golden_page_dates():
    text = open("tests/golden/raw/aramco-uip-ar.txt", encoding="utf-8").read()
    got = set(_dates(text))
    assert {date(2026, 10, 26), date(2026, 11, 2), date(2027, 1, 17), date(2027, 1, 18)} <= got


def test_invalid_date_is_ignored():
    assert _dates("31 فبراير 2026") == []


def test_quiet_hours_riyadh():
    # 23:00 UTC = 02:00 الرياض
    assert in_quiet_hours(datetime(2026, 10, 4, 23, 0, tzinfo=timezone.utc))
    # 04:00 UTC = 07:00 الرياض
    assert not in_quiet_hours(datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc))
    # 20:59 UTC = 23:59 الرياض
    assert not in_quiet_hours(datetime(2026, 10, 4, 20, 59, tzinfo=timezone.utc))


def test_riyadh_now_is_aware():
    assert riyadh_now().utcoffset().total_seconds() == 3 * 3600
