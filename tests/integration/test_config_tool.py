"""Settings layering end to end, and fail-fast on invalid configuration (FR-023)."""

import os
import subprocess
import sys

import pytest

from tests.helpers import mcp_client
from webfetch2000.config import load_settings


def run_server(env_extra, timeout=15):
    env = {k: v for k, v in os.environ.items() if not k.startswith("WEBFETCH_")}
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "webfetch2000"],
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    "env,needle",
    [
        ({"WEBFETCH_CACHE_TTL_S": "abc"}, "WEBFETCH_CACHE_TTL_S"),
        ({"WEBFETCH_ENABLED_STRATEGIES": "http,teleport"}, "WEBFETCH_ENABLED_STRATEGIES"),
        ({"WEBFETCH_TIMEOUT_S": "0"}, "WEBFETCH_TIMEOUT_S"),
    ],
)
def test_invalid_settings_stop_startup_with_a_clear_message(env, needle):
    p = run_server(env)
    assert p.returncode == 2
    assert needle in p.stderr and p.stdout == ""


def test_missing_explicit_config_file_fails(tmp_path):
    p = run_server({"WEBFETCH_CONFIG": str(tmp_path / "nope.toml")})
    assert p.returncode == 2 and "config file not found" in p.stderr


async def test_layers_end_to_end(tmp_path, data_dir):
    cfg = tmp_path / "c.toml"
    cfg.write_text('cache_ttl_s = 7200\nstealth_headless = false\nuser_agent = "from-file"\n')
    loaded = load_settings(
        env={"WEBFETCH_CACHE_TTL_S": "60", "WEBFETCH_DATA_DIR": str(data_dir)}, config_path=cfg
    )
    async with mcp_client(loaded.settings, loaded=loaded) as client:
        s = (await client.call_tool("config", {})).structuredContent["settings"]
    assert s["cache_ttl_s"] == {"value": 60, "source": "env"}  # env beats file
    assert s["stealth_headless"] == {"value": False, "source": "file"}  # file beats default
    assert s["user_agent"]["source"] == "file"
    assert s["timeout_s"]["source"] == "default"


async def test_per_call_arguments_beat_settings(tmp_path, data_dir, site):
    async with mcp_client(data_dir=str(data_dir), timeout_s=30) as client:
        res = await client.call_tool(
            "fetch",
            {"url": site.url("/slow?s=3"), "timeout_s": 1, "strategy": "http", "fallback": False},
        )
    assert res.isError  # the per-call 1s timeout won over the 30s setting
