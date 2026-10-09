# Research: Multi-Strategy Web Fetch MCP Server

No `NEEDS CLARIFICATION` items remain in the Technical Context. Decisions below also settle the items deferred from clarification.

## 1. Language and MCP framework

- **Decision**: Python 3.12+, official `mcp` SDK (v1.30, FastMCP API), stdio transport.
- **Rationale**: The user asked for Python tools (requests to Playwright); Camoufox is Python-first; the official SDK is stable and supports typed tools.
- **Alternatives**: TypeScript SDK (Camoufox is Python-driven, so a bridge would be needed); a hand-rolled JSON-RPC server (needless maintenance).

## 2. HTTP tier

- **Decision**: `httpx` async client with HTTP/2, streaming body reads that truncate at the size cap with a warning, redirect limit, and manual redirect re-validation.
- **Rationale**: The user mentioned Python `requests`; `requests` is blocking and cannot stream-cap cleanly inside an async server. `httpx` has the same ergonomics and is async.
- **Alternatives**: `requests` in a thread pool (works, worse cancellation and concurrency); `curl_cffi` for TLS impersonation (a strong possible extra tier between HTTP and browser, deferred as a future enhancement to keep v1 to the three required tiers).

## 3. Browser tier

- **Decision**: Playwright Chromium, one shared browser, new isolated context per fetch, resource blocking for images, media and fonts by default, `networkidle`-or-timeout wait.
- **Rationale**: Renders JavaScript; blocking heavy resources saves time and bandwidth (constitution III).
- **Alternatives**: Playwright Firefox (Camoufox already covers Firefox); a remote browser service (out of scope, adds dependency).

## 4. Stealth tier

- **Decision**: Camoufox (0.5.8) via its Playwright-compatible API, fingerprint and behavior masking only; no CAPTCHA solving and no proxies (per clarification).
- **Rationale**: User-specified. **Version constraint found**: Camoufox 0.5.8 requires `playwright<1.63`, while the latest Playwright is 1.63, so `playwright` must be pinned `<1.63`. Camoufox downloads its own browser binary (`python -m camoufox fetch`).
- **Alternatives**: patched Chromium stealth plugins (less robust, rejected by user choice).

## 5. Storage

- **Decision**: One SQLite database in the platform user-data dir (`platformdirs`), WAL mode, `busy_timeout`, short write transactions, outcomes stored as append-friendly counters updated with atomic `UPDATE ... SET x = x + 1`.
- **Rationale**: Meets shared-by-all-instances and no-lost-updates (FR-021, FR-022) without a daemon; stdlib only; atomic increments avoid read-modify-write races.
- **Alternatives**: JSON files (races, corruption); a separate cache server such as Redis (extra process, against local-tool simplicity).

## 6. Strategy memory algorithm

- **Decision**: For each (domain, path-prefix or empty, strategy) keep time-decayed success and failure counts and mean duration. Score = Laplace-smoothed success rate (`(s+1)/(s+f+2)`) with half-life of 14 days. Starting strategy = the cheapest whose score is within 0.1 of the best score and has at least 2 observations; unseen strategies default to the ladder order. Re-probe: a cheaper strategy that failed is retried when its last attempt is older than 7 days or with 5% probability per fetch, whichever comes first. A path-prefix override is created after at least 5 observations for that prefix whose best strategy differs from the domain's, and is removed when it matches the domain default again for 10 consecutive observations.
- **Rationale**: Simple, explainable, cheap to compute, handles drift (FR-007, FR-020). Constants are configurable.
- **Alternatives**: multi-armed bandit libraries (overkill); fixed TTL on failures only (slow to adapt, no path nuance).

## 7. Detecting unusable content

