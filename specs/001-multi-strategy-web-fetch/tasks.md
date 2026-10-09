# Tasks: Multi-Strategy Web Fetch MCP Server

**Input**: Design documents from `/specs/001-multi-strategy-web-fetch/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md, quickstart.md

**Tests**: REQUIRED. The project constitution (Principle I, non-negotiable) mandates automated tests for every feature. Test tasks come before the implementation they cover and must fail first.

**Organization**: Tasks are grouped by user story so each can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 to US4, mapping to the user stories in spec.md
- Paths follow the single-project layout in plan.md (`src/webfetch2000/`, `tests/`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and tooling

- [X] T001 Create `pyproject.toml` with Python >=3.12, `uv` build config, console script `webfetch2000`, runtime deps (`mcp`, `httpx[http2]`, `playwright<1.63`, `camoufox`, `trafilatura`, `pypdf`, `platformdirs`, `pydantic`) and dev deps (`pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`)
- [X] T002 [P] Create package skeleton: `src/webfetch2000/__init__.py`, `src/webfetch2000/__main__.py` (stub), `src/webfetch2000/strategies/__init__.py`, and empty `tests/unit/`, `tests/contract/`, `tests/integration/`, `tests/browser/` directories with `__init__.py`
- [X] T003 [P] Configure `ruff`, `mypy` and pytest markers (`browser`, `slow`) in `pyproject.toml`; add `.gitignore` for Python, `.venv`, caches
- [X] T004 [P] Create shared test server fixture in `tests/conftest.py`: a local HTTP server with routes for a static page, a JS-injected page, a block/challenge page (200 status), a 403 page, a 429 page with `Retry-After`, a slow page, a redirecting page, a `text/markdown` page (honors `Accept`), a PDF, a JSON page and an image
- [X] T005 [P] Create a minimal `.github/workflows/ci.yml`: matrix `ubuntu-latest` and `macos-latest` running lint, types and the offline suite (`pytest -m "not browser"`), so every later change is tested on both platforms per the constitution; the browser suite and image jobs are added in Polish

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core pieces every user story depends on

**CRITICAL**: No user story work begins until this phase is complete

### Tests for the foundation (write first, must fail)

- [X] T006 [P] Unit tests for settings layering and validation in `tests/unit/test_config.py` (defaults, TOML file, `WEBFETCH_*` env, per-call precedence, invalid values exit with a stderr message) per FR-023
- [X] T007 [P] Unit tests for URL validation in `tests/unit/test_safety.py` (malformed, non-http schemes, loopback, private, link-local, IPv6, DNS resolving to private, redirect re-check, `allow_private_addresses` flag) per FR-014, SC-009
- [X] T008 [P] Unit tests for `redact_url` and stderr-only logging in `tests/unit/test_logging.py` (query strings, fragments and userinfo removed; nothing written to stdout) per FR-017
- [X] T009 [P] Unit tests for the SQLite store in `tests/unit/test_store.py` (schema creation, WAL mode, `schema_version` migration, unavailable or corrupted store yields a warning, not a crash) per FR-016
- [X] T010 [P] Unit tests for content detection in `tests/unit/test_detect.py` (error statuses, 200-status block and challenge pages, JS-required shells, text shorter than `min_content_chars`, `extra_block_markers`, 429/503 classified as deferred) per FR-003, FR-028
- [X] T011 [P] Unit tests for conversion in `tests/unit/test_convert.py` (HTML to markdown, PDF text extraction, JSON/XML/CSV/plain text wrapped as markdown, binary metadata-only, origin markdown passthrough) per FR-019, FR-026
- [X] T012 [P] Unit tests for the rate limiter in `tests/unit/test_ratelimit.py` (per-domain concurrency cap, token bucket and burst, 0 disables, queueing bounded by timeout, `Retry-After` parsing in seconds and HTTP-date capped at `max_retry_after_s`, cache hits do not consume tokens, redirect hops counted) per FR-027, FR-028, SC-014

### Implementation of the foundation

- [X] T013 Implement layered settings in `src/webfetch2000/config.py` (pydantic model with all settings from research.md decision 15, 17, 18, 19, 20 and the usability thresholds; TOML via `tomllib`; `WEBFETCH_` env; record each value's source)
- [X] T014 [P] Implement pydantic models in `src/webfetch2000/models.py`: `FetchRequest`, `FetchResult`, `Attempt` (outcomes `success`, `failed`, `skipped`, `unavailable`, `deferred`), error codes from the contract
- [X] T015 [P] Implement `src/webfetch2000/logging.py`: stderr-only structured logging and `redact_url()` as the only way URLs reach logs
- [X] T016 [P] Implement `src/webfetch2000/safety.py`: URL normalization, scheme check, DNS resolution and private-range blocking, reusable per redirect hop and by browser request interception
- [X] T017 Implement `src/webfetch2000/store.py`: per-user SQLite via `platformdirs`, WAL, `busy_timeout`, `outcomes`, `cache` and `meta` tables per data-model.md, migrations, graceful degradation when unavailable
- [X] T018 [P] Implement `src/webfetch2000/strategies/base.py`: `Strategy` protocol (name, cost, `available()`, `fetch()`), fetch outcome type carrying status, headers, body bytes, final URL and failure reason
- [X] T019 [P] Implement `src/webfetch2000/detect.py`: pure usability classification returning `ok`, `failed(reason)` or `deferred(retry_after)`
- [X] T020 [P] Implement `src/webfetch2000/convert.py`: HTML to markdown (`trafilatura`), PDF text (`pypdf`), text-type wrapping, binary metadata, origin-markdown passthrough, size-cap truncation helper that never alters raw output
- [X] T021 Implement `src/webfetch2000/ratelimit.py`: per-domain concurrency and token bucket, queueing bounded by timeout, `Retry-After` back-off helper

**Checkpoint**: Foundation ready; user stories can begin

---

## Phase 3: User Story 1 - Fetch a page with automatic escalation (Priority: P1) MVP

**Goal**: A single `fetch` call returns usable markdown from static, JS-rendered and protected pages by escalating HTTP, then Chromium, then Camoufox, with a full attempt log.

**Independent Test**: Fetch a static, a JS-rendered and a bot-protected test page; each returns usable content with the winning strategy reported; a page that defeats every strategy returns an error listing all attempts (quickstart scenarios 1 to 3, 10, 12, 21, 24).

### Tests for User Story 1 (write first, must fail)

- [X] T022 [P] [US1] Contract test for the `fetch` tool input and output schema and error shapes in `tests/contract/test_fetch_contract.py` per contracts/mcp-tools.md
- [X] T023 [P] [US1] HTTP strategy tests in `tests/integration/test_http_strategy.py` using `respx` and the local server (browser-like headers and `user_agent` override, `Accept: text/markdown` negotiation and origin passthrough with `origin_tokens` and `content_signals`, redirect hop safety and rate limiting, truncation at the size cap with a warning and `too_large` for unusable truncation, timeouts) per FR-026, SC-013
- [X] T024 [P] [US1] Router escalation tests with fake strategies in `tests/integration/test_router_escalation.py` (cheapest first, escalate on failure and on unusable 200 pages, attempt log with reasons, all-fail error per SC-007, `static page never launches a browser` per SC-005)
- [X] T025 [P] [US1] Back-off tests in `tests/integration/test_backoff.py` (429 with `Retry-After` waits then retries the same strategy, never escalates, not recorded as failure, `rate_limited` error after limit) per FR-028, SC-015
- [X] T026 [P] [US1] Degraded-mode tests in `tests/integration/test_degraded_mode.py` (browsers missing: HTTP still works and `warnings` lists unavailable strategies; store unavailable: fetch works with a warning) per FR-015, FR-016
- [X] T027 [P] [US1] Shutdown tests in `tests/integration/test_shutdown.py` (stdin EOF and SIGTERM with a browser open: browsers and store closed, no orphan processes, clean exit code; real-browser variant marked `browser`) per FR-018
- [X] T028 [P] [US1] Real-browser tests marked `browser` in `tests/browser/test_browser_strategy.py` (JS-rendered page, resource blocking, private-address interception, pages and contexts closed after use)
- [X] T029 [P] [US1] Real-browser tests marked `browser` in `tests/browser/test_stealth_strategy.py` (Camoufox launches, fetches the JS page, headless and `headed` options, cleanup on exit)

### Implementation for User Story 1

- [X] T030 [P] [US1] Implement the HTTP strategy in `src/webfetch2000/strategies/http.py` (`httpx` async, HTTP/2, streaming with size cap, manual redirects with safety and limiter per hop, browser-like identity, markdown negotiation)
- [X] T031 [P] [US1] Implement the Chromium strategy in `src/webfetch2000/strategies/browser.py` (lazy shared browser, isolated context per fetch, resource blocking, request interception for safety and limiter, semaphore, idle shutdown, availability check)
- [X] T032 [P] [US1] Implement the stealth strategy in `src/webfetch2000/strategies/stealth.py` (Camoufox via its Playwright API, headless by default, semaphore, same interception, availability check, cleanup)
- [X] T033 [US1] Implement the router in `src/webfetch2000/router.py` (ladder order, per-strategy timeout and bounded retries with backoff, usability check via `detect.py`, deferred handling, attempt log, structured all-fail error, resource release in `finally`)
- [X] T034 [US1] Implement the MCP server and `fetch` tool in `src/webfetch2000/server.py` and wire `src/webfetch2000/__main__.py` (stdio only, settings loaded at startup, tool description and schema per contract including the per-call `headed` and `negotiate_markdown` options)
- [X] T035 [US1] Pass the per-call `headed` option through `router.py` to the browser strategies (`browser.py`, `stealth.py`)
- [X] T036 [US1] Implement graceful shutdown in `src/webfetch2000/server.py` and `src/webfetch2000/__main__.py` (handle stdin EOF, SIGINT and SIGTERM; close browsers, pending requests and the store) per FR-018
- [X] T037 [US1] Add structured logging calls for strategy choice, attempts, duration and failure reason in `router.py` and the strategies (redacted URLs, no stdout)

**Checkpoint**: User Story 1 works end to end and is the MVP

---

## Phase 4: User Story 2 - Remember which strategy works best per site (Priority: P1)

**Goal**: Outcomes are recorded per domain (with path-prefix overrides) in the shared store and used to choose the starting strategy, including after restart and across instances.

**Independent Test**: Fetch a site that needs the heavier strategy twice; the second fetch skips the failed cheaper strategies and is faster; restart and repeat (quickstart 4, 5, 13).

### Tests for User Story 2 (write first, must fail)

- [X] T038 [P] [US2] Unit tests for scoring in `tests/unit/test_memory_scoring.py` (decayed counters, Laplace smoothing, cheapest-within-tolerance choice, minimum observations, unseen strategies default to ladder order) per FR-006
- [X] T039 [P] [US2] Unit tests for path-prefix overrides in `tests/unit/test_memory_overrides.py` (created after enough divergent observations, removed after convergence, requested-domain keying after redirects) per FR-020
- [X] T040 [P] [US2] Unit tests for re-probing in `tests/unit/test_memory_reprobe.py` (age-based and probabilistic re-test of cheaper strategies, memory recovers when a site changes) per FR-007
- [X] T041 [P] [US2] Integration tests in `tests/integration/test_memory_persistence.py` (second fetch starts with the remembered strategy, survives a new store connection, deferred outcomes are not recorded) per FR-005, SC-002, SC-003, SC-008
- [X] T042 [P] [US2] Multi-process test in `tests/integration/test_store_concurrency.py` (5 processes record outcomes concurrently, no lost increments, store readable) per FR-022, SC-010

### Implementation for User Story 2

- [X] T043 [US2] Implement `src/webfetch2000/memory.py` (atomic `UPDATE ... SET x = x + ?` outcome recording, time decay, scoring, path-prefix override lifecycle, re-probe policy, ranked order query)
- [X] T044 [US2] Integrate memory into `router.py` (start strategy from ranking, record every non-deferred outcome with duration, skip memory when the store is unavailable with a warning)
- [X] T045 [US2] Add memory decision logging (starting strategy, reason, re-probe) in `router.py` and `memory.py` using redacted domain and path only

**Checkpoint**: User Stories 1 and 2 both work independently

---

## Phase 5: User Story 3 - Avoid duplicate fetches with a result cache (Priority: P2)

**Goal**: Repeat requests are served from a shared, bounded cache honoring HTTP validators; identical in-flight requests share one fetch; callers can bypass or refresh.

**Independent Test**: Fetch a URL twice and see a cache hit with no network request; fetch with `refresh` and `bypass`; send two identical concurrent requests and see one network fetch (quickstart 6 to 8, 22).

### Tests for User Story 3 (write first, must fail)

- [X] T046 [P] [US3] Unit tests for the cache in `tests/unit/test_cache.py` (key includes URL, format and negotiation flag, TTL, `Cache-Control` max-age and `no-store`, LRU eviction to the size cap, expired entries kept for revalidation)
- [X] T047 [P] [US3] Integration tests in `tests/integration/test_cache_behavior.py` (hit under 100 ms with no network per SC-004, `refresh` and `bypass`, ETag and Last-Modified revalidation returns `revalidated`, errors and block pages never cached)
- [X] T048 [P] [US3] Single-flight tests in `tests/integration/test_singleflight.py` (two simultaneous identical requests cause one fetch and both get the result, distinct options do not coalesce, a failed leader propagates to followers) per FR-009

### Implementation for User Story 3

- [X] T049 [US3] Implement `src/webfetch2000/cache.py` (key derivation, store read and write, validators, expiry, LRU eviction, size cap, clear by URL, domain or all)
- [X] T050 [US3] Integrate cache and single-flight into `router.py` (modes `use`, `refresh`, `bypass`; conditional revalidation; coalescing map; cache hits and coalesced duplicates skip the rate limiter)
- [X] T051 [US3] Add cache hit, miss and revalidated logging with redacted URLs

**Checkpoint**: User Stories 1 to 3 work independently

---

## Phase 6: User Story 4 - Control output and strategy (Priority: P3)

**Goal**: Callers can pick output format and size, force a strategy, and inspect, reset or clear what the server has learned and cached; operators can see effective settings.

**Independent Test**: Fetch a long page as markdown and raw with a size cap and a forced strategy; run the inspection and clearing tools (quickstart 9, 11, 14 to 16, 25).

### Tests for User Story 4 (write first, must fail)

- [X] T052 [P] [US4] Contract tests for `site_memory`, `reset_memory`, `clear_cache`, `strategies` and `config` in `tests/contract/test_management_tools_contract.py` per contracts/mcp-tools.md
- [X] T053 [P] [US4] Integration tests for output control in `tests/integration/test_output_control.py` (markdown default, raw bytes unaltered, `max_chars` truncation marker and `total_chars` for markdown, `total_bytes` for raw, binary metadata-only, PDF and JSON handling) per FR-010, FR-019
- [X] T054 [P] [US4] Integration tests for forced strategy in `tests/integration/test_forced_strategy.py` (forced strategy used first, `fallback: false` stops after one failure, unavailable or disabled forced strategy returns `strategy_unavailable` with the reason and no substitution) per FR-011, FR-029
- [X] T055 [P] [US4] Integration tests for `config` tool and settings layering end to end in `tests/integration/test_config_tool.py` (source reported per value, invalid env exits with stderr message) per FR-023
- [X] T056 [P] [US4] Tests for the per-call `headed` override end to end in `tests/browser/test_headed_override.py` (marked `browser`; window opens for that call only, default stays headless)

### Implementation for User Story 4

- [X] T057 [US4] Implement output controls in `router.py` and `convert.py` (format selection, `max_chars` truncation for markdown, `total_chars`, raw passthrough capped only by `max_response_bytes` with `total_bytes`)
- [X] T058 [US4] Implement forced strategy, `fallback` flag, `enabled_strategies` and the `strategy_unavailable` error in `router.py`
- [X] T059 [P] [US4] Implement `site_memory` and `reset_memory` tools in `src/webfetch2000/tools_memory.py` using `memory.py`
- [X] T060 [P] [US4] Implement `clear_cache` and `strategies` tools in `src/webfetch2000/tools_cache.py` using `cache.py` and strategy availability
- [X] T061 [US4] Implement the `config` tool in `src/webfetch2000/tools_config.py` using the source tracking in `config.py`, then register the `tools_memory`, `tools_cache` and `tools_config` modules in `server.py`

**Checkpoint**: All four user stories independently functional

---

## Phase 7: Polish and Cross-Cutting Concerns

**Purpose**: Documentation, packaging, platform and container support, and system-level verification

- [X] T062 [P] Write `README.md`: install, MCP client registration, tool reference linking contracts/mcp-tools.md, configuration table, headed vs headless, macOS and Linux notes, limitations (in-process rate limits, public pages only, content is unmarked)
- [X] T063 [P] Add tool descriptions and docstrings for every MCP tool and a `CHANGELOG.md`
- [X] T064 [P] Create `Dockerfile` with `full` and `slim` targets (non-root, `tini`, `xvfb`, Chromium via `playwright install --with-deps`, Camoufox fetched at build, `/data` volume, `WEBFETCH_DATA_DIR`, `no_sandbox` on in image) per research decision 17
- [X] T065 [P] Create `compose.yaml` (named volume, `shm_size: 1gb`, stdio usage example) and `.dockerignore`
- [X] T066 [P] Extend `.github/workflows/ci.yml` (created in T005): add the `browser` suite (installing browsers) on `ubuntu-latest` and `macos-latest`, plus an image build and a containerized smoke fetch per FR-024, SC-011
- [X] T067 [P] Add an opt-in live benchmark harness in `tests/benchmark/run_benchmark.py` (marked `live`, excluded from CI) over a small versioned URL list of static, JS-rendered and protected pages; reports usable-content rate (SC-001), first-try success after warm-up (SC-002) and repeat-fetch speedup (SC-003); results recorded in `specs/001-multi-strategy-web-fetch/benchmark.md`
- [X] T068 [P] Add a load test in `tests/integration/test_load.py` (50 concurrent requests: resident memory under 1 GB and back within 20% of baseline within 60 s after the load ends, per-domain in-flight and rate limits respected per SC-014, no leftover browser processes per SC-006) marked `slow`
- [X] T069 [P] Add a cache latency test asserting under 100 ms hits (SC-004) and a platform path test confirming `platformdirs` locations on macOS and Linux in `tests/unit/test_paths.py`
- [X] T070 Verify Camoufox arm64 Linux availability and virtual-display headless mode against current docs; record the result in research.md and make the image report the stealth strategy unavailable if missing
- [X] T071 Update quickstart.md with scenarios for URL redaction, `user_agent` override, the forced-but-unavailable strategy error, graceful shutdown cleanup and oversized-body truncation; run all quickstart scenarios on macOS and Linux and fix gaps
- [X] T072 Security review pass: SSRF paths (redirects, DNS rebinding, browser subresources), log redaction, cache contents, container hardening
- [X] T073 Final constitution check against plan.md and spec success criteria SC-001 to SC-015

---

## Dependencies and Execution Order

- **Phase 1 (Setup)** has no dependencies.
- **Phase 2 (Foundational)** depends on Setup and blocks every user story. Within it, tests first; `config.py`, `models.py`, `logging.py`, `safety.py`, `store.py`, `base.py`, `detect.py`, `convert.py` are mostly parallel; `ratelimit.py` depends on `config.py`.
- **User Story 1 (P1, MVP)** depends on Phase 2 only. The three strategies are parallel; `router.py` depends on them; `server.py` depends on `router.py`.
- **User Story 2 (P1)** depends on Phase 2 and extends the US1 router (memory is optional there, so US2 can be built against fakes before US1 completes).
- **User Story 3 (P2)** depends on Phase 2 and extends the US1 router; independent of US2.
- **User Story 4 (P3)** depends on Phase 2; tool wiring needs `memory.py` (US2) and `cache.py` (US3) for the management tools, while output control and forced strategy need only US1.
- **Polish** depends on the stories it documents or verifies; Docker and the extended CI can start once US1 runs; the minimal CI from Setup runs from the start.

### Parallel opportunities

- All foundation test tasks run in parallel; after them, most foundation modules are parallel.
- US1: the three strategy tasks and their tests are parallel.
- US2 and US3 can proceed in parallel after US1's router exists, touching `memory.py` and `cache.py` separately (both edit `router.py`, so integrate sequentially).
- US4 tool tasks for memory, cache and config are parallel.

## Implementation Strategy

1. **MVP**: Phases 1, 2 and 3 (User Story 1). Validate with quickstart scenarios 1 to 3, 10, 12, 21, 24.
2. **Increment 1**: add User Story 2 (memory), validate scenarios 4, 5, 13.
3. **Increment 2**: add User Story 3 (cache), validate scenarios 6 to 8, 22.
4. **Increment 3**: add User Story 4 (controls and management tools).
5. **Finish**: Polish phase, including Docker, CI on both platforms and the verification items.

Each increment ends with the full offline suite passing, per the constitution.
