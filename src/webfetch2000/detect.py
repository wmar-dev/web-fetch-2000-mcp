"""Decide whether a response is usable, a failure to escalate from, or a back-off signal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .config import Settings
from .ratelimit import parse_retry_after

BLOCK_MARKERS = (
    "just a moment",
    "cf-chl",
    "cf-browser-verification",
    "enable javascript and cookies",
    "g-recaptcha",
    "hcaptcha",
    "px-captcha",
    "attention required! | cloudflare",
    "verify you are human",
    "verify you are a human",
    "are you a robot",
    "unusual traffic",
    "datadome",
    "access denied",
)
JS_REQUIRED_MARKERS = (
    "you need to enable javascript",
    "enable javascript to",
    "requires javascript",
    "javascript is required",
    "javascript must be enabled",
)
# Marker hits only count on short pages, so long articles that merely mention a captcha pass.
MARKER_MAX_TEXT = 1500
LENGTH_CHECKED = ("html", "xml", "markdown")


@dataclass(frozen=True)
class Verdict:
    kind: Literal["ok", "failed", "deferred"]
    reason: str | None = None
    retry_after: float | None = None


def classify(
    *,
    status: int,
    content_type: str,
    headers: Mapping[str, str],
    text_len: int,
    html_sample: str,
    settings: Settings,
    check_length: bool = True,
) -> Verdict:
    if status in (429, 503):
        return Verdict("deferred", f"http_{status}", parse_retry_after(headers.get("retry-after")))
    if status >= 400:
        return Verdict("failed", f"http_{status}")

    ct = (content_type or "").lower()
    if not any(t in ct for t in LENGTH_CHECKED):
        return Verdict("ok")

    sample = html_sample.lower()
    markers = BLOCK_MARKERS + tuple(m.lower() for m in settings.extra_block_markers)
    if text_len < MARKER_MAX_TEXT and any(m in sample for m in markers):
        return Verdict("failed", "challenge_detected")
    if check_length and text_len < settings.min_content_chars:
        if any(m in sample for m in JS_REQUIRED_MARKERS):
            return Verdict("failed", "js_required")
        return Verdict("failed", "empty_content")
    return Verdict("ok")
