# web-fetch-2000-mcp Constitution

## Core Principles

### I. Well Tested (NON-NEGOTIABLE)

Every feature and bug fix ships with automated tests. Tests are written before or alongside the implementation and must fail without it. Unit tests cover logic; integration tests cover MCP tool contracts, fetch behavior and fallback paths. Network access in tests is mocked or recorded so the suite is deterministic and runs offline. A change does not merge with failing or skipped-without-reason tests.

### II. Well Documented

Every MCP tool has a documented purpose, input schema, output shape and error behavior. The README covers setup, configuration and usage examples. Non-obvious decisions are recorded where they are made (spec, plan, or code comment explaining *why*). Documentation changes land in the same change as the behavior they describe.

### III. Resource Efficient

Fetching and processing must bound their use of network, CPU, memory and tokens. Enforce timeouts, response-size limits and streaming or truncation for large pages. Return the smallest useful content (for example, extracted main content rather than raw HTML) and let callers opt into more. No unbounded buffers, retries or concurrency. Avoid dependencies that add weight without clear benefit.

### IV. Fallback Mechanisms

No single fetch strategy is assumed to succeed. Each tool defines an ordered fallback chain (for example, a direct fetch, then an alternate user agent or renderer, then a cached or archived copy) with clear conditions for moving to the next step. Failures degrade gracefully and return structured errors that name the strategies tried and why each failed. Retries use bounded backoff.

### V. Memory to Avoid Duplicate Work

Repeated requests must not repeat work. Fetched and processed results are cached with a key that reflects what was requested (URL, options, extraction mode), a defined TTL, and respect for HTTP cache validators (ETag, Last-Modified, Cache-Control). In-flight identical requests are coalesced. Cache size is bounded with eviction, and callers can bypass or refresh it explicitly. The same principle applies to development: check existing code, specs and notes before building something new.

## Additional Constraints

- Safety: validate and normalize URLs, block access to local and private network addresses by default, and respect robots and rate limits where applicable.
- Observability: log fetch strategy used, cache hit or miss, duration and failure reason to stderr (never stdout, which carries the MCP protocol). Never log secrets.
- Simplicity: prefer the smallest design that satisfies the spec; complexity beyond that must be justified in the plan.

## Development Workflow

- Work follows the Spec Kit flow: specify, plan, tasks, implement.
- Each plan includes a Constitution Check against the principles above.
- Changes are small and reviewable; review verifies tests, docs, resource bounds, fallbacks and caching behavior.

## Governance

This constitution supersedes other practices. Amendments require a documented rationale, a version bump, and updates to any dependent templates or docs. Versioning is semantic: MAJOR for removed or redefined principles, MINOR for added principles or sections, PATCH for clarifications. Violations must be justified in the plan's complexity tracking or fixed before merge.

**Version**: 1.0.0 | **Ratified**: 2026-10-08 | **Last Amended**: 2026-10-08
