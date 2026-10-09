# MCP Tool Contract

Transport: stdio. Server name: `web-fetch-2000`. All tools return structured JSON content plus a short text rendering. Errors use the MCP `isError` flag with the structured body below. Nothing is ever written to stdout except protocol messages.

## `fetch`

Fetch a URL and return its content.

**Input**

```json
{
  "type": "object",
  "required": ["url"],
  "properties": {
    "url": {"type": "string", "format": "uri"},
    "format": {"enum": ["markdown", "raw"], "default": "markdown"},
    "max_chars": {"type": "integer", "minimum": 1, "maximum": 2000000, "default": 50000},
    "strategy": {"enum": ["auto", "http", "browser", "stealth"], "default": "auto"},
    "fallback": {"type": "boolean", "default": true},
    "cache": {"enum": ["use", "refresh", "bypass"], "default": "use"},
    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
    "headed": {"type": "boolean", "default": false},
    "negotiate_markdown": {"type": "boolean", "description": "Override the negotiate_markdown setting for this call"}
  }
}
```

**Success output**

```json
{
  "url": "string", "final_url": "string", "status": 200,
  "content_type": "text/html", "format": "markdown",
  "content": "string",
  "truncated": false, "total_chars": 1234,
  "strategy_used": "http",
  "attempts": [{"strategy": "http", "outcome": "success", "reason": null, "duration_ms": 180}],
  "markdown_source": "converted",
  "origin_tokens": null,
  "content_signals": null,
  "cache": "miss",
  "duration_ms": 190,
  "waited_ms": 0,
  "warnings": []
}
```

`markdown_source` is `origin` when the site served markdown itself (content negotiation); `origin_tokens` and `content_signals` echo the site's token estimate and content-usage signals when supplied. With `format: raw` the content is whatever the site returned, which may already be markdown.

Binary content without `format: raw` returns `content: ""` with `content_type`, `size_bytes` and `final_url`.

**Error output**

```json
{
  "error": "all_strategies_failed",
  "message": "string",
  "attempts": [{"strategy": "http", "outcome": "failed", "reason": "http_403", "duration_ms": 120}]
}
```

Error codes: `invalid_url`, `blocked_address`, `unsupported_scheme`, `all_strategies_failed`, `strategy_unavailable`, `timeout`, `too_large` (only when truncating at `max_response_bytes` cannot give usable output, such as a cut-off PDF; otherwise the body is truncated and `warnings` says so), `rate_limited` (the site kept asking us to back off beyond the retry limit, or queueing exceeded `timeout_s`; includes the last `retry_after_s` when known).

## `site_memory`

Show what has been learned for a site.

**Input**: `{"domain": "string", "path": "string (optional)"}`

**Output**: `{"domain", "ranking": [{"strategy", "score", "successes", "failures", "mean_duration_ms", "last_attempt_at"}], "overrides": [{"path_prefix", "ranking": [...]}], "next_start_strategy": "http"}`

## `reset_memory`

Clear learned strategy data.

**Input**: `{"domain": "string (optional; omit to clear everything)"}`

**Output**: `{"cleared_domains": 1}`

## `clear_cache`

Clear cached results.

**Input**: `{"url": "string (optional)", "domain": "string (optional)"}`; omitting both clears the whole cache.

**Output**: `{"cleared_entries": 12}`

## `strategies`

List strategies, cost order and availability.

**Input**: none

**Output**: `{"strategies": [{"name": "http", "cost": 1, "available": true}, {"name": "browser", "cost": 2, "available": false, "reason": "browser_not_installed"}, {"name": "stealth", "cost": 3, "available": true}], "store": {"available": true, "path": "string"}}`

## `config`

Show the effective settings and where each value came from.

**Input**: none

**Output**: `{"settings": {"<name>": {"value": "any", "source": "default | file | env"}}, "config_file": "string or null"}`

Settings are read at startup; per-call `fetch` arguments override them for that call only. Defaults and precedence are listed in [research.md](../research.md) decision 15.

## Compatibility

Tool names and the `fetch` input and output fields above are the public contract. Adding optional fields is non-breaking; removing or renaming is a breaking change requiring a major version bump.
