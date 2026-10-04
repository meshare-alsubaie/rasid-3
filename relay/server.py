"""خادم جدة: يجلب صفحة سعودية نيابة عن المحرّك (المواقع الحكومية ترفض خوادم أمريكا).

الحماية:
- رمز سري في الترويسة X-Relay-Token وإلا 403.
- http/https فقط، ويُرفض أي عنوان داخلي (مثل 169.254.169.254) في الطلب وفي كل تحويل.
التشغيل: RELAY_TOKEN=... python -m relay.server  (يستمع على 127.0.0.1:8080 خلف Caddy للتشفير)
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5
UAS = ["RasidBot/1.0 (+https://github.com/meshare-alsubaie/rasid-3)",
       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"]


def _public(url: str, resolve: Callable[[str], str]) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        ip = ipaddress.ip_address(resolve(p.hostname))
    except (OSError, ValueError):
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)


def check_request(body: dict, token: str, expected: str,
                  resolve: Callable[[str], str] = socket.gethostbyname) -> tuple[int, str]:
    if not expected or not hmac.compare_digest(token or "", expected):
        return 403, "رمز غير صحيح"
    url = str(body.get("url", ""))
    if not _public(url, resolve):
        return 400, "رابط غير مسموح"
    return 200, url


def relay_fetch(url: str, client: httpx.Client) -> dict:
    last: dict = {"status": 0, "url": url, "text": "", "error": "لم يُجرَّب"}
    for ua in UAS:
        current = url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                r = client.get(current, headers={"User-Agent": ua, "Accept-Language": "ar,en;q=0.8"},
                               timeout=30, follow_redirects=False)
                if r.is_redirect and "location" in r.headers:
                    nxt = urljoin(current, r.headers["location"])
                    if not _public(nxt, socket.gethostbyname):
                        return {"status": 400, "url": nxt, "text": "", "error": "تحويل لعنوان داخلي"}
                    current = nxt
                    continue
                break
            last = {"status": r.status_code, "url": current, "text": r.text[:MAX_BYTES]}
            if r.status_code == 200:
                return last
        except httpx.HTTPError as e:
            last = {"status": 0, "url": current, "text": "", "error": type(e).__name__}
    return last


class Handler(BaseHTTPRequestHandler):
    client = httpx.Client()

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        self._send(200 if self.path == "/health" else 404, {"ok": self.path == "/health"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/fetch":
            return self._send(404, {"error": "غير موجود"})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 10_000)))
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "طلب غير صالح"})
        code, url_or_msg = check_request(body, self.headers.get("X-Relay-Token", ""), os.environ.get("RELAY_TOKEN", ""))
        if code != 200:
            return self._send(code, {"error": url_or_msg})
        self._send(200, relay_fetch(url_or_msg, self.client))

    def log_message(self, fmt: str, *args) -> None:  # سجل مختصر بلا روابط كاملة
        pass


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("RELAY_PORT", "8080"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
