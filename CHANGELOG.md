# Changelog

## 0.1.0

Initial release.

- `fetch` tool with an escalating HTTP, Chromium and Camoufox strategy ladder, usability
  detection (error statuses, challenge pages, empty JavaScript shells) and a full attempt log.
- Per-domain strategy memory with decay, learned path-section overrides and periodic re-testing,
  shared by all instances through a per-user SQLite store.
- Result cache with `Cache-Control`/ETag revalidation, LRU bounds, in-flight coalescing, and
  `use`/`refresh`/`bypass` modes.
- Markdown output by default (HTML, PDF, JSON/XML/CSV/text), raw output on request, and site
  markdown (`Accept: text/markdown`, e.g. Cloudflare Markdown for Agents) used as-is.
- Per-domain concurrency and rate limits; 429/503 handled as back-off, never escalation.
- Forced strategies, `fallback` control, `headed` override and `negotiate_markdown` override.
- Management tools: `site_memory`, `reset_memory`, `clear_cache`, `strategies`, `config`.
- Layered configuration (defaults, TOML file, `WEBFETCH_*` environment, per-call arguments).
- SSRF protection, URL redaction in logs, graceful shutdown, Docker images (`full`, `slim`).
