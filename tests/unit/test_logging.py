import json

from webfetch2000.logging import configure, get_logger, redact_url


def test_redacts_query_fragment_userinfo():
    assert redact_url("https://u:p@example.com/a/b?token=secret#frag") == "https://example.com/a/b"
    assert redact_url("http://example.com") == "http://example.com"
    assert redact_url("http://example.com:8080/x?y=1") == "http://example.com:8080/x"


def test_redact_handles_garbage():
    assert "secret" not in redact_url("not a url?secret=1")
    assert redact_url("") == ""


def test_logs_go_to_stderr_only(capsys):
    configure("INFO")
    log = get_logger("test")
    log.info(
        "fetch", extra={"url": redact_url("https://example.com/p?k=secret"), "strategy": "http"}
    )
    out = capsys.readouterr()
    assert out.out == ""
    assert "secret" not in out.err
    assert "https://example.com/p" in out.err
    line = [ln for ln in out.err.splitlines() if "fetch" in ln][0]
    data = json.loads(line)
    assert data["strategy"] == "http" and data["msg"] == "fetch"


def test_level_filters(capsys):
    configure("WARNING")
    get_logger("t2").info("hidden")
    get_logger("t2").warning("shown")
    err = capsys.readouterr().err
    assert "hidden" not in err and "shown" in err


def test_third_party_libraries_cannot_leak_urls(capsys):
    import logging

    configure("INFO")
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING
