"""Per-user storage locations follow each platform's conventions (macOS and Linux)."""

import sys
from pathlib import Path

import pytest

from webfetch2000.config import Settings, default_config_path


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS locations")
def test_macos_locations():
    assert "Library/Application Support/web-fetch-2000" in str(Settings().resolved_data_dir())
    assert "Library/Application Support/web-fetch-2000" in str(default_config_path())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux locations")
def test_linux_locations_follow_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert Settings().resolved_data_dir() == tmp_path / "data" / "web-fetch-2000"
    assert default_config_path() == tmp_path / "config" / "web-fetch-2000" / "config.toml"


def test_override_and_tilde_expansion(tmp_path):
    assert Settings(data_dir=str(tmp_path)).resolved_data_dir() == tmp_path
    assert Settings(data_dir="~/x").resolved_data_dir() == Path.home() / "x"