- **Decision**: A response counts as failure when: status is 403, 429 or 5xx; body is below a minimum text length after extraction; known challenge or block markers appear (Cloudflare, "enable JavaScript", CAPTCHA widgets); or the HTML is a script-only shell. Detection is a pure function with fixtures so it is easy to test and extend.
- **Thresholds**: minimum extracted text defaults to 200 characters (`min_content_chars`); additional block markers can be added through `extra_block_markers`. Non-HTML types and `format: raw` skip the text-length rule. A forced strategy with fallback disabled returns whatever it got, with a warning if it looks unusable.
- **Rationale**: FR-003 requires 200-status block pages to escalate.
- **Alternatives**: status-code-only detection (misses most real blocks).

## 8. Cache

- **Decision**: Key = hash of (normalized URL, output-affecting options such as format). Store extracted markdown and raw bytes (raw only up to the size cap). Default TTL 1 hour, honoring `Cache-Control: max-age`/`no-store` and storing ETag and Last-Modified for conditional revalidation after expiry. LRU eviction to a size cap (default 200 MB). Single-flight via an in-process map of key to future.
- **Rationale**: FR-008 and FR-009; conditional requests save bandwidth.
- **Alternatives**: in-memory only (loses the shared benefit and violates FR-021).

## 9. Content conversion

- **Decision**: `trafilatura` for HTML to markdown with main-content extraction; `pypdf` for PDF text; JSON, XML, CSV and plain text pass through a thin markdown wrapper (fenced block); binaries return a metadata-only result.
- **Rationale**: FR-010 and FR-019; trafilatura is purpose-built for main content, which keeps token cost low.
- **Alternatives**: `markdownify` or `html2text` (convert everything including navigation noise); PyMuPDF (heavier, licensing).

## 10. Safety

- **Decision**: Allow only http and https; resolve DNS and reject loopback, private, link-local, multicast and reserved ranges (IPv4 and IPv6), re-checking on every redirect; in browser tiers, intercept requests and apply the same check. A config flag permits local addresses for development.
- **Rationale**: FR-014 and the constitution's safety constraint.
- **Alternatives**: hostname deny-lists (bypassable via DNS or redirects).

## 11. Concurrency and resources

- **Decision**: `asyncio` semaphores: 20 HTTP, 2 Chromium pages, 1 Camoufox page by default. Browsers launch lazily and close after 60 s idle and on shutdown; all page and context objects are closed in `finally`.
- **Rationale**: FR-013, FR-018, SC-006.
- **Alternatives**: browser pool prewarmed at startup (wastes memory when unused).

## 12. Testing approach

- **Decision**: Layered tests. Unit tests for scoring, detection, conversion, safety, cache. Contract tests validate tool schemas and error shapes. Integration tests run the router against fake strategies and a local HTTP server that simulates static, JS-rendered, blocked and slow pages. A `browser`-marked suite exercises real Playwright and Camoufox and is skipped when binaries are absent. A concurrency test with several processes writes to the shared store (SC-010).
- **Rationale**: Constitution I; keeps the default run offline and fast.

## 13. Selenium considered and rejected

- **Decision**: Do not use Selenium.
- **Rationale**: Camoufox is built on Playwright, so Playwright is already required; a second driver would duplicate binaries and maintenance. Selenium has no async API, which complicates the concurrency and cleanup guarantees (FR-013, FR-018). Playwright provides request interception for the private-network check in browser tiers. Stock Selenium also exposes more automation signals.
- **Alternatives**: Selenium-based stealth drivers (for example undetected-chromedriver); can be added later as another strategy behind the same protocol without changing the router or memory.

## 14. Headed vs headless

- **Decision**: Both browser tiers run headless by default. Each is configurable (`browser_headless`, `stealth_headless`), and `fetch` accepts an optional `headed` flag for one-off debugging. Headed is not an automatic escalation step in v1.
- **Rationale**: Headless is faster, lighter and does not open windows on the user's desktop (constitution III). Headless Chromium is more detectable, which is what the stealth tier addresses. A headed browser can pass checks headless cannot, so it is left available as an opt-in.
- **Alternatives**: headed as a fourth automatic strategy (opens windows unprompted and adds a tier to track in memory; reconsider after v1 usage data); virtual-display headless on Linux for Camoufox (to be verified against current Camoufox docs during implementation).

## 15. Configuration

