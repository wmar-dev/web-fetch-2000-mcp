import pytest

from webfetch2000.config import Settings
from webfetch2000.detect import classify

S = Settings()
LONG = 500


def c(**kw):
    base = dict(
        status=200,
        content_type="text/html",
        headers={},
        text_len=LONG,
        html_sample="<p>hi</p>",
        settings=S,
    )
    base.update(kw)
    return classify(**base)


def test_ok():
    v = c()
    assert v.kind == "ok" and v.reason is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 500, 502])
def test_error_statuses_fail(status):
    v = c(status=status)
    assert v.kind == "failed" and v.reason == f"http_{status}"


@pytest.mark.parametrize("status", [429, 503])
def test_backoff_statuses_deferred(status):
    v = c(status=status, headers={"retry-after": "7"})
    assert v.kind == "deferred" and v.retry_after == 7
    assert c(status=status).retry_after is None


def test_short_text_is_empty_content():
    v = c(text_len=50)
    assert v.kind == "failed" and v.reason == "empty_content"


def test_min_content_chars_configurable():
    assert c(text_len=50, settings=Settings(min_content_chars=10)).kind == "ok"


@pytest.mark.parametrize(
    "sample",
    [
        "<title>Just a moment...</title>",
        "<div class='cf-chl-widget'></div>",
        "Please enable JavaScript and cookies to continue",
        '<div class="g-recaptcha"></div>',
        "<script src='https://hcaptcha.com/1/api.js'></script>",
        "Attention Required! | Cloudflare",
        "Please verify you are human",
    ],
)
def test_challenge_markers_on_200(sample):
    v = c(html_sample=sample, text_len=300)
    assert v.kind == "failed" and v.reason == "challenge_detected"


def test_marker_ignored_when_page_is_long_article():
    v = c(html_sample="we discuss captcha and recaptcha here", text_len=20_000)
    assert v.kind == "ok"


def test_extra_block_markers():
    s = Settings(extra_block_markers=("custom wall",))
    assert (
        c(html_sample="CUSTOM WALL here", text_len=300, settings=s).reason == "challenge_detected"
    )


def test_js_required_shell():
    v = c(
        html_sample="<noscript>You need to enable JavaScript to run this app.</noscript><div id=root></div>",
        text_len=40,
    )
    assert v.kind == "failed" and v.reason in {"js_required", "empty_content"}


def test_non_html_skips_length_rule():
    assert c(content_type="application/json", text_len=5, html_sample="").kind == "ok"
    assert c(content_type="application/pdf", text_len=0, html_sample="").kind == "ok"


def test_skip_length_rule_flag_for_raw():
    assert c(text_len=0, check_length=False).kind == "ok"


def test_error_status_with_non_html_still_fails():
    assert c(status=404, content_type="application/json").kind == "failed"
