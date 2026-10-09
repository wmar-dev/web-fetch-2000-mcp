# Data Model

Storage is one SQLite database (WAL) in the per-user data directory. Types below are logical; see [research.md](research.md) for decisions.

## FetchRequest (input, not stored)

| Field | Type | Default | Rules |
|-------|------|---------|-------|
| url | string | required | http/https only; normalized; must pass safety check |
| format | `markdown` \| `raw` | `markdown` | |
| max_chars | int | 50000 | 1 to 2,000,000; applies to markdown output only; raw output is capped by the `max_response_bytes` setting |
| strategy | `http` \| `browser` \| `stealth` \| `auto` | `auto` | forces the first strategy |
| fallback | bool | true | when a strategy is forced, false means no escalation |
| cache | `use` \| `refresh` \| `bypass` | `use` | `refresh` fetches and overwrites; `bypass` fetches without reading or writing |
| timeout_s | int | 30 | per-strategy cap, max 120 |
| negotiate_markdown | bool | setting (true) | per-call override of whether the HTTP tier asks for `text/markdown` |
| headed | bool | false | run browser tiers with a visible window (debugging); ignored by `http` |

## FetchResult (output, not stored directly)

| Field | Notes |
|-------|-------|
| url, final_url, status | after redirects |
| content_type, format | what was returned |
| content | markdown text, raw text, or empty for binary metadata-only |
| truncated | bool, with `total_chars` when known |
| strategy_used | the winning strategy |
| attempts[] | Attempt entries in order |
| cache | `hit`, `miss`, `revalidated`, `bypassed` |
| duration_ms | total |
| markdown_source | `origin` (site served markdown) or `converted` (we converted); absent for raw or binary |
| origin_tokens | token estimate supplied by the site, when present |
| content_signals | content-usage signals supplied by the site (e.g. `ai-input=yes`), when present |
| warnings[] | e.g. memory unavailable, browser unavailable |

## Attempt

`strategy`, `outcome` (`success` \| `failed` \| `skipped` \| `unavailable` \| `deferred`), `reason` (e.g. `http_403`, `rate_limited`, `challenge_detected`, `empty_content`, `timeout`, `browser_not_installed`), `duration_ms`.

`deferred` means the site asked us to back off (429 or 503); it is not recorded as a failure in site memory and does not trigger escalation. `waited_ms` records time spent queued or backing off.

## StrategyOutcome (table `outcomes`)

Per site and strategy, decayed counters.

| Column | Notes |
|--------|-------|
| domain | registrable host, lowercase |
| path_prefix | empty string for the domain default, else first path segment(s) |
| strategy | `http`, `browser`, `stealth` |
| successes, failures | decayed real numbers |
| mean_duration_ms | exponential moving average |
| observations | integer count since reset |
| last_attempt_at, last_success_at | timestamps |
| updated_at | timestamp used for decay |

Primary key: (domain, path_prefix, strategy). Updates use atomic SQL expressions so concurrent instances do not lose increments.

**Derived**: a ranked strategy order per (domain, path_prefix), computed on read by the scoring rule in research decision 6.

**Lifecycle**: a path-prefix row set is created when the prefix diverges from the domain default and deleted after convergence; `reset` removes all rows for a domain.

## CacheEntry (table `cache`)

| Column | Notes |
|--------|-------|
| key | hash of normalized URL, output-affecting options and whether markdown negotiation was used |
| url, final_url, status, content_type | |
| body_markdown, body_raw | raw stored only within the size cap |
| etag, last_modified | for conditional revalidation |
| fetched_at, expires_at | freshness window from TTL and Cache-Control |
| size_bytes, last_accessed_at | for LRU eviction |
| strategy_used | |

**Privacy**: strategy memory and logs never contain query strings or fragments (domain and path prefix only). The cache is the only place full URLs are kept, because the key requires them; entries expire and can be cleared on request.

**Rules**: entries with `no-store` are never written; total size is capped and the least recently accessed entries are evicted first; expired entries with validators are revalidated before refetching.

## StoreMeta (table `meta`)

`schema_version` for migrations, and creation time.

## State transitions

- Strategy availability: `unknown` to `available` or `unavailable` (browser binaries missing), re-checked at most once per process start.
- Site memory: `unseen` (ladder order) to `learning` (fewer than 2 observations per strategy) to `ranked`, with periodic re-probing back through `learning` for cheaper tiers.
