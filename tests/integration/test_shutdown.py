"""Graceful shutdown on stdin EOF and SIGTERM (FR-018)."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


def start(data_dir, **extra_env):
    env = dict(os.environ)
    env.update({"WEBFETCH_DATA_DIR": str(data_dir), "WEBFETCH_ALLOW_PRIVATE_ADDRESSES": "1"})
    env.update(extra_env)
    p = subprocess.Popen(
        [sys.executable, "-m", "webfetch2000"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    p.stdin.write(json.dumps(INIT) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    assert json.loads(line)["id"] == 1, line
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    p.stdin.flush()
    return p


def call(p, id_, name, args):
    p.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": id_,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        )
        + "\n"
    )
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def wait_exit(p, timeout=15):
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        raise


def test_exits_cleanly_on_stdin_eof(data_dir):
    p = start(data_dir)
    p.stdin.close()
    assert wait_exit(p) == 0


def test_exits_cleanly_on_sigterm(data_dir):
    p = start(data_dir)
    p.send_signal(signal.SIGTERM)
    assert wait_exit(p) == 0


def test_exits_cleanly_on_sigint(data_dir):
    p = start(data_dir)
    p.send_signal(signal.SIGINT)
    assert wait_exit(p) == 0


def test_stdout_only_carries_protocol(data_dir):
    p = start(data_dir)
    p.stdin.close()
    rest = p.stdout.read()
    wait_exit(p)
    for line in rest.splitlines():
        json.loads(line)  # every stdout line is JSON-RPC, never logs
    assert p.stderr.read() is not None


@pytest.mark.browser
@pytest.mark.parametrize("how", ["eof", "sigterm"])
def test_no_orphan_browsers_after_shutdown(data_dir, site, how):
    import psutil

    p = start(data_dir)
    resp = call(p, 2, "fetch", {"url": site.url("/js")})
    assert not resp["result"].get("isError"), resp
    me = psutil.Process(p.pid)
    kids = me.children(recursive=True)
    assert kids, "expected a browser process to be running"
    if how == "eof":
        p.stdin.close()
    else:
        p.send_signal(signal.SIGTERM)
    assert wait_exit(p, 30) == 0
    time.sleep(1)
    alive = [k for k in kids if k.is_running() and k.status() != psutil.STATUS_ZOMBIE]
    assert not alive, f"orphaned processes: {alive}"
