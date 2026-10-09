# Feature Specification: Multi-Strategy Web Fetch MCP Server

**Feature Branch**: `001-multi-strategy-web-fetch`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "Make an MCP server that can fetch content from the web using a variety of tools, that also has memory on which tool is the best. From python requests to playwright with stealth abilities."

## Clarifications

### Session 2026-10-08

- Q: What does the stealth strategy cover? → A: Fingerprint and behavior masking only, provided by Camoufox (user-specified engine); no CAPTCHA solving and no proxy support.
- Q: What output formats are offered for fetched content? → A: Markdown (default, best for assistants) and raw original data as received.
- Q: Which content types are supported? → A: Markdown for HTML, PDF (text extracted) and text types (JSON, XML, CSV, plain text); raw available for any type; binaries such as images return metadata only unless raw is requested.
- Q: At what granularity is strategy memory keyed? → A: Domain default, plus a learned override for a path prefix when its results consistently differ from the domain default.
- Q: Where are memory and cache stored, and who shares them? → A: One per-user store shared by every client and project, for both strategy memory and cached results. Cached content expires and can be cleared on request.
- Q: How is the shared store handled when several server instances run at once? → A: Instances safely share and merge updates with no lost learning or corruption; a momentarily stale read is acceptable.
- Q: Does the server honor robots.txt or pace requests to sites? → A: No robots.txt handling. It applies per-domain rate limiting (a cap on concurrent requests and on request rate per domain), and treats 429 and 503 as back-off signals instead of escalating to heavier strategies.
- Q: Is a request limited to one URL, or are batch, crawling or search in scope? → A: One URL per call. Crawling, link-following, search and batch fetch are out of scope for v1.
- Q: How is fetched content presented with respect to untrusted or injected instructions? → A: Returned as-is with no marking, filtering or scanning; treating the content as untrusted is up to the client.
- Q: How is content judged unusable so the server escalates? → A: By HTTP status, a minimum amount of extracted text (default 200 characters), and known block or challenge markers; thresholds are configurable.
- Q: What happens when a caller forces a strategy that is unavailable? → A: The server returns a strategy-unavailable error stating why (not installed or disabled) and does not substitute another strategy.
- Q: Is there an overall time limit on a request, beyond per-strategy timeouts? → A: No. Only per-strategy timeouts apply; total time is bounded by the strategy ladder, retries and back-off.
- Q: After a redirect, which domain are memory and rate limits applied to? → A: Strategy memory is recorded against the requested domain. Per-domain rate limits apply to every domain actually contacted, including redirect hops.
- Q: What identity does the plain HTTP strategy present to sites? → A: A browser-like identity (a current Chrome user agent and typical headers) in every strategy, overridable by a setting.
- Q: What URL detail is written to logs and strategy memory? → A: Domain and path only, with query strings and fragments removed. The cache keeps full URLs (required for correct keys) with expiry and clear-on-request.
- Q: Can callers pass cookies or credentials with a request? → A: No. v1 fetches public pages only; there is no per-call way to supply cookies, authorization headers or other credentials.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fetch a page with automatic escalation (Priority: P1)

An AI assistant (via an MCP client) asks the server to fetch a URL. The server tries the cheapest fetch strategy first (a plain HTTP request), and if that fails or returns unusable content (blocked, empty shell, challenge page), it automatically escalates to progressively more capable strategies: a real browser that renders JavaScript, then a browser with anti-detection ("stealth") measures. The assistant receives clean, usable content plus a note on which strategy produced it.

**Why this priority**: This is the core value. Without reliable escalation the server is no better than a single fetch tool.

**Independent Test**: Request three kinds of URLs (a static page, a JavaScript-rendered page, a bot-protected page) and verify usable content is returned for each, with the winning strategy reported.

**Acceptance Scenarios**:

