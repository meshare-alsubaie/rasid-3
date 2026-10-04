from pathlib import Path

import pytest

from rasid.entities import EntityFileError, load_entities, load_entities_safe

GOOD = """\
- id: aramco
  name_ar: أرامكو السعودية
  stars_manual: 5
  cyber: 1
  hires_after: 3
  fulltime_history: "yes"
  fulltime_evidence: "لا يسمح بتسجيل مواد دراسية خلال فترة التدريب"
  usual_months: [3, 10]
  channels:
    - kind: web
      url: https://www.aramco.com/ar/careers/for-saudi-applicants/student-opportunities
    - kind: x
      url: https://x.com/aramco
- id: sdaia
  name_ar: سدايا
  cyber: 3
  hires_after: 2
  channels:
    - kind: web
      url: https://sdaia.gov.sa/
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "entities.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_good_file_loads(tmp_path):
    es = load_entities(_write(tmp_path, GOOD))
    assert [e.id for e in es] == ["aramco", "sdaia"]
    a = es[0]
    assert a.stars_manual == 5 and a.cyber == 1 and a.usual_months == [3, 10]
    assert a.channels[1].kind == "x"
    s = es[1]
    assert s.stars_manual is None and s.fulltime_history == "unknown" and s.usual_months == []


def test_duplicate_id_names_line(tmp_path):
    bad = GOOD + "- id: aramco\n  name_ar: مكرر\n  cyber: 0\n  hires_after: 0\n  channels: []\n"
    with pytest.raises(EntityFileError) as e:
        load_entities(_write(tmp_path, bad))
    assert e.value.line == 21
    assert "مكرر" in e.value.message_ar


def test_out_of_range_cyber(tmp_path):
    with pytest.raises(EntityFileError) as e:
        load_entities(_write(tmp_path, GOOD.replace("cyber: 3", "cyber: 7")))
    assert "cyber" in e.value.message_ar and e.value.line == 16


def test_bad_url(tmp_path):
    with pytest.raises(EntityFileError) as e:
        load_entities(_write(tmp_path, GOOD.replace("https://sdaia.gov.sa/", "sdaia dot gov")))
    assert "رابط" in e.value.message_ar


def test_unknown_channel_kind(tmp_path):
    with pytest.raises(EntityFileError):
        load_entities(_write(tmp_path, GOOD.replace("kind: x", "kind: tiktok")))


def test_broken_yaml_gives_arabic_message(tmp_path):
    with pytest.raises(EntityFileError) as e:
        load_entities(_write(tmp_path, GOOD.replace("  cyber: 1", "cyber: : 1")))
    assert e.value.line > 0 and e.value.message_ar


def test_safe_load_falls_back_to_last_good(tmp_path):
    path = _write(tmp_path, GOOD)
    last_good = tmp_path / "last_good.yaml"
    es, err = load_entities_safe(path, last_good)
    assert err is None and len(es) == 2 and last_good.exists()
    path.write_text(GOOD.replace("cyber: 3", "cyber: 9"), encoding="utf-8")
    es, err = load_entities_safe(path, last_good)
    assert len(es) == 2 and es[1].cyber == 3
    assert err and "السطر" in err
