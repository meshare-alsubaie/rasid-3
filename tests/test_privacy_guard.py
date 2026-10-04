from pathlib import Path

from rasid.privacy_guard import scan_paths, scan_text


def test_email_is_flagged():
    assert scan_text("contact a@b.com") != []


def test_windows_user_path_is_flagged():
    assert scan_text(r"C:\Users\X\Desktop") != []


def test_forbidden_word_is_flagged():
    assert scan_text("حساب fakeuser123 للرصد", forbidden=["fakeuser123"]) != []


def test_forbidden_word_is_case_insensitive():
    assert scan_text("FAKEUSER123", forbidden=["fakeuser123"]) != []


def test_clean_arabic_passes():
    assert scan_text("أرامكو تفتح التقديم") == []


def test_public_contact_emails_of_entities_pass():
    # إيميلات الجهات الرسمية العامة ليست بيانات شخصية
    assert scan_text("careers@aramco.com", allowed_domains=["aramco.com"]) == []


def test_messages_are_arabic_and_name_the_file(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("me@gmail.com", encoding="utf-8")
    problems = scan_paths([f])
    assert len(problems) == 1
    assert "x.txt" in problems[0]
    assert "إيميل" in problems[0]


def test_binary_files_are_skipped(tmp_path: Path):
    f = tmp_path / "img.png"
    f.write_bytes(b"\x89PNG\x00\x00me@gmail.com")
    assert scan_paths([f]) == []