- **Decision**: Precedence is built-in defaults, then an optional TOML file in the per-user config directory (`platformdirs`), then `WEBFETCH_`-prefixed environment variables, then per-call `fetch` arguments. Settings are validated once at startup with pydantic and fail fast with a stderr message. No live reload in v1. A `config` tool reports effective values and their source.
- **Rationale**: Environment variables fit the MCP client's `env` block, a file suits persistent preferences, and per-call arguments cover live changes. Fail-fast validation avoids silently ignored typos.
- **Alternatives**: environment-only (awkward for many settings); YAML or JSON config (TOML is stdlib-readable via `tomllib`); live reload (extra complexity with little benefit for a local tool).

### Settings reference (defaults)

| Group | Settings |
|-------|----------|
| Limits | `timeout_s` 30, `max_response_bytes` 10 MB, `max_redirects` 5, `retries` 2 with backoff |
| Concurrency | `http_concurrency` 20, `browser_pages` 2, `stealth_pages` 1, `browser_idle_shutdown_s` 60 |
| Browsers | `browser_headless` true, `stealth_headless` true, `block_resources` images, media, fonts |
| Strategies | `enabled_strategies` all three |
| Cache | `cache_ttl_s` 3600, `cache_max_mb` 200, `respect_cache_control` true |
| Memory (advanced) | `half_life_days` 14, `reprobe_after_days` 7, `reprobe_probability` 0.05, `score_tolerance` 0.1 |
| Usability | `min_content_chars` 200, `extra_block_markers` (list) |
| Identity | `user_agent` (default: current Chrome string), `extra_headers` |
| Negotiation | `negotiate_markdown` true |
| Rate limiting | `domain_concurrency` 2, `domain_rate_per_s` 2, `domain_burst` 4, `max_retry_after_s` 30 |
| Safety | `allow_private_addresses` false, `allow_domains`, `deny_domains` |
| Storage and logs | `data_dir`, `log_level` |
| Containers and sandboxing | `no_sandbox` false (true in the container image) |

## 16. macOS and Linux support

- **Decision**: Support macOS and Linux equally; Windows is out of scope for v1. Platform-neutral building blocks only: `platformdirs` for config, data and cache locations (XDG on Linux, `~/Library` on macOS), stdlib `sqlite3` WAL (works on both; the data dir must be on a local filesystem, not a network mount), `pathlib` for all paths, no shelling out to platform tools, and `asyncio` signal handling for SIGINT and SIGTERM with browser cleanup on both.
- **Linux specifics**: Chromium needs system libraries (`playwright install --with-deps chromium`); headed or virtual-display Camoufox needs a display or `xvfb`; headless needs neither. Containers may need `--no-sandbox` or extra capabilities, exposed as a setting rather than a default.
- **macOS specifics**: no extra system packages; headed windows appear on the desktop; binaries land under the user cache directory.
- **Verification**: CI matrix on `ubuntu-latest` and `macos-latest` running the offline suite and the `browser` suite (browsers installed in the job). The multi-process store test runs on both. Not verified locally on Linux yet.
- **Alternatives**: macOS-only first (cheaper, but the user wants both and Linux is where most automation runs); Windows (extra path, signal and locking differences, deferred).

## 17. Docker support

- **Decision**: Ship a `Dockerfile` and a `compose.yaml`. The MCP client launches the server with `docker run -i --rm` (stdio passes through `-i`; no ports are published). Multi-stage build on a slim Debian-based Python image, `uv` for dependency install, Chromium installed with `playwright install --with-deps chromium`, Camoufox fetched at build time, `xvfb` installed for virtual-display mode, `tini` as init to reap browser child processes, non-root user. Two image targets: `full` (all three strategies, default) and `slim` (HTTP tier only, small). Data, config and cache live under `/data` (`WEBFETCH_DATA_DIR`) intended to be a volume; settings come from `WEBFETCH_*` env or a mounted TOML file.
- **Rationale**: Satisfies FR-025 and SC-012 and removes host-side browser and system-library setup, especially on Linux. Stdio over `docker run -i` is the standard way MCP clients run containerized servers. `tini` prevents zombie browser processes (FR-018). The slim target honors resource efficiency for users who only need HTTP.
- **Container specifics**:
  - Chromium needs a larger shared memory area: run with `--shm-size=1g` (or `--ipc=host`); the sandbox is disabled via the `no_sandbox` setting, enabled by default in the image only, because the container is the isolation boundary.
  - Private-address blocking still applies inside the container, so `host.docker.internal` and the Docker network ranges are blocked by default; `allow_private_addresses` or the allow-list opens them deliberately.
  - Logs go to stderr (visible with `docker logs` when not attached).
