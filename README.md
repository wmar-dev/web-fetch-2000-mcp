# web-fetch-2000-mcp

An [MCP](https://modelcontextprotocol.io) server that fetches web content with an escalating
ladder of strategies and **remembers which one works best for each site**.

| Strategy | What it is | Cost |
|---|---|---|
| `http` | Async HTTP client with a browser-like identity; asks sites for markdown directly | cheapest |
| `browser` | Playwright Chromium, renders JavaScript | medium |
| `stealth` | [Camoufox](https://github.com/daijro/camoufox) (stealth Firefox): fingerprint and automation-signal masking | heaviest |

A `fetch` call starts with the best strategy known for the site (the cheapest, for a new site),
escalates when a strategy fails or returns unusable content (error status, challenge page, empty
JavaScript shell), and records the outcome. Results are cached, identical in-flight requests
share one fetch, and each domain is rate limited. Output is **markdown** by default.

## Quickstart

1. Install (needs Python 3.12+ and [uv](https://docs.astral.sh/uv/)):

   ```bash
   git clone https://github.com/wmar-dev/web-fetch-2000-mcp && cd web-fetch-2000-mcp
   uv sync
   ```

   This is enough to try the `http` strategy. Add the browser strategies later, see [Install](#install).

2. Register the server with your MCP client (paths must be absolute):

   ```json
   {
     "mcpServers": {
       "web-fetch": {
         "command": "uv",
         "args": ["run", "--directory", "/path/to/web-fetch-2000-mcp", "webfetch2000"]
       }
     }
   }
   ```

3. Restart the client and ask it to fetch a page, for example "fetch `https://example.com`". The
   client calls the `fetch` tool:

   ```json
   { "url": "https://example.com" }
   ```

   The result is abridged here:

   ```json
   {
     "url": "https://example.com",
     "status": 200,
     "format": "markdown",
     "content": "# Example Domain\n\nThis domain is for use in illustrative examples...",
     "strategy_used": "http",
     "attempts": [{ "strategy": "http", "outcome": "success", "reason": null, "duration_ms": 180 }],
     "cache": "miss"
   }
   ```

   `attempts` lists every strategy tried and why each failed, so you can see when the server
   escalated to a browser. Fetch the same site again and `site_memory` shows what it learned.

To check the setup, call the `strategies` tool: it lists which strategies are available.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium      # strategy "browser"   (optional)
uv run python -m camoufox fetch         # strategy "stealth"   (optional)
```

Without the browser downloads the server still works: the `http` strategy is always available and
`strategies` reports the others as unavailable.

**Linux:** Chromium needs system libraries: `uv run playwright install --with-deps chromium`.
Running a strategy *headed* (or Camoufox with a virtual display) also needs a display or `xvfb`.
Headless, the default, needs neither. Keep the data directory on a local filesystem (not a network
mount): the shared store uses SQLite in WAL mode.

## Use with an MCP client

Add the server to your client's configuration, for example:

```json
{
  "mcpServers": {
    "web-fetch": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/web-fetch-2000-mcp", "webfetch2000"],
      "env": { "WEBFETCH_CACHE_TTL_S": "7200" }
    }
  }
}
```

### Docker

```bash
docker build --target full -t web-fetch-2000 .     # or --target slim for the http strategy only
docker run -i --rm --shm-size=1g -v web-fetch-2000-data:/data web-fetch-2000
```

Use a **named volume** for `/data`: it holds the shared memory and cache (SQLite), and sharing one
SQLite file between the host and a container through a bind mount on Docker Desktop for macOS is
unreliable. Private addresses (including `host.docker.internal`) stay blocked unless you set
`WEBFETCH_ALLOW_PRIVATE_ADDRESSES=1`. See [compose.yaml](compose.yaml).

## Tools

Full schemas and error codes: [specs/001-multi-strategy-web-fetch/contracts/mcp-tools.md](specs/001-multi-strategy-web-fetch/contracts/mcp-tools.md).

| Tool | Purpose |
|---|---|
| `fetch` | Fetch one URL. Options: `format` (`markdown` default, or `raw` original data), `max_chars`, `strategy` (`auto` or force one), `fallback`, `cache` (`use`/`refresh`/`bypass`), `timeout_s`, `headed`, `negotiate_markdown` |
| `site_memory` | Show what was learned for a domain: ranking, per-section overrides, next starting strategy |
| `reset_memory` | Forget what was learned for one domain, or everything |
| `clear_cache` | Remove cached results for a URL, a domain, or everything |
| `strategies` | List strategies in cost order, their availability, and store status |
| `config` | Show the effective settings and where each value came from |

Every `fetch` result reports the strategy used, **every attempt and why it failed**, the cache
status, whether markdown came from the site or was converted, and any warnings. When all
strategies fail, the error lists each one tried and its reason.

Content types: HTML, PDF (text extracted), and JSON/XML/CSV/plain text become markdown; images and
other binaries return metadata only unless `format: raw` (then base64). One URL per call:
crawling, search and batch fetch are out of scope.

## Configuration

Precedence: defaults, then an optional TOML file, then `WEBFETCH_*` environment variables, then
per-call `fetch` arguments. Invalid values stop startup with a message on stderr. Settings are
read at startup (no live reload). Use the `config` tool to see effective values and their sources.

The file is `config.toml` in the per-user config directory (`~/Library/Application
Support/web-fetch-2000/` on macOS, `~/.config/web-fetch-2000/` on Linux), or the path in
`WEBFETCH_CONFIG`.

```toml
cache_ttl_s = 7200
stealth_headless = false
enabled_strategies = ["http", "browser"]
```

Equivalent environment form: `WEBFETCH_CACHE_TTL_S=7200`.

| Group | Settings (default) |
|---|---|
| Limits | `timeout_s` (30, per strategy), `max_response_bytes` (10 MB), `max_redirects` (5), `retries` (2), `retry_backoff_s` (0.5) |
| Concurrency | `http_concurrency` (20), `browser_pages` (2), `stealth_pages` (1), `browser_idle_shutdown_s` (60) |
| Browsers | `browser_headless` (true), `stealth_headless` (true), `block_resources` (image, media, font), `no_sandbox` (false; true in the Docker image) |
| Strategies | `enabled_strategies` (http, browser, stealth) |
| Cache | `cache_ttl_s` (3600), `cache_max_mb` (200), `respect_cache_control` (true) |
| Rate limiting | `domain_concurrency` (2), `domain_rate_per_s` (2), `domain_burst` (4), `max_retry_after_s` (30); 0 disables a limit |
| Usability | `min_content_chars` (200), `extra_block_markers` |
| Identity | `user_agent` (current Chrome), `extra_headers`, `negotiate_markdown` (true) |
| Safety | `allow_private_addresses` (false), `allow_domains`, `deny_domains` |
| Storage / logs | `data_dir`, `log_level` |
| Memory (advanced) | `half_life_days` (14), `reprobe_after_days` (7), `reprobe_probability` (0.05), `score_tolerance` (0.1), `min_observations` (2), `override_min_observations` (5), `max_prefixes_per_domain` (20) |

### Headless vs headed

Both browser strategies run headless by default (faster, lighter, no windows on your desktop).
Headless browsers are easier for sites to detect; the stealth strategy exists for that. For
debugging or stubborn sites, set `stealth_headless = false`, or pass `headed: true` to a single
`fetch` call.

## How it works

- **Memory** (per domain, with learned overrides for path sections like `/app`): decayed success
  counts per strategy; the starting strategy is the cheapest one within a tolerance of the best
  score. Cheaper strategies that failed are periodically re-tested so the memory can recover when
  a site changes. 429/503 responses are back-off signals and never count against a strategy.
- **Cache**: keyed by normalized URL; honors `Cache-Control` and ETag/Last-Modified
  revalidation; bounded with LRU eviction. `cache: "bypass"` neither reads nor writes it.
- **Shared store**: memory and cache live in one per-user SQLite file shared safely by every
  server instance and project.
- **Safety**: only http(s); local and private addresses are blocked by default, re-checked on
  every redirect and for browser sub-requests.
- **Logging**: structured JSON on stderr only (stdout carries the protocol). URLs are logged
  without query strings or fragments.

## Limitations

- Public pages only: no cookies, credentials, logins or CAPTCHA solving, and no proxies.
- Fetched content is returned as-is; it is **untrusted** external data and is not filtered for
  prompt-injection attempts. Treat it accordingly in your client.
- `robots.txt` is not consulted. Politeness comes from per-domain rate limiting and back-off;
  respecting site terms is the operator's responsibility.
- Rate limits are enforced per server process; several instances do not coordinate request rates.
- There is no overall per-request deadline, only per-strategy timeouts. Lower `timeout_s`, force a
  strategy, or set `fallback: false` if your client gives up quickly.
- Pages with very little text (under `min_content_chars`, 200 by default) look like empty
  JavaScript shells and escalate to a browser; for sites made of tiny pages, lower
  `min_content_chars`. Memory is per domain with learned section overrides, so a site that mixes
  static and JavaScript pages in different sections can drift toward the heavier strategy until
  the periodic re-test corrects it.
- The HTTP strategy presents a Chrome user agent over a non-Chrome TLS stack; sites that
  fingerprint TLS will escalate to the browsers.

## Development

```bash
uv run pytest                      # offline suite (no browsers, no network)
uv run pytest -m browser           # real Chromium + Camoufox
uv run pytest -m slow              # load tests
uv run ruff check . && uv run mypy
uv run python tests/benchmark/run_benchmark.py   # opt-in live benchmark (SC-001 to SC-003)
uv run python scripts/smoke_container.py web-fetch-2000:full --browsers
```

The project follows [Spec Kit](https://github.com/github/spec-kit): see
[specs/001-multi-strategy-web-fetch/](specs/001-multi-strategy-web-fetch/) for the spec, plan,
research decisions, data model, contract and task list, and
[.specify/memory/constitution.md](.specify/memory/constitution.md) for the project principles.