1. **Given** a static page, **When** the assistant fetches it, **Then** the content is returned using the cheapest strategy and no browser is launched.
2. **Given** a page whose content only appears after JavaScript runs, **When** the assistant fetches it, **Then** the server escalates to a rendering strategy and returns the rendered content.
3. **Given** a page that blocks simple clients and standard browsers, **When** the assistant fetches it, **Then** the server escalates to the stealth strategy and returns the content if it can be obtained.
4. **Given** a site that can serve markdown directly (for example through Cloudflare's Markdown for Agents), **When** the assistant fetches it, **Then** the server asks for markdown, uses the site's own markdown as-is instead of converting HTML, and reports that the markdown came from the origin.
5. **Given** every strategy fails, **When** the assistant fetches the URL, **Then** it receives a structured error listing each strategy tried and why it failed.

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

The caller can choose the output form (markdown by default, or the original raw data), cap the output size, force a specific strategy, and inspect what the server has learned about a site.

**Why this priority**: Gives power users control and keeps responses small for token efficiency, but the server is useful without it.

**Independent Test**: Request the same page as markdown and as raw with a size cap and with a forced strategy; verify the format, truncation notice, and strategy used.

**Acceptance Scenarios**:

1. **Given** a long page, **When** the caller sets a maximum size, **Then** the output is truncated and clearly marked as truncated.
2. **Given** the caller forces a specific strategy, **When** it fails, **Then** no other strategy is tried unless the caller allows fallback.
3. **Given** a site with history, **When** the caller asks for its strategy statistics, **Then** success rates and last-used strategy are shown.

---

### Edge Cases

- URL is malformed, uses an unsupported scheme, or points to a local or private network address (must be refused).
- Page returns a 200 status but is a CAPTCHA, login wall or JavaScript-required placeholder (must count as a failure and escalate).
- Redirect loops, very slow servers, and responses larger than the size limit (truncated with a warning; too-large error only when truncation is unusable).
- Non-HTML content: PDFs are text-extracted, text types are converted to markdown, and binaries return metadata only unless raw is requested.
- The browser components are not installed or fail to start (cheaper strategies must still work and the gap must be reported).
- Memory store is missing, corrupted or locked (server continues without memory and reports a warning).
- Many concurrent requests (browser usage must be bounded).
- Several server instances read and write the shared store at the same time.
- A site answers 429 or 503 with a retry delay (the server waits within its limits and does not escalate to a heavier strategy because of it).
- Many requests target the same domain at once (they queue behind the per-domain limits).
- A site changes its protection so a previously best strategy stops working.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST expose a fetch capability over the Model Context Protocol that accepts a URL and returns the page content.
- **FR-002**: The server MUST support at least three strategies ordered by cost: plain HTTP request, JavaScript-rendering browser, and a stealth browser that masks automation signals and browser fingerprint (using Camoufox, as specified by the user).
- **FR-003**: The server MUST automatically escalate to the next strategy when one fails or returns unusable content, including block pages, challenge pages and empty content shells. Content is unusable when the HTTP status is an error (other than a back-off signal, see FR-028), when the extracted text is below a configurable minimum (default 200 characters), or when known block or challenge markers are present.
- **FR-004**: The server MUST report which strategy produced the result, which were attempted, and why each failed.
- **FR-005**: The server MUST persistently record per-site strategy outcomes (success, failure, duration) across restarts.
- **FR-006**: The server MUST use recorded outcomes to choose the starting strategy for a site (using a path-prefix override when one has been learned, otherwise the domain default), preferring the cheapest strategy among those with comparable success.
- **FR-007**: The server MUST periodically re-test cheaper strategies for sites with remembered preferences so memory can recover from changes (default intervals and thresholds are in research.md, decision 6).
- **FR-008**: The server MUST cache fetched results with a freshness window, honor the caller's request to bypass or refresh, and bound cache size.
- **FR-009**: The server MUST coalesce simultaneous identical requests into a single fetch.
- **FR-010**: The server MUST return content as markdown by default, or as the original data exactly as received when the caller requests raw output, and MUST support a caller-specified maximum output size with a visible truncation marker (raw output is truncated at the size limit, never altered).
- **FR-011**: The server MUST allow the caller to force a strategy and to enable or disable fallback.
- **FR-012**: The server MUST provide a way to view and reset what it has learned for a site.
- **FR-013**: The server MUST enforce timeouts, response-size limits, bounded retries with backoff, and a bounded number of concurrent browser sessions. A response body larger than the size limit MUST be truncated at the limit and flagged with a warning, not rejected, unless truncation cannot yield usable output (for example a cut-off PDF), in which case a too-large error is returned.
- **FR-014**: The server MUST reject malformed URLs, non-web schemes, and local or private network addresses by default.
- **FR-015**: The server MUST keep working with reduced strategies if browser components are unavailable, and tell the caller which strategies were unavailable.
- **FR-016**: The server MUST continue operating without memory or cache if their storage is unavailable, and surface a warning.
- **FR-017**: The server MUST log strategy choice, cache hit or miss, duration and failure reasons without writing to the protocol channel and without logging secrets; URLs in logs and in strategy memory MUST omit query strings and fragments.
- **FR-018**: The server MUST release browser resources promptly after use and on shutdown.
- **FR-019**: The server MUST convert HTML, PDF (text extraction) and text-based types (JSON, XML, CSV, plain text) to markdown, serve any content type as raw on request, and return metadata only (type, size, final URL) for binaries such as images when raw is not requested.
- **FR-020**: The server MUST create a path-prefix override only after results for that prefix consistently differ from the domain default (default thresholds in research.md, decision 6), and remove it when they converge again.
- **FR-021**: The server MUST keep strategy memory and cached results in a single per-user store shared by all clients and projects, and MUST let the caller clear the cache, or all learned data, on request.
- **FR-022**: The server MUST allow several instances to use the shared store concurrently without corrupting it or losing recorded outcomes; a momentarily stale read is acceptable.
- **FR-023**: The server MUST be configurable (limits, concurrency, browser visibility, enabled strategies, cache and memory behavior, safety lists) through a settings file and environment variables, with per-call options taking precedence, and MUST reject invalid settings at startup with a clear message.
- **FR-024**: The server MUST run with identical behavior on macOS and Linux, including all three strategies, the shared store, and configuration, with platform differences confined to installation steps.
- **FR-025**: The server MUST be runnable as a container image that provides all three strategies out of the box, communicates over standard input and output, keeps its memory and cache on a mountable volume so they persist across container runs, and runs as a non-root user.
- **FR-026**: The server MUST ask sites for markdown when using the plain HTTP strategy, use markdown the site provides directly without re-converting it, report whether the markdown came from the origin or was converted, and surface any token estimate and content-usage signals the site supplies.
- **FR-027**: The server MUST limit concurrent requests and request rate per domain across all strategies (counting every domain actually contacted, including redirect hops), with configurable defaults, queueing excess requests up to the caller's timeout; cache hits and coalesced duplicates MUST NOT count against the limits.
- **FR-028**: The server MUST treat 429 and 503 responses as back-off signals, honoring a server-supplied retry delay up to a configured maximum, MUST NOT count them against a strategy's recorded success, and MUST NOT escalate to a heavier strategy solely because of them.
- **FR-029**: When the caller forces a strategy that is unavailable (not installed or disabled in settings), the server MUST return a strategy-unavailable error that states the reason and MUST NOT substitute another strategy.

### Key Entities

- **Fetch Request**: URL plus options (output format, size cap, forced strategy, fallback allowed, cache mode, per-strategy timeout, visible-browser flag, markdown-negotiation override).
- **Strategy**: A named way of retrieving a page, with a relative cost, availability status and failure signals.
- **Fetch Result**: Content, format, final URL, status, strategy used, strategies attempted with failure reasons, cache status, truncation flag, whether markdown came from the site or was converted, any site-supplied token estimate and content-usage signals, time spent queued or backing off, duration, warnings.
- **Site Memory**: Per-domain record (with optional path-prefix overrides) of each strategy's recent successes, failures, durations and last-tested time; yields a ranked strategy order.
- **Cache Entry**: A stored result with its request key, fetch time and freshness window.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a benchmark set covering static, JavaScript-rendered and bot-protected pages, at least 90% of fetchable pages return usable content without the caller choosing a strategy.
- **SC-002**: For sites visited before, the first strategy tried succeeds at least 90% of the time.
- **SC-003**: Repeat fetches of a site that needs a heavier strategy are at least 50% faster than the first fetch because failed cheaper strategies are skipped.
- **SC-004**: A repeat request within the freshness window is answered in under 100 milliseconds without any network access.
- **SC-005**: A static page is fetched without launching a browser in 100% of cases.
- **SC-006**: With 50 concurrent requests, server resident memory stays under 1 GB and returns to within 20% of its idle baseline within 60 seconds after the load ends, with no leftover browser processes.
- **SC-007**: When all strategies fail, 100% of error responses name every strategy tried and its reason for failing.
- **SC-008**: Learned site knowledge survives a server restart in 100% of tested cases.
- **SC-009**: Requests to local or private network addresses are refused in 100% of tested cases.
- **SC-010**: With 5 server instances recording outcomes at the same time, 100% of recorded outcomes are present and the store remains readable afterward.
- **SC-011**: The full automated test suite, including real-browser tests, passes on both macOS and Linux for every change before it is accepted.
- **SC-012**: A user with only a container runtime installed can start the server and complete a fetch with every strategy in under 5 minutes, without installing any browser or other dependency on the host.
- **SC-013**: For sites that serve markdown directly, 100% of plain-HTTP fetches return the site's markdown without HTML conversion.
- **SC-014**: With 50 concurrent requests to one domain, no more than the configured per-domain concurrency is in flight at any moment and the configured request rate is never exceeded.
- **SC-015**: A 429 response with a retry delay never triggers a heavier strategy, and is not counted against that strategy's remembered success rate.

## Assumptions

- Only public pages are fetched: callers cannot supply cookies or credentials per call, which also keeps the shared cache free of account-specific content.
- Every strategy, including plain HTTP, presents a browser-like identity by default; the operator can override it.
- Strategy memory is recorded against the domain the caller requested, even if the request is redirected; per-domain rate limits apply to every domain actually contacted, including redirect hops.
- There is no overall per-request deadline; callers who need a shorter total can lower the per-strategy timeout, force a strategy, or disable fallback.
- Fetched content is returned unmodified and unmarked; the server does not filter or flag prompt-injection attempts, and handling untrusted content is the client's responsibility.
- Each request fetches exactly one URL; crawling, link-following, search and batch fetch are out of scope for v1 (callers can issue parallel requests, which the per-domain limits keep safe).
- Site-provided markdown is requested through standard content negotiation; sites that do not support it simply return HTML.
- The primary users are AI assistants connecting through MCP clients, operated by a developer who installs the server locally.
- SC-001 to SC-003 depend on live sites, so they are verified by an opt-in benchmark run and manual review, not by the offline automated suite.
- Container images target Linux (amd64, and arm64 where the browser builds exist); host platforms for running them are macOS and Linux.
- Supported platforms are macOS and Linux (Windows is out of scope for v1).
- The server is a single-user, local tool whose memory and cache are shared across every MCP client and project the user runs; multi-tenant hosting and authentication are out of scope.
- Sites are identified for memory purposes by domain, with learned path-prefix overrides where a section of a site behaves differently from the rest.
- Sites requiring a login, solving of CAPTCHAs, proxy rotation or paid access are out of scope; challenge pages are detected and reported rather than solved.
- robots.txt is not consulted; politeness is provided by per-domain rate limiting and back-off, and the operator remains responsible for respecting site terms.
- Stealth measures are intended for legitimate access to publicly available content; respecting site terms and rate limits remains the operator's responsibility.
- Default cache freshness is minutes to hours and is configurable; memory is retained until reset.
- Browser components are an optional installation step; the plain HTTP strategy works without them.
