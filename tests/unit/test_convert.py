import json

import pytest

from tests.conftest import PNG_1PX, STATIC_HTML, make_pdf
from webfetch2000.convert import (
    convert_body,
    decode_body,
    is_text_type,
    truncate_bytes,
    truncate_text,
)


def test_html_to_markdown_extracts_main_content():
    out = convert_body(STATIC_HTML.encode(), "text/html; charset=utf-8", "http://x/")
    assert out.kind == "html"
    assert "Static Heading" in out.markdown
    assert "Web fetching" in out.markdown
    assert "<article>" not in out.markdown


def test_pdf_text_extraction():
    out = convert_body(make_pdf("Hello PDF world"), "application/pdf", "http://x/a.pdf")
    assert out.kind == "pdf"
    assert "Hello PDF world" in out.markdown


def test_json_is_fenced_and_pretty():
    out = convert_body(b'{"a":1,"b":[1,2]}', "application/json", "http://x/")
    assert out.kind == "text"
    assert out.markdown.startswith("```json\n")
    assert json.loads(out.markdown.split("```json\n")[1].rsplit("\n```", 1)[0]) == {
        "a": 1,
        "b": [1, 2],
    }


def test_invalid_json_still_fenced():
    out = convert_body(b"{not json", "application/json", "http://x/")
    assert out.markdown.startswith("```json")


@pytest.mark.parametrize(
    "ct,lang",
    [("text/csv", "csv"), ("application/xml", "xml"), ("text/xml", "xml"), ("text/plain", "text")],
)
def test_other_text_types_fenced(ct, lang):
    out = convert_body(b"a,b\n1,2\n", ct, "http://x/")
    assert out.markdown.startswith(f"```{lang}\n")
    assert out.kind == "text"


def test_markdown_passthrough():
    md = "# Title\n\nbody\n"
    out = convert_body(md.encode(), "text/markdown; charset=utf-8", "http://x/")
    assert out.kind == "markdown" and out.markdown == md


def test_binary_is_metadata_only():
    out = convert_body(PNG_1PX, "image/png", "http://x/i.png")
    assert out.kind == "binary" and out.markdown == ""


def test_fence_escapes_backticks_in_content():
    out = convert_body(b"```inner```", "text/plain", "http://x/")
    assert out.markdown.count("````") >= 2  # outer fence longer than inner


def test_is_text_type():
    assert is_text_type("text/html")
    assert is_text_type("application/json; charset=utf-8")
    assert is_text_type("application/xhtml+xml")
    assert not is_text_type("image/png")
    assert not is_text_type("application/pdf")
    assert not is_text_type("")


def test_decode_body_charset():
    assert decode_body("héllo".encode("latin-1"), "text/plain; charset=latin-1") == "héllo"
    assert decode_body("héllo".encode(), "text/plain") == "héllo"
    assert "�" in decode_body(b"\xff\xfe\xfa", "text/plain; charset=utf-8")


def test_truncate_text():
    t, trunc, total = truncate_text("a" * 100, 50)
    assert trunc and total == 100 and t.startswith("a" * 50) and "truncated" in t
    t, trunc, total = truncate_text("short", 50)
    assert (t, trunc, total) == ("short", False, 5)


def test_truncate_bytes_never_alters():
    data = bytes(range(256)) * 4
    out, trunc, total = truncate_bytes(data, 100)
    assert out == data[:100] and trunc and total == 1024
    out, trunc, total = truncate_bytes(data, 5000)
    assert out == data and not trunc
