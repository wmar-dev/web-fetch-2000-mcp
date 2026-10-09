# Implementation Plan: Multi-Strategy Web Fetch MCP Server

**Branch**: `001-multi-strategy-web-fetch` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-multi-strategy-web-fetch/spec.md`

## Summary

A local MCP server (stdio) exposing a `fetch` tool that retrieves web content through an ordered ladder of strategies: plain async HTTP, a Playwright-driven Chromium, and Camoufox (stealth Firefox). A router picks the starting rung from persistent per-domain (and path-prefix) memory, escalates on failure or unusable content, and records outcomes. Results are cached and in-flight duplicates coalesced. Memory and cache live in one per-user SQLite database (WAL) shared safely by all server instances. Behavior is configurable through a validated settings layer. Output is markdown by default or raw bytes-as-received. See [research.md](research.md) for the decisions behind this.

## Technical Context

**Language/Version**: Python 3.12+ (developed on 3.14; Camoufox and MCP SDK require >=3.10)

**Primary Dependencies**: `mcp` (official SDK, FastMCP), `httpx` (async HTTP), `playwright` (pinned `<1.63`, required by Camoufox), `camoufox`, `trafilatura` (HTML to markdown), `pypdf` (PDF text), `platformdirs`, `pydantic`

**Storage**: SQLite file in the per-user data dir (stdlib `sqlite3`, WAL mode) holding strategy memory and the result cache

**Testing**: `pytest`, `pytest-asyncio`, `respx` (httpx mocking), a local in-process HTTP test server for browser tiers; browser tests marked `browser` and skippable

**Target Platform**: macOS and Linux (both first-class, verified by a CI matrix on `ubuntu-latest` and `macos-latest`), run locally by an MCP client over stdio; Windows out of scope

**Project Type**: single project (library plus MCP server entry point), also distributed as a Docker image (`full` and `slim` targets)

**Performance Goals**: cache hit under 100 ms (SC-004); no browser launched for static pages (SC-005); repeat visits skip failed tiers (SC-003)

**Constraints**: both browser tiers headless by default (configurable, optional per-call `headed`); settings layered defaults < TOML file < `WEBFETCH_*` env < per-call arguments, see research.md decision 15; default 30 s per-strategy timeout, 10 MB response cap, max 2 concurrent browser pages and 1 stealth browser by default, bounded retries; stdout reserved for MCP protocol

**Scale/Scope**: single user, up to ~50 concurrent requests (SC-006), thousands of domains, cache capped (default 200 MB, LRU eviction)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How the plan satisfies it |
|-----------|--------|---------------------------|
| I. Well Tested | Pass | pytest unit, contract and integration suites; network mocked or served by a local test server; browser tests separately marked; test tasks precede implementation tasks |
| II. Well Documented | Pass | Tool contract in [contracts/mcp-tools.md](contracts/mcp-tools.md), README and [quickstart.md](quickstart.md) delivered with the code |
| III. Resource Efficient | Pass | Cheapest-first routing, timeouts, size caps, browser concurrency semaphores, lazy browser launch with idle shutdown, markdown extraction by default |
| IV. Fallback Mechanisms | Pass | Ordered ladder with explicit failure classification; structured attempt log in every error; degraded mode when browsers or the store are unavailable |
| Containers (FR-025) | Pass | Multi-stage Dockerfile with `full` and `slim` targets, non-root, `tini`, volume at `/data`, image smoke-tested in CI |
| Cross-platform (FR-024) | Pass | Platform-neutral libraries, CI matrix on macOS and Linux, platform notes in README and quickstart |
| III. Resource Efficient (markdown) | Pass | Site-provided markdown avoids HTML conversion and cuts tokens (FR-026) |
| III. Resource Efficient (rate limits) | Pass | Per-domain concurrency and rate limits, 429/503 back-off without escalation (FR-027, FR-028) |
| V. Memory / No Duplicate Work | Pass | SQLite strategy memory, HTTP-validator-aware cache, single-flight coalescing, shared across instances |

Re-check after Phase 1 design: still passes; no complexity violations to track.

## Project Structure

### Documentation (this feature)

```text
specs/001-multi-strategy-web-fetch/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── mcp-tools.md
├── checklists/
│   └── requirements.md
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml
README.md
src/webfetch2000/
├── __main__.py          # entry point: runs the stdio server
├── server.py            # MCP tool definitions, wiring
├── config.py            # layered settings: defaults, TOML file, WEBFETCH_ env, validated at startup
├── models.py            # pydantic: FetchRequest, FetchResult, Attempt, errors
├── router.py            # strategy ordering, escalation loop, single-flight
├── memory.py            # site memory: scoring, path-prefix overrides, re-probing
├── cache.py             # result cache, validators, eviction
├── store.py             # SQLite connection, schema, migrations, WAL
├── safety.py            # URL validation, private-network blocking
├── ratelimit.py         # per-domain concurrency cap, token bucket, Retry-After back-off
├── detect.py            # unusable-content / block / challenge detection
├── convert.py           # HTML, PDF, text to markdown; binary metadata
├── strategies/
│   ├── base.py          # Strategy protocol, availability, result type
│   ├── http.py          # httpx tier; negotiates Accept: text/markdown
│   ├── browser.py       # Playwright Chromium tier
│   └── stealth.py       # Camoufox tier
└── logging.py           # stderr-only structured logging

tests/
├── unit/                # memory scoring, detect, convert, safety, cache
├── contract/            # MCP tool schemas and error shapes
├── integration/         # router with fake and local-server strategies
└── browser/             # marked `browser`: real Playwright and Camoufox

Dockerfile               # targets: full (default), slim (HTTP only)
compose.yaml             # named volume, shm_size, stdio usage example
.dockerignore

.github/workflows/ci.yml # matrix: ubuntu-latest, macos-latest; offline and browser suites; also builds the images and runs a containerized smoke fetch
```

**Structure Decision**: Single Python package under `src/` with one module per responsibility; strategies are pluggable behind a small protocol so the router and memory are testable with fakes.

## Complexity Tracking

No constitution violations to justify.
