"""Smoke-test a built image: start it over stdio and fetch pages from a local test site.

Usage: uv run python scripts/smoke_container.py IMAGE [--browsers]
  --browsers  also fetch a JavaScript-rendered page (needs the `full` image)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BODY = (
    "<html><body><article><h1>Container Smoke</h1><p>"
    + "The quick brown fox jumps over the lazy dog. " * 12
    + "</p></article></body></html>"
)
JS = (
    "<html><body><div id=a></div><script>document.getElementById('a').innerHTML="
    "'<article><h1>Rendered In Container</h1><p>' + 'lorem ipsum dolor sit amet '.repeat(20)"
    " + '</p></article>';</script></body></html>"
)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        body = (JS if self.path == "/js" else BODY).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def rpc(p, id_, method, params):
    p.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params}) + "\n"
    )
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--browsers", action="store_true")
    args = ap.parse_args()

    server = ThreadingHTTPServer(("0.0.0.0", 0), H)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    linux = sys.platform.startswith("linux")
    host = "127.0.0.1" if linux else "host.docker.internal"
    cmd = [
        "docker",
        "run",
        "-i",
        "--rm",
        "--shm-size=1g",
        "-e",
        "WEBFETCH_ALLOW_PRIVATE_ADDRESSES=1",
    ]
    cmd += ["--network", "host"] if linux else []
    cmd += [args.image]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        init = rpc(
            p,
            1,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        )
        assert init["result"]["serverInfo"]["name"] == "web-fetch-2000", init
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()

        res = rpc(
            p, 2, "tools/call", {"name": "fetch", "arguments": {"url": f"http://{host}:{port}/"}}
        )
        out = res["result"]
        assert not out.get("isError"), out
        assert out["structuredContent"]["strategy_used"] == "http", out
        assert "Container Smoke" in out["structuredContent"]["content"]
        print("OK http fetch")

        st = rpc(p, 3, "tools/call", {"name": "strategies", "arguments": {}})["result"][
            "structuredContent"
        ]
        print("strategies:", {s["name"]: s["available"] for s in st["strategies"]})
        assert st["store"]["available"], st

        if args.browsers:
            res = rpc(
                p,
                4,
                "tools/call",
                {"name": "fetch", "arguments": {"url": f"http://{host}:{port}/js"}},
            )
            out = res["result"]
            assert not out.get("isError"), out
            sc = out["structuredContent"]
            assert sc["strategy_used"] in ("browser", "stealth"), sc
            assert "Rendered In Container" in sc["content"], sc
            print("OK browser fetch via", sc["strategy_used"])
            res = rpc(
                p,
                5,
                "tools/call",
                {
                    "name": "fetch",
                    "arguments": {
                        "url": f"http://{host}:{port}/js",
                        "strategy": "stealth",
                        "fallback": False,
                        "cache": "bypass",
                    },
                },
            )
            assert not res["result"].get("isError"), res["result"]["content"]
            sc = res["result"]["structuredContent"]
            assert sc["strategy_used"] == "stealth", res
            print("OK stealth fetch")
        return 0
    finally:
        p.stdin.close()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
