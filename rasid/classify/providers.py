"""مزودو الذكاء: كلهم بواجهة واحدة متوافقة، ونفس التعليمات ونفس شكل الجواب. لا يرمي استثناءً أبداً."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml

BASES = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1/",
}
ErrorKind = Literal["rate_minute", "rate_day", "busy", "too_large", "network", "bad_json", "auth"]


@dataclass(frozen=True)
class Provider:
    name: str
    base: str
    model: str
    key_env: str
    daily: int
    role: Literal["reader", "confirmer"]
    json_mode: bool = True


@dataclass
class CallResult:
    ok: bool
    data: dict | None = None
    error_kind: ErrorKind | None = None
    message: str = ""


def load_providers(path: Path) -> list[Provider]:
    return [Provider(**p) for p in yaml.safe_load(Path(path).read_text(encoding="utf-8"))]


def _classify_429(text: str) -> ErrorKind:
    t = text.lower()
    return "rate_day" if ("per day" in t or "perday" in t or "daily" in t) else "rate_minute"


def _extract_json(txt: str) -> dict | None:
    txt = re.sub(r"<(?:think|thought)>.*?</(?:think|thought)>", "", txt or "", flags=re.S).strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip()
    try:
        out = json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        try:
            out = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return out if isinstance(out, dict) else None


def call_provider(p: Provider, system: str, user: str, keys: dict[str, str],
                  client: httpx.Client | None = None) -> CallResult:
    key = keys.get(p.key_env, "")
    if not key:
        return CallResult(False, None, "auth", f"[المصنّف][{p.name}] المفتاح {p.key_env} غير موجود")
    body: dict[str, Any] = {"model": p.model, "temperature": 0,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]}
    if p.json_mode:
        body["response_format"] = {"type": "json_object"}
    c = client or httpx.Client()
    for attempt in range(2):
        try:
            r = c.post(BASES[p.base] + "chat/completions", json=body, timeout=120,
                       headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as e:
            return CallResult(False, None, "network", f"[المصنّف][{p.name}] خطأ شبكة: {type(e).__name__}")
        if r.status_code == 200:
            try:
                content = r.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                content = None
            data = _extract_json(content or "")
            if data is None:
                return CallResult(False, None, "bad_json", f"[المصنّف][{p.name}] جواب ليس JSON")
            return CallResult(True, data)
        if r.status_code == 429:
            kind = _classify_429(r.text)
            if kind == "rate_minute" and attempt == 0:
                time.sleep(min(float(r.headers.get("retry-after", 20) or 20), 60) + 1)
                continue
            if "too large" in r.text.lower():
                return CallResult(False, None, "too_large", f"[المصنّف][{p.name}] النص أطول من حده")
            return CallResult(False, None, kind, f"[المصنّف][{p.name}] انتهت الحصة ({kind})")
        if r.status_code in (401, 403):
            return CallResult(False, None, "auth", f"[المصنّف][{p.name}] المفتاح مرفوض ({r.status_code})")
        if r.status_code == 413:
            return CallResult(False, None, "too_large", f"[المصنّف][{p.name}] النص أطول من حده")
        return CallResult(False, None, "busy", f"[المصنّف][{p.name}] رمز {r.status_code}")
    return CallResult(False, None, "rate_minute", f"[المصنّف][{p.name}] حد الدقيقة")
