"""حارس الخصوصية: يمنع أي بيانات شخصية من الوصول لملف منشور أو مُلتزَم.

الكلمات الممنوعة (أسماء الحسابات الوهمية، اسم المؤسس...) لا تُكتب في الكود أبداً،
بل تُقرأ من متغير البيئة RASID_FORBIDDEN (مفصولة بـ |) أو من ملف .forbidden.local.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
USER_PATH = re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".html",
                 ".js", ".css", ".csv", ".cfg", ".ini", ".sh", ""}

# ملف اختبار الحارس نفسه يحوي أمثلة مزيفة عمداً
SKIP_NAMES = {"test_privacy_guard.py"}

# دومينات عامة مسموح ظهورها (إيميلات توظيف رسمية للجهات تُضاف هنا)
DEFAULT_ALLOWED = ["example.com", "noreply.github.com", "anthropic.com"]


def load_forbidden(root: Path | None = None) -> list[str]:
    words = [w for w in os.environ.get("RASID_FORBIDDEN", "").split("|") if w.strip()]
    local = (root or Path.cwd()) / ".forbidden.local"
    if local.exists():
        words += [l.strip() for l in local.read_text(encoding="utf-8").splitlines() if l.strip()]
    return words


def scan_text(text: str, forbidden: list[str] | None = None,
              allowed_domains: list[str] | None = None) -> list[str]:
    allowed = [d.lower() for d in (allowed_domains or []) + DEFAULT_ALLOWED]
    problems: list[str] = []
    for m in EMAIL.finditer(text):
        domain = m.group(0).split("@", 1)[1].lower()
        if not any(domain == d or domain.endswith("." + d) for d in allowed):
            problems.append(f"إيميل شخصي محتمل: {m.group(0)}")
    for m in USER_PATH.finditer(text):
        problems.append(f"مسار جهاز: {m.group(0)}")
    low = text.lower()
    for w in forbidden or []:
        if w.lower() in low:
            problems.append("كلمة ممنوعة من القائمة السرية")
    return problems


def scan_paths(paths: list[Path], forbidden: list[str] | None = None,
               allowed_domains: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for p in paths:
        if p.name in SKIP_NAMES or p.suffix.lower() not in TEXT_SUFFIXES or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for problem in scan_text(text, forbidden, allowed_domains):
            out.append(f"[حارس الخصوصية][{p.name}] {problem}")
    return out


def _staged_files() -> list[Path]:
    names = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                           capture_output=True, text=True, encoding="utf-8").stdout.split()
    return [Path(n) for n in names]


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    paths = [Path(a) for a in argv] if argv else _staged_files()
    problems = scan_paths(paths, load_forbidden())
    for p in problems:
        print(p)
    if problems:
        print("[حارس الخصوصية] رُفض: أزل البيانات أعلاه ثم أعد المحاولة.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
