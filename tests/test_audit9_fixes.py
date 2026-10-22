"""اختبارات إصلاح الفحص التاسع (٢٢ أكتوبر): ساعة الموقع لا تجعل الصفحة «جديدة» في كل جلب."""
from rasid.diff import new_blocks
from rasid.fetch import FetchResult, _is_boilerplate, block_hash


def test_site_clock_and_last_modified_lines_are_boilerplate():
    for line in ("05:05 م", "٠٦:٢١ م", "10:42:07", "22-أكتوبر-2026", "آخر تعديل 16-سبتمبر-2026",
                 "أخر تحديث بتاريخ 27 Sep 2026"):
        assert _is_boilerplate(line), line


def test_dated_content_is_kept():
    for line in ("04 أكتوبر 2026", "يبدأ التسجيل الساعة 08:00 صباحاً يوم الإثنين", "آخر تحديث: تمديد التسجيل حتى 2026-11-05",
                 "تاريخ النشر : 11 October 2026", "برنامج التدريب العملي"):
        assert not _is_boilerplate(line), line


def test_page_with_a_ticking_clock_has_nothing_new():
    """نسختان من صفحة الهيئة بينهما ساعتان: المحتوى نفسه، والساعة وحدها تغيّرت."""
    from rasid.fetch import _html_blocks
    page = "<html><body><p>{t}</p><p>{d}</p><p>برنامج التدريب العملي للطلاب</p></body></html>"
    first, _ = _html_blocks(page.format(t="05:05 م", d="22-أكتوبر-2026"), "https://www.hrc.gov.sa/website/careers")
    later, _ = _html_blocks(page.format(t="07:05 م", d="23-أكتوبر-2026"), "https://www.hrc.gov.sa/website/careers")
    seen = {b.hash for b in first}
    assert not new_blocks(seen, FetchResult(True, "u", later))
    assert block_hash("برنامج التدريب العملي للطلاب") in seen