- **Shared store caveat**: the "share everything" decision (FR-021) holds across containers that mount the same volume. Sharing one SQLite WAL file between the host and a container through a bind mount on Docker Desktop for macOS is unreliable (WAL needs shared-memory file support that the VM file-sharing layer may not provide). Recommended: a named Docker volume for container use; a host-installed server uses its own per-user store. Cross-sharing between host and container is documented as unsupported on macOS bind mounts.
- **Architectures**: build `linux/amd64` and `linux/arm64`. Camoufox arm64 Linux availability must be verified at implementation time; if missing, the arm64 image ships with the stealth tier reported as unavailable (degraded mode, FR-015).
- **Alternatives**: a single fat image (large for HTTP-only users); Alpine base (Chromium and Camoufox need glibc); running the server over HTTP inside the container (needs port publishing and auth, out of scope for a local stdio tool).

## 18. Site-provided markdown (Cloudflare Markdown for Agents)

- **Source**: https://blog.cloudflare.com/markdown-for-agents/. Sites on Cloudflare (Pro, Business, Enterprise, SSL for SaaS; opt-in per zone, beta) convert HTML to markdown at the edge when the request carries `Accept: text/markdown`. Responses carry `Content-Type: text/markdown; charset=utf-8`, `Vary: accept`, an `x-markdown-tokens` token estimate, and a `Content-Signal` header (for example `ai-train=yes, search=yes, ai-input=yes`).
- **Decision**: The HTTP tier sends `Accept: text/markdown, text/html;q=0.9, */*;q=0.8`. If the response is `text/markdown`, it is used as-is (no HTML extraction), still subject to the size cap, safety checks and block-page detection. Results record `markdown_source: origin`, `origin_tokens` from `x-markdown-tokens`, and `content_signals` from `Content-Signal`. This applies to any site honoring the negotiation, not only Cloudflare.
- **Cache**: the cache key includes the negotiated representation, and `Vary: accept` is respected, so a markdown response is never served as HTML or the reverse.
- **Content signals**: surfaced as metadata and, when a signal such as `ai-input=no` is present, as a warning. The server does not block on it in v1 (policy stays with the operator and assistant), but this is configurable later.
- **Browser tiers**: no `Accept` override. Changing the document request's `Accept` header would make a real-browser fingerprint look unusual and could hurt the stealth tier. If the HTTP tier fails, the browser tiers fetch HTML normally and convert it.
- **Memory**: a site that serves markdown simply records HTTP-tier successes, so memory favors the cheapest tier with no special case.
- **Setting**: `negotiate_markdown` (default true) to turn the header off, for example for a site that misbehaves with it.
- **Rationale**: Cloudflare reports roughly 80% fewer tokens for markdown versus HTML on its own blog post (16,180 to 3,150), and it saves our extraction work, supporting constitution III.
- **Alternatives**: always converting HTML ourselves (more tokens and CPU, no origin-quality markdown); probing a `.md` URL suffix or `llms.txt` (not part of this mechanism; possible later enhancement).

## 19. Per-domain rate limiting and back-off

