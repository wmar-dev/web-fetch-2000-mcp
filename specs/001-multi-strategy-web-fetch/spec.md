# Feature Specification: Multi-Strategy Web Fetch MCP Server

**Feature Branch**: `001-multi-strategy-web-fetch`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "Make an MCP server that can fetch content from the web using a variety of tools, that also has memory on which tool is the best. From python requests to playwright with stealth abilities."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fetch a page with automatic escalation (Priority: P1)

An AI assistant (via an MCP client) asks the server to fetch a URL. The server tries the cheapest fetch strategy first (a plain HTTP request), and if that fails or returns unusable content (blocked, empty shell, challenge page), it automatically escalates to progressively more capable strategies: a real browser that renders JavaScript, then a browser with anti-detection ("stealth") measures. The assistant receives clean, usable content plus a note on which strategy produced it.

**Why this priority**: This is the core value. Without reliable escalation the server is no better than a single fetch tool.

**Independent Test**: Request three kinds of URLs (a static page, a JavaScript-rendered page, a bot-protected page) and verify usable content is returned for each, with the winning strategy reported.

**Acceptance Scenarios**:

1. **Given** a static page, **When** the assistant fetches it, **Then** the content is returned using the cheapest strategy and no browser is launched.
2. **Given** a page whose content only appears after JavaScript runs, **When** the assistant fetches it, **Then** the server escalates to a rendering strategy and returns the rendered content.
3. **Given** a page that blocks simple clients and standard browsers, **When** the assistant fetches it, **Then** the server escalates to the stealth strategy and returns the content if it can be obtained.
4. **Given** every strategy fails, **When** the assistant fetches the URL, **Then** it receives a structured error listing each strategy tried and why it failed.

---

### User Story 2 - Remember which strategy works best per site (Priority: P1)

The server keeps a persistent record of which strategy succeeded or failed for each site (domain). On later requests to the same site it starts with the strategy most likely to succeed instead of re-walking the escalation chain, and it favors cheaper strategies when outcomes are equal.

**Why this priority**: The user explicitly asked for memory of the best tool. It also saves time and resources on repeat visits.

**Independent Test**: Fetch a site that requires the stealth strategy twice; the second fetch skips the failed cheaper strategies and completes faster, and the decision is visible in the response.

**Acceptance Scenarios**:

1. **Given** a site where a plain request previously failed and the browser strategy succeeded, **When** the site is fetched again, **Then** the browser strategy is tried first.
2. **Given** a remembered strategy that now fails, **When** the site is fetched, **Then** the server falls back through the remaining strategies and updates its memory.
3. **Given** the server is restarted, **When** a previously seen site is fetched, **Then** the earlier learning is still applied.
4. **Given** a remembered preference is old, **When** the site is fetched, **Then** the server occasionally re-tests cheaper strategies so memory does not become permanently stale.

---

### User Story 3 - Avoid duplicate fetches with a result cache (Priority: P2)

When the same URL is requested again within a freshness window, the server returns the stored result instead of fetching again. Identical requests arriving at the same time share one fetch. The caller can force a refresh.

**Why this priority**: Saves bandwidth, time and load on target sites; required by the project constitution.

**Independent Test**: Fetch the same URL twice and confirm the second response is marked as cached and no network request occurs; fetch with refresh and confirm a new request occurs.

**Acceptance Scenarios**:

1. **Given** a recently fetched URL, **When** it is requested again, **Then** the cached content is returned and flagged as cached.
2. **Given** two simultaneous requests for the same URL, **When** both are processed, **Then** only one network fetch occurs.
3. **Given** the caller asks to bypass the cache, **When** the URL is requested, **Then** a fresh fetch is performed and the cache is updated.

---

### User Story 4 - Control output and strategy (Priority: P3)

The caller can choose the output form (clean main text, markdown, or raw), cap the output size, force or exclude a specific strategy, and inspect what the server has learned about a site.

**Why this priority**: Gives power users control and keeps responses small for token efficiency, but the server is useful without it.

**Independent Test**: Request the same page as markdown with a size cap and with a forced strategy; verify the format, truncation notice, and strategy used.

**Acceptance Scenarios**:

1. **Given** a long page, **When** the caller sets a maximum size, **Then** the output is truncated and clearly marked as truncated.
2. **Given** the caller forces a specific strategy, **When** it fails, **Then** no other strategy is tried unless the caller allows fallback.
3. **Given** a site with history, **When** the caller asks for its strategy statistics, **Then** success rates and last-used strategy are shown.

---

### Edge Cases

