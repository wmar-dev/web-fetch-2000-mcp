# Quickstart and Validation Guide

Contract details: [contracts/mcp-tools.md](contracts/mcp-tools.md). Data details: [data-model.md](data-model.md).

## Prerequisites

- Python 3.12+ and `uv`
- Install dependencies: `uv sync`
- Browsers (optional, needed for tiers 2 and 3): `uv run playwright install chromium` and `uv run python -m camoufox fetch`
- Linux only: install Chromium's system libraries with `uv run playwright install --with-deps chromium`; running headed or with a virtual display also needs a display or `xvfb`. macOS needs no extra system packages.
- The data directory must be on a local filesystem (not a network mount) on both platforms.

## Run with Docker

Build: `docker build --target full -t web-fetch-2000 .` (or `--target slim` for the HTTP tier only).

MCP client command:

```text
docker run -i --rm --shm-size=1g -v web-fetch-2000-data:/data web-fetch-2000
```

- Use a named volume for `/data` so memory and cache persist across runs and are shared by every container using that volume. Avoid bind-mounting a host directory that a host-installed server also uses (SQLite WAL is unreliable across Docker Desktop for macOS file sharing).
- Pass settings with `-e WEBFETCH_CACHE_TTL_S=7200` or mount a TOML file.
- `host.docker.internal` and Docker network addresses are blocked by default; see `allow_private_addresses`.

## Run the server

`uv run webfetch2000` (stdio). Register it with an MCP client using that command.

## Configuration

Precedence: defaults, then an optional TOML file (for example `~/.config/web-fetch-2000/config.toml`), then `WEBFETCH_*` environment variables (usable in the MCP client's `env` block), then per-call `fetch` arguments. Invalid values stop startup with a message on stderr. Use the `config` tool to see effective values and their sources. The full settings table is in [research.md](research.md) decision 15.

Example:

```toml
cache_ttl_s = 7200
stealth_headless = false
enabled_strategies = ["http", "browser"]
```

Equivalent environment form: `WEBFETCH_CACHE_TTL_S=7200`.

## Run the tests

- Default offline suite: `uv run pytest -m "not browser"`
- Real-browser suite: `uv run pytest -m browser`

## Validation scenarios

| # | Scenario | Steps | Expected |
|---|----------|-------|----------|
| 1 | Static page uses cheapest tier | `fetch` a static page | `strategy_used: http`, no browser launched (SC-005) |
| 2 | JS page escalates | `fetch` a page whose content is injected by script | `attempts` shows `http` failed with `empty_content`, `browser` success |
| 3 | Protected page escalates to stealth | `fetch` a page that blocks plain and Chromium clients | `strategy_used: stealth`, or an error listing all attempts |
| 4 | Memory skips failed tiers | Repeat scenario 2 or 3 | First attempt is now the remembered strategy; faster (SC-003); `site_memory` shows the ranking |
| 5 | Memory survives restart | Restart the server, repeat | Same starting strategy (SC-008) |
| 6 | Cache hit | `fetch` same URL twice | Second has `cache: hit` and returns in under 100 ms (SC-004) |
| 7 | Cache bypass and refresh | `fetch` with `cache: bypass`, then `refresh` | New network request each time |
| 8 | Coalescing | Send two identical requests concurrently | One network request in the logs |
| 9 | Raw and truncation | `fetch` with `format: raw` and small `max_chars` | Original bytes as received, truncated flag set |
| 10 | Non-HTML | `fetch` a PDF, a JSON URL, an image | Markdown text, fenced JSON, metadata-only |
| 11 | Safety | `fetch` `http://127.0.0.1` and `file:///etc/passwd` | `blocked_address` and `unsupported_scheme` (SC-009) |
| 12 | Degraded mode | Run without browser binaries | HTTP works; `strategies` reports browsers unavailable |
| 13 | Shared store concurrency | Start several instances and fetch concurrently | No lost outcomes, store readable (SC-010) |
| 14 | Config layering | Set a value in the file, override it with an env var, override again per call | Each layer wins in order; `config` shows the source |
| 15 | Invalid config | Set `WEBFETCH_CACHE_TTL_S=abc` | Server exits with a clear stderr message |
| 16 | Headed override | `fetch` with `headed: true` on a browser tier | Visible window opens for that call only |
| 17 | Cross-platform | Run the offline and `browser` suites on macOS and Linux (CI matrix) | Both pass; paths resolve to the platform's standard user directories |
| 18 | Container run | Build the image; run it with `docker run -i --rm`; `fetch` with each strategy | All three strategies work with no host browser install (SC-012) |
| 19 | Container persistence | Run, fetch, stop; run again with the same volume | Memory and cache persist; process runs as non-root |
| 20 | Container cleanup | Fetch with stealth then stop the container | No orphaned browser processes (tini reaps children) |
| 21 | Site markdown | `fetch` a Cloudflare zone with Markdown for Agents enabled (or the local test server returning `text/markdown`) | `markdown_source: origin`, `origin_tokens` and `content_signals` populated, no HTML conversion (SC-013) |
| 22 | Negotiation cache safety | Fetch the same URL with `negotiate_markdown: true`, then `false` | Representations are cached separately |
| 23 | Per-domain limits | Send 50 concurrent `fetch` calls to one domain | In-flight never exceeds `domain_concurrency`; request rate stays within `domain_rate_per_s` (SC-014) |
| 24 | Back-off on 429 | Local server returns 429 with `Retry-After: 2`, then 200 | Waits about 2 s, retries the same strategy, no escalation, memory unchanged (SC-015) |
| 25 | Reset and clear | `reset_memory`, `clear_cache` | Counts returned; memory empty afterward |