- **Decision**: A limiter keyed by registrable domain, shared by all strategies: a concurrency cap (default 2 in flight per domain) and a token bucket (default 2 requests per second, burst 4). Excess requests queue until a slot or token is free, bounded by the call's `timeout_s`. A browser fetch counts as one request for the main document; subresource loads are not counted. Cache hits and coalesced duplicates never consume tokens. Setting either value to 0 disables that limit.
- **Back-off**: `429` and `503` are classified as `deferred`, not `failed`. The server waits for `Retry-After` (seconds or HTTP date) capped at `max_retry_after_s` (default 30), then retries the same strategy up to the retry limit; if it still fails it returns `rate_limited`. Deferred outcomes are not recorded in site memory and never trigger escalation, because a heavier strategy would hit the site harder.
- **Which domain**: strategy memory is recorded against the requested domain; rate limits apply to every domain actually contacted (clarification decision). The HTTP tier acquires limiter slots per redirect hop, and the browser tiers do so for main-document navigations observed through the same request interception used for the private-address check. Subresource loads remain uncounted.
- **Scope across instances**: limits are enforced in-process. Several server instances sharing the store do not coordinate request rates in v1 (the shared store holds strategy memory, not live counters). Documented as a limitation; a shared per-domain `not_before` timestamp (set from `Retry-After`) in the store is a possible follow-up.
- **robots.txt**: not consulted (clarification decision).
- **Settings**: `domain_concurrency` 2, `domain_rate_per_s` 2, `domain_burst` 4, `max_retry_after_s` 30.
- **Rationale**: Protects sites and the user's IP from blocks, and keeps escalation for real blocks only (FR-027, FR-028). In-process limiting keeps the hot path off the database.
- **Alternatives**: a fixed delay between requests (wastes time on fast, tolerant sites); store-backed global limiter (extra database writes on every request); treating 429 as a block and escalating (causes harder hits and bans).

### Note on total request time

No overall deadline exists (clarification decision), so worst-case time is roughly (strategies attempted) x (`timeout_s` x (1 + retries)) plus queueing and `Retry-After` waits (each capped at `max_retry_after_s`). Callers on clients with short tool timeouts should lower `timeout_s`, force a strategy, or set `fallback: false`. An overall deadline remains a possible later addition.

## 20. Request identity

- **Decision**: The HTTP tier sends a browser-like identity by default: a current desktop Chrome `User-Agent` plus matching typical headers (`Accept-Language`, `Sec-Fetch-*`, `Upgrade-Insecure-Requests`), in a realistic order. `user_agent` and `extra_headers` settings override it. The default string is kept in one module and updated with releases. The browser tiers use their engine's native identity (Chromium's own, Camoufox's generated fingerprint), not this string.
- **Rationale**: Clarification decision; maximizes what the cheapest tier can fetch, which keeps more traffic off the heavy tiers (constitution III).
- **Known limitation**: A Chrome user agent sent over a non-Chrome TLS stack (httpx) can still be flagged by TLS-fingerprinting sites; those sites escalate to the browser tiers and memory learns it. TLS impersonation (e.g. `curl_cffi`) remains a possible later enhancement (see decision 2).
- **Interaction with markdown negotiation**: the `Accept: text/markdown, text/html;q=0.9` header (decision 18) deliberately differs from a browser's `Accept`; it can be disabled with `negotiate_markdown` if a site reacts badly.
- **Alternatives**: honest tool identity by default (more transparent but blocked more often, pushing work to heavier tiers); honest first then browser-like retry (extra request per blocked site).

## 21. URL privacy in logs and storage

- **Decision**: A single `redact_url()` helper strips query strings and fragments (and any `user:pass@` userinfo) and is the only way URLs reach the logger or `outcomes`. Strategy memory already stores only domain and path prefix. The cache keeps full URLs because keys depend on them; entries expire (TTL) and `clear_cache` removes them. Callers can use `cache: bypass` so a sensitive URL is never written.
- **Rationale**: Query strings often carry tokens or personal data (signed URLs, reset links); logs and memory do not need them. Constitution's "never log secrets" becomes enforceable by one tested function.
- **Alternatives**: full URLs everywhere (leaks secrets into logs); hashing cache URLs (prevents reading entries back and complicates `clear_cache` by URL).
