import pytest

from webfetch2000.config import ConfigError, Settings, load_settings


def test_defaults():
    loaded = load_settings(env={}, config_path=None)
    s = loaded.settings
    assert s.timeout_s == 30
    assert s.max_response_bytes == 10_000_000
    assert s.browser_headless is True and s.stealth_headless is True
    assert s.enabled_strategies == ("http", "browser", "stealth")
    assert s.domain_concurrency == 2 and s.domain_rate_per_s == 2 and s.domain_burst == 4
    assert s.negotiate_markdown is True
    assert s.min_content_chars == 200
    assert s.allow_private_addresses is False
    assert set(loaded.sources.values()) == {"default"}


def test_file_overrides_defaults(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('cache_ttl_s = 7200\nstealth_headless = false\nenabled_strategies = ["http"]\n')
    loaded = load_settings(env={}, config_path=cfg)
    assert loaded.settings.cache_ttl_s == 7200
    assert loaded.settings.stealth_headless is False
    assert loaded.settings.enabled_strategies == ("http",)
    assert loaded.sources["cache_ttl_s"] == "file"
    assert loaded.sources["timeout_s"] == "default"
    assert loaded.config_file == cfg


def test_env_overrides_file(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("cache_ttl_s = 7200\n")
    loaded = load_settings(env={"WEBFETCH_CACHE_TTL_S": "60"}, config_path=cfg)
    assert loaded.settings.cache_ttl_s == 60
    assert loaded.sources["cache_ttl_s"] == "env"


def test_env_parsing_types():
    env = {
        "WEBFETCH_BROWSER_HEADLESS": "false",
        "WEBFETCH_ENABLED_STRATEGIES": "http, browser",
        "WEBFETCH_DOMAIN_RATE_PER_S": "0.5",
        "WEBFETCH_EXTRA_HEADERS": '{"X-Test": "1"}',
        "WEBFETCH_ALLOW_PRIVATE_ADDRESSES": "1",
    }
    s = load_settings(env=env, config_path=None).settings
    assert s.browser_headless is False
    assert s.enabled_strategies == ("http", "browser")
    assert s.domain_rate_per_s == 0.5
    assert s.extra_headers == {"X-Test": "1"}
    assert s.allow_private_addresses is True


def test_config_path_from_env(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("timeout_s = 5\n")
    loaded = load_settings(env={"WEBFETCH_CONFIG": str(cfg)})
    assert loaded.settings.timeout_s == 5


@pytest.mark.parametrize(
    "env",
    [
        {"WEBFETCH_CACHE_TTL_S": "abc"},
        {"WEBFETCH_TIMEOUT_S": "-1"},
        {"WEBFETCH_ENABLED_STRATEGIES": "http,teleport"},
        {"WEBFETCH_BROWSER_HEADLESS": "maybe"},
        {"WEBFETCH_EXTRA_HEADERS": "not json"},
    ],
)
def test_invalid_env_raises(env):
    with pytest.raises(ConfigError) as exc:
        load_settings(env=env, config_path=None)
    assert "WEBFETCH_" in str(exc.value) or "invalid" in str(exc.value).lower()


def test_invalid_file_raises(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("not_a_setting = 1\n")
    with pytest.raises(ConfigError):
        load_settings(env={}, config_path=cfg)
    cfg.write_text("this is = not toml [")
    with pytest.raises(ConfigError):
        load_settings(env={}, config_path=cfg)


def test_unknown_env_vars_ignored():
    s = load_settings(env={"WEBFETCH_NOT_A_SETTING": "1", "OTHER": "x"}, config_path=None)
    assert s.settings.timeout_s == 30


def test_with_overrides_per_call():
    base = Settings()
    s = base.with_overrides(timeout_s=5, negotiate_markdown=False)
    assert s.timeout_s == 5 and s.negotiate_markdown is False
    assert base.timeout_s == 30
    with pytest.raises(ValueError):
        base.with_overrides(timeout_s=0)


def test_data_dir_default_and_override(tmp_path):
    default = load_settings(env={}, config_path=None).settings
    assert default.resolved_data_dir().name  # platform dir
    s = load_settings(env={"WEBFETCH_DATA_DIR": str(tmp_path)}, config_path=None).settings
    assert s.resolved_data_dir() == tmp_path
