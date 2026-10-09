"""stderr-only structured logging. URLs must go through ``redact_url`` before being logged."""

from __future__ import annotations

import json
import logging as _logging
import sys
import time
from typing import Any
from urllib.parse import urlsplit

_ROOT = "webfetch2000"
_STD = set(_logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def redact_url(url: str | None) -> str:
    """Drop userinfo, query string and fragment so secrets never reach logs or memory."""
    if not url:
        return ""
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        port = p.port
    except ValueError:
        return url.split("?")[0].split("#")[0]
    if not host:
        return url.split("?")[0].split("#")[0]
    netloc = f"{host}:{port}" if port else host
    scheme = f"{p.scheme}://" if p.scheme else ""
    return f"{scheme}{netloc}{p.path}"


class _JsonFormatter(_logging.Formatter):
    def format(self, record: _logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                data[k] = redact_url(v) if k in ("url", "final_url") and isinstance(v, str) else v
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


# Third-party libraries that log full request URLs (query strings included) at INFO.
_NOISY = ("httpx", "httpcore", "hpack", "urllib3", "trafilatura", "courlan", "htmldate")


def configure(level: str = "INFO") -> None:
    for name in _NOISY:
        _logging.getLogger(name).setLevel(_logging.WARNING)
    root = _logging.getLogger(_ROOT)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = _logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False


def get_logger(name: str) -> _logging.Logger:
    return _logging.getLogger(f"{_ROOT}.{name}")