- URL is malformed, uses an unsupported scheme, or points to a local or private network address (must be refused).
- Page returns a 200 status but is a CAPTCHA, login wall or JavaScript-required placeholder (must count as a failure and escalate).
- Redirect loops, very slow servers, and responses larger than the size limit.
- Non-HTML content (PDF, JSON, images, binary).
- The browser components are not installed or fail to start (cheaper strategies must still work and the gap must be reported).
- Memory store is missing, corrupted or locked (server continues without memory and reports a warning).
- Many concurrent requests (browser usage must be bounded).
- A site changes its protection so a previously best strategy stops working.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST expose a fetch capability over the Model Context Protocol that accepts a URL and returns the page content.
- **FR-002**: The server MUST support at least three strategies ordered by cost: plain HTTP request, JavaScript-rendering browser, and browser with stealth/anti-detection measures.
- **FR-003**: The server MUST automatically escalate to the next strategy when one fails or returns unusable content, including block pages, challenge pages and empty content shells.
- **FR-004**: The server MUST report which strategy produced the result, which were attempted, and why each failed.
- **FR-005**: The server MUST persistently record per-site strategy outcomes (success, failure, duration) across restarts.
- **FR-006**: The server MUST use recorded outcomes to choose the starting strategy for a site, preferring the cheapest strategy among those with comparable success.
- **FR-007**: The server MUST periodically re-test cheaper strategies for sites with remembered preferences so memory can recover from changes.
- **FR-008**: The server MUST cache fetched results with a freshness window, honor the caller's request to bypass or refresh, and bound cache size.
- **FR-009**: The server MUST coalesce simultaneous identical requests into a single fetch.
- **FR-010**: The server MUST support output as cleaned main text, markdown, or raw content, and a caller-specified maximum output size with a visible truncation marker.
- **FR-011**: The server MUST allow the caller to force a strategy and to enable or disable fallback.
- **FR-012**: The server MUST provide a way to view and reset what it has learned for a site.
- **FR-013**: The server MUST enforce timeouts, response-size limits, bounded retries with backoff, and a bounded number of concurrent browser sessions.
- **FR-014**: The server MUST reject malformed URLs, non-web schemes, and local or private network addresses by default.
- **FR-015**: The server MUST keep working with reduced strategies if browser components are unavailable, and tell the caller which strategies were unavailable.
- **FR-016**: The server MUST continue operating without memory or cache if their storage is unavailable, and surface a warning.
- **FR-017**: The server MUST log strategy choice, cache hit or miss, duration and failure reasons without writing to the protocol channel and without logging secrets.
- **FR-018**: The server MUST release browser resources promptly after use and on shutdown.

### Key Entities

- **Fetch Request**: URL plus options (output format, size cap, forced strategy, fallback allowed, cache mode).
- **Strategy**: A named way of retrieving a page, with a relative cost, availability status and failure signals.
- **Fetch Result**: Content, format, final URL, status, strategy used, strategies attempted with failure reasons, cache status, truncation flag, duration.
- **Site Memory**: Per-site record of each strategy's recent successes, failures, durations and last-tested time; yields a ranked strategy order.
- **Cache Entry**: A stored result with its request key, fetch time and freshness window.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a benchmark set covering static, JavaScript-rendered and bot-protected pages, at least 90% of fetchable pages return usable content without the caller choosing a strategy.
- **SC-002**: For sites visited before, the first strategy tried succeeds at least 90% of the time.
- **SC-003**: Repeat fetches of a site that needs a heavier strategy are at least 50% faster than the first fetch because failed cheaper strategies are skipped.
- **SC-004**: A repeat request within the freshness window is answered in under 100 milliseconds without any network access.
- **SC-005**: A static page is fetched without launching a browser in 100% of cases.
- **SC-006**: Server memory use stays bounded under 50 concurrent requests, with no leftover browser processes after the load ends.
- **SC-007**: When all strategies fail, 100% of error responses name every strategy tried and its reason for failing.
- **SC-008**: Learned site knowledge survives a server restart in 100% of tested cases.
- **SC-009**: Requests to local or private network addresses are refused in 100% of tested cases.

## Assumptions

- The primary users are AI assistants connecting through MCP clients, operated by a developer who installs the server locally.
- The server is a single-user, local tool; multi-tenant hosting and authentication are out of scope.
- Sites are identified for memory purposes by domain.
- Sites requiring a login, solving of CAPTCHAs, or paid access are out of scope; challenge pages are detected and reported rather than solved.
- Stealth measures are intended for legitimate access to publicly available content; respecting site terms and rate limits remains the operator's responsibility.
- Default cache freshness is minutes to hours and is configurable; memory is retained until reset.
- Browser components are an optional installation step; the plain HTTP strategy works without them.
