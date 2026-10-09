"""Turn response bodies into markdown (HTML, PDF, text types) and truncate safely."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["html", "pdf", "text", "markdown", "binary"]

_TEXT_EXACT = {
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
    "application/x-javascript",
    "application/yaml",
    "application/x-yaml",
    "application/csv",
    "application/rss+xml",
    "application/atom+xml",
    "application/ld+json",
}
_LANG = {"json": "json", "csv": "csv", "xml": "xml", "yaml": "yaml"}


class ConversionError(Exception):
    pass


@dataclass
class Converted:
    markdown: str
    kind: Kind


def _base_type(content_type: str) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def is_text_type(content_type: str) -> bool:
    ct = _base_type(content_type)
    if not ct:
        return False
    return ct.startswith("text/") or ct in _TEXT_EXACT or ct.endswith(("+json", "+xml"))


def is_html_type(content_type: str) -> bool:
    ct = _base_type(content_type)
    return ct in ("text/html", "application/xhtml+xml")


def is_markdown_type(content_type: str) -> bool:
    return _base_type(content_type) in ("text/markdown", "text/x-markdown")


def decode_body(body: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    charset = m.group(1) if m else None
    if charset is None and is_html_type(content_type):
        m2 = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", body[:4096], re.I)
        charset = m2.group(1).decode("ascii", "ignore") if m2 else None
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _fence(text: str, lang: str) -> str:
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{text.rstrip(chr(10))}\n{ticks}"


def html_to_markdown(html: str, url: str) -> str:
    import trafilatura

    out = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_tables=True,
        include_formatting=True,
        favor_recall=True,
    )
    if not out:
        out = trafilatura.html2txt(html) or ""
    return out.strip()


def pdf_to_text(body: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(body))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
    except Exception as e:  # pypdf raises many types on damaged files
        raise ConversionError(f"could not read PDF: {e}") from e
    return "\n\n".join(p for p in pages if p)


def convert_body(body: bytes, content_type: str, url: str) -> Converted:
    ct = _base_type(content_type)
    if ct == "application/pdf":
        return Converted(pdf_to_text(body), "pdf")
    if is_markdown_type(ct):
        return Converted(decode_body(body, content_type), "markdown")
    if is_html_type(ct):
        return Converted(html_to_markdown(decode_body(body, content_type), url), "html")
    if is_text_type(ct):
        text = decode_body(body, content_type)
        if ct == "application/json" or ct.endswith("+json"):
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                pass
            lang = "json"
        elif ct.endswith("xml"):
            lang = "xml"
        elif ct.endswith("csv"):
            lang = "csv"
        else:
            lang = _LANG.get(ct.rsplit("/", 1)[-1], "text")
        return Converted(_fence(text, lang), "text")
    return Converted("", "binary")


def truncate_text(text: str, max_chars: int) -> tuple[str, bool, int]:
    total = len(text)
    if total <= max_chars:
        return text, False, total
    return (
        text[:max_chars] + f"\n\n[truncated: showing {max_chars} of {total} characters]",
        True,
        total,
    )


def truncate_bytes(data: bytes, max_bytes: int) -> tuple[bytes, bool, int]:
    total = len(data)
    if total <= max_bytes:
        return data, False, total
    return data[:max_bytes], True, total
