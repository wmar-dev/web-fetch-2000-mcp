"""Output format, size caps, and non-HTML handling (FR-010, FR-019)."""

import base64

from tests.conftest import PNG_1PX, STATIC_HTML
from tests.helpers import ladder, make_settings, outcome
from webfetch2000.models import FetchRequest
from webfetch2000.router import Router
from webfetch2000.strategies.http import HttpStrategy


def router(strategies, **kw):
    return Router(make_settings(**kw), strategies)


URL = "http://fake.test/p"


async def test_markdown_is_the_default():
    res = await router(ladder()).fetch(FetchRequest(url=URL))
    assert res.format == "markdown" and "<article>" not in res.content


async def test_raw_returns_original_bytes_as_text():
    res = await router(ladder()).fetch(FetchRequest(url=URL, format="raw"))
    assert res.format == "raw" and res.content == STATIC_HTML
    assert res.markdown_source is None and res.content_encoding == "utf-8"
    assert res.total_bytes == len(STATIC_HTML.encode())


async def test_max_chars_truncates_markdown_with_marker():
    res = await router(ladder()).fetch(FetchRequest(url=URL, max_chars=100))
    assert res.truncated and res.total_chars and res.total_chars > 100
    assert "[truncated: showing 100 of" in res.content
    assert res.content.startswith(res.content[:50])


async def test_untruncated_has_no_marker():
    res = await router(ladder()).fetch(FetchRequest(url=URL, max_chars=500_000))
    assert not res.truncated and "[truncated" not in res.content
    assert res.total_chars == len(res.content)


async def test_raw_is_not_limited_by_max_chars():
    res = await router(ladder()).fetch(FetchRequest(url=URL, format="raw", max_chars=10))
    assert res.content == STATIC_HTML and not res.truncated


async def test_raw_truncated_by_response_cap_never_altered():
    body = "<html><body><p>" + "abcdefghij" * 5000 + "</p></body></html>"
    s = ladder(http=[outcome(body, body_truncated=True, total_bytes=len(body))])
    res = await router(s).fetch(FetchRequest(url=URL, format="raw"))
    assert res.truncated and res.total_bytes == len(body)


async def test_binary_markdown_is_metadata_only():
    s = ladder(http=[outcome(PNG_1PX, content_type="image/png", url="http://fake.test/i.png")])
    res = await router(s).fetch(FetchRequest(url=URL))
    assert res.content == "" and res.size_bytes == len(PNG_1PX) and res.content_type == "image/png"
    assert res.final_url == "http://fake.test/i.png" and res.markdown_source is None


async def test_binary_raw_is_base64():
    s = ladder(http=[outcome(PNG_1PX, content_type="image/png")])
    res = await router(s).fetch(FetchRequest(url=URL, format="raw"))
    assert res.content_encoding == "base64"
    assert base64.b64decode(res.content) == PNG_1PX


async def test_pdf_json_text_csv_against_local_site(site):
    settings = make_settings()
    r = Router(settings, {"http": HttpStrategy(settings, None)})
    pdf = await r.fetch(FetchRequest(url=site.url("/pdf")))
    assert "Hello PDF world" in pdf.content and pdf.markdown_source == "converted"
    js = await r.fetch(FetchRequest(url=site.url("/json")))
    assert js.content.startswith("```json") and '"a": 1' in js.content
    txt = await r.fetch(FetchRequest(url=site.url("/text")))
    assert "plain text body" in txt.content
    csv = await r.fetch(FetchRequest(url=site.url("/csv")))
    assert csv.content.startswith("```csv")
    raw_json = await r.fetch(FetchRequest(url=site.url("/json"), format="raw"))
    assert raw_json.content == '{"a": 1, "b": [1, 2, 3]}'
    img = await r.fetch(FetchRequest(url=site.url("/image")))
    assert img.content == "" and img.size_bytes == len(PNG_1PX)
    await r.close()


async def test_large_page_default_cap_and_warning(site):
    settings = make_settings()
    r = Router(settings, {"http": HttpStrategy(settings, None)})
    res = await r.fetch(FetchRequest(url=site.url("/large?bytes=200000")))
    assert res.truncated and len(res.content) < 51_000 and "[truncated" in res.content
    await r.close()
