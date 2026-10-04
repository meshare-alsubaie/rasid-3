"""اختبار جدوى: يمرّر الأمثلة الذهبية على كل نموذج مجاني ويطبع الدقة. لا يطبع المفاتيح أبداً.

الاستخدام: uv run python scripts/probe_llm.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rasid.dates import parse_dates  # noqa: E402

CANDIDATES = [
    ("gemini", "gemini-3.8-flash"), ("gemini", "gemini-3.5-flash"), ("gemini", "gemini-3-flash-preview"),
    ("gemini", "gemini-2.5-flash"), ("gemini", "gemini-3.5-flash-lite"),
    ("groq", "openai/gpt-oss-120b"), ("groq", "qwen/qwen3.8-27b"), ("groq", "allam-2-7b"),
]
BASE = {"gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "groq": "https://api.groq.com/openai/v1/"}
KEYVAR = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}


def load_env() -> dict[str, str]:
    lines = (ROOT / "secrets.local.env").read_text(encoding="utf-8").splitlines()
    return {k: v.strip() for k, v in (l.split("=", 1) for l in lines if "=" in l and not l.startswith("#"))}


def ask(provider: str, model: str, key: str, system: str, user: str) -> tuple[dict | None, str, dict]:
    try:
        r = _post(provider, model, key, system, user)
        if r.status_code == 429:  # حد الدقيقة: انتظر المدة التي يطلبها المزود ثم أعد مرة واحدة
            time.sleep(min(float(r.headers.get("retry-after", 30)), 90) + 1)
            r = _post(provider, model, key, system, user)
    except httpx.HTTPError as e:
        return None, f"خطأ شبكة: {type(e).__name__}", {}
    limits = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()}
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text.strip().splitlines()[0][:80] if r.text else ''}", limits
    txt = r.json()["choices"][0]["message"]["content"] or ""
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
    try:
        return json.loads(txt), "", limits
    except json.JSONDecodeError:
        return None, "JSON غير صالح: " + txt[:120], limits


def _post(provider: str, model: str, key: str, system: str, user: str) -> httpx.Response:
    return httpx.post(BASE[provider] + "chat/completions", timeout=120,
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})


def _norm(s: str) -> str:
    # الحروف والأرقام فقط: يتجاهل الترقيم والنقاط والتشكيل، ويبقى يكشف أي كلمة مختلقة
    s = re.sub(r"[ً-ْـ]", "", s)
    return re.sub(r"[^\w]+", " ", s).strip()


def check(out: dict, exp: dict, text: str) -> list[str]:
    errs: list[str] = []
    if out.get("kind") != exp["kind"]:
        errs.append(f"النوع {out.get('kind')} والمتوقع {exp['kind']}")
    nt = _norm(text)
    for name, f in out.items():
        if isinstance(f, dict) and f.get("quote") and _norm(f["quote"]) not in nt:
            errs.append(f"اقتباس مختلق في {name}")
    for name in ("opens", "closes", "training_starts"):
        if name in exp:
            f = out.get(name) or {}
            got = str(f.get("value"))
            if got != str(exp[name]):
                # التحقق المستقل: هل الاقتباس فيه هذا التاريخ فعلاً؟
                ds = [str(d.date) for d in parse_dates(f.get("quote") or "")]
                if str(exp[name]) not in ds:
                    errs.append(f"{name}={got} والمتوقع {exp[name]}")
    for name in ("stipend", "housing", "medical", "transport", "no_courses_allowed"):
        if name in exp and (out.get(name) or {}).get("value") != exp[name]:
            errs.append(f"{name} خطأ")
    return errs


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    env = load_env()
    system = (ROOT / "rasid/classify/prompt.md").read_text(encoding="utf-8")
    cases = []
    for p in sorted((ROOT / "tests/golden/cases").glob("*.yaml")):
        c = yaml.safe_load(p.read_text(encoding="utf-8"))
        c["text"] = (p.parent / c["text_file"]).read_text(encoding="utf-8")
        cases.append(c)
    only = sys.argv[1:]
    for provider, model in CANDIDATES:
        if only and model not in only:
            continue
        ok = 0
        for c in cases:
            user = f"الجهة: {c['entity']}\nالرابط: {c['source_url']}\n\nالنص:\n{c['text']}"
            t0 = time.time()
            out, err, limits = ask(provider, model, env[KEYVAR[provider]], system, user)
            dt = time.time() - t0
            errs = [err] if err else check(out, c["expected"], user)
            ok += not errs
            print(f"{model:28} {c['id']:22} {'✅' if not errs else '❌'} {dt:5.1f}s {'; '.join(errs)[:220]}")
            if limits:
                print("   حدود:", {k: v for k, v in limits.items() if "remaining" in k or "limit-requests" in k})
            time.sleep(2)
        print(f"== {model}: {ok}/{len(cases)}")


if __name__ == "__main__":
    main()
