"""Shared fixtures: a local HTTP test site that simulates the pages the fetcher must handle."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

LOREM = (
    "Web fetching is the process of retrieving documents from servers. "
    "A robust fetcher tries cheap methods first and escalates only when needed. "
) * 6

STATIC_HTML = f"""<!doctype html><html><head><title>Static page</title></head>
<body><nav>menu</nav><article><h1>Static Heading</h1><p>{LOREM}</p>
<p>Second paragraph with a <a href="/other">link</a>.</p></article></body></html>"""

JS_HTML = """<!doctype html><html><head><title>JS page</title></head>
<body><div id="app"></div>
<script>
document.getElementById('app').innerHTML =
  '<article><h1>Rendered Heading</h1><p>' + %s + '</p></article>';
</script></body></html>""" % json.dumps(LOREM)

CHALLENGE_HTML = """<!doctype html><html><head><title>Just a moment...</title></head>
<body><h1>Just a moment...</h1><p>Enable JavaScript and cookies to continue</p>
<div class="cf-chl-widget"></div></body></html>"""

MARKDOWN_BODY = "# Origin Markdown\n\n" + LOREM + "\n"


def make_pdf(text: str) -> bytes:
    """Build a tiny valid single-page PDF containing ``text``."""
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        None,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objs[3] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201e5c1ab6f0000000049454e44ae426082"
)


@dataclass
class Site:
    base: str
    hits: list[dict[str, Any]] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    inflight: int = 0
    peak: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def url(self, path: str = "/") -> str:
        return self.base + path

    def reset(self) -> None:
        self.hits.clear()
        self.counters.clear()
        self.inflight = 0
        self.peak = 0

    def count(self, path: str) -> int:
        return sum(1 for h in self.hits if h["path"] == path)


def _make_handler(site_ref: list[Site]):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # silence
            pass

        def _send(
            self,
            status: int,
            body: bytes = b"",
            ctype: str = "text/html; charset=utf-8",
            headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_GET(self) -> None:  # noqa: N802
            site = site_ref[0]
            u = urlparse(self.path)
            q = parse_qs(u.query)
            path = u.path
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            site.hits.append({"path": path, "query": u.query, "headers": hdrs, "t": time.time()})
            n = site.counters.get(path, 0) + 1
            site.counters[path] = n

            if path == "/static":
                return self._send(200, STATIC_HTML.encode())
            if path in ("/", "/other"):
                return self._send(200, STATIC_HTML.encode())
            if path == "/js":
                return self._send(200, JS_HTML.encode())
            if path == "/challenge":
                return self._send(200, CHALLENGE_HTML.encode())
            if path == "/forbidden":
                return self._send(403, b"<html><body>Forbidden</body></html>")
            if path == "/firefox-only":
                if "Firefox" in hdrs.get("user-agent", "") and "Headless" not in hdrs.get(
                    "user-agent", ""
                ):
                    return self._send(200, STATIC_HTML.encode())
                return self._send(403, CHALLENGE_HTML.encode())
            if path == "/ratelimited":
                fail = int(q.get("fail", ["1"])[0])
                after = q.get("retry_after", ["1"])[0]
                if n <= fail:
                    return self._send(429, b"slow down", headers={"Retry-After": after})
                return self._send(200, STATIC_HTML.encode())
            if path == "/always429":
                return self._send(429, b"slow down", headers={"Retry-After": "1"})
            if path == "/unavailable":
                return self._send(503, b"down", headers={"Retry-After": "1"})
            if path == "/slow":
                time.sleep(float(q.get("s", ["2"])[0]))
                return self._send(200, STATIC_HTML.encode())
            if path == "/redirect":
                return self._send(302, b"", headers={"Location": "/static"})
            if path == "/redirect-to":
                return self._send(302, b"", headers={"Location": q["to"][0]})
            if path == "/redirect-loop":
                return self._send(302, b"", headers={"Location": "/redirect-loop"})
            if path == "/markdown":
                if "text/markdown" in hdrs.get("accept", ""):
                    return self._send(
                        200,
                        MARKDOWN_BODY.encode(),
                        "text/markdown; charset=utf-8",
                        {
                            "x-markdown-tokens": "42",
                            "Content-Signal": "ai-train=no, search=yes, ai-input=yes",
                            "Vary": "accept",
                        },
                    )
                return self._send(200, STATIC_HTML.encode(), headers={"Vary": "accept"})
            if path == "/pdf":
                return self._send(200, make_pdf("Hello PDF world"), "application/pdf")
            if path == "/json":
                return self._send(200, b'{"a": 1, "b": [1, 2, 3]}', "application/json")
            if path == "/text":
                return self._send(200, b"plain text body", "text/plain; charset=utf-8")
            if path == "/csv":
                return self._send(200, b"a,b\n1,2\n", "text/csv")
            if path == "/image":
                return self._send(200, PNG_1PX, "image/png")
            if path == "/large":
                size = int(q.get("bytes", ["2000000"])[0])
                body = ("<html><body><p>" + "x" * size + "</p></body></html>").encode()
                return self._send(200, body)
            if path == "/etag":
                if hdrs.get("if-none-match") == '"v1"':
                    return self._send(304, b"", headers={"ETag": '"v1"'})
                return self._send(200, STATIC_HTML.encode(), headers={"ETag": '"v1"'})
            if path == "/no-store":
                return self._send(200, STATIC_HTML.encode(), headers={"Cache-Control": "no-store"})
            if path == "/max-age":
                return self._send(200, STATIC_HTML.encode(), headers={"Cache-Control": "max-age=1"})
            if path == "/count":
                body = f"<html><body><p>{LOREM} hit {n}</p></body></html>".encode()
                return self._send(200, body)
            if path == "/track":
                with site._lock:
                    site.inflight += 1
                    site.peak = max(site.peak, site.inflight)
                try:
                    time.sleep(float(q.get("s", ["0.05"])[0]))
                finally:
                    with site._lock:
                        site.inflight -= 1
                return self._send(200, STATIC_HTML.encode())
            if path == "/with-image":
                html = (
                    f'<html><body><article><p>{LOREM}</p><img src="/image"></article></body></html>'
                )
                return self._send(200, html.encode())
            if path == "/empty":
                return self._send(200, b"<html><body></body></html>")
            return self._send(404, b"<html><body>not found</body></html>")

    return Handler


@pytest.fixture(scope="session")
def _site_server() -> Iterator[Site]:
    site_ref: list[Site] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(site_ref))
    server.daemon_threads = True
    port = server.server_address[1]
    site = Site(base=f"http://127.0.0.1:{port}")
    site_ref.append(site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield site
    server.shutdown()
    server.server_close()


@pytest.fixture
def site(_site_server: Site) -> Site:
    _site_server.reset()
    return _site_server


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d
