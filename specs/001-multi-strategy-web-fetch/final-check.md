# Final constitution and success-criteria check (T073)

Run on macOS (Apple Silicon), 2026-10-08. Offline suite: 278 passed, 1 skipped. Browser suite
(real Chromium and Camoufox, including end-to-end escalation): 17 passed, 2 skipped (headed
window tests need `WEBFETCH_TEST_HEADED=1`). Load tests (`slow`, with and without browsers): passed.
`ruff` and `mypy` clean.

## Constitution (v1.1.0)

| Principle | Result | Evidence |
|---|---|---|
| I. Well tested | Pass | Unit, contract, integration, browser and load suites; tests written before implementation per story; network mocked or served by a local test site; CI workflow runs them. |
| II. Well documented | Pass | README, `contracts/mcp-tools.md`, tool descriptions, CHANGELOG, research decisions, quickstart with a scenario-to-test map, security review. |
| III. Resource efficient | Pass | Cheapest-first routing, timeouts, response cap, per-domain and browser concurrency bounds, lazy browsers with idle shutdown, markdown output, site-provided markdown used as-is. |
| IV. Fallback mechanisms | Pass | Ordered ladder, structured attempt log in every error, degraded mode without browsers or store, bounded retries with backoff. |
| V. Memory to avoid duplicate work | Pass | Persistent shared strategy memory, validator-aware cache, in-flight coalescing. |
| Additional constraints | Pass | URL safety (incl. DNS-rebinding peer check), rate limits and back-off, stderr-only redacted logging. |

## Success criteria

| ID | Result | Evidence / note |
|---|---|---|
| SC-001 | Met (snapshot) | Live benchmark: 100% of fetchable pages returned usable content (`benchmark.md`). |
| SC-002 | Met (snapshot) | 100% first-try success after warm-up in the benchmark; `test_memory_persistence`. |
| SC-003 | **Not met in the live snapshot** | Benchmark measured a 28% repeat-fetch speed-up (target 50%). The benchmark's cheaper strategy fails fast (0.1 to 0.4 s) while the browser itself takes 0.7 to 1.5 s, so skipping the failed attempt saves little. The saving is large only when the cheaper attempt is slow (timeouts, challenge pages). Behaviour is verified by `test_skips_failed_strategies_on_repeat_visits`; the numeric target was not achieved on these sites. |
| SC-004 | Met | `test_repeat_request_is_served_from_cache_without_network` asserts a hit under 100 ms with no strategy call. |
| SC-005 | Met | `test_cheapest_first_and_browser_never_used_for_static`; end-to-end test. |
| SC-006 | Met | `test_load.py`: resident memory under 1 GB, pages bounded to 2, no leftover browser processes (browser load test). |
| SC-007 | Met | `test_all_fail_error_lists_every_strategy_and_reason`. |
| SC-008 | Met | `test_learning_survives_restart`. |
| SC-009 | Met | `test_safety.py`, `test_fetch_contract.py`. |
| SC-010 | Met | `test_store_concurrency.py` (5 processes, no lost outcomes). |
| SC-011 | **Partly verified** | The full suite passes on macOS. The Linux run happens in the CI matrix, which has not been executed from here. The `slim` image ran its smoke test on linux/aarch64. |
| SC-012 | **Partly verified** | `slim` image built and passed `scripts/smoke_container.py` (HTTP fetch, store, strategies report). The `full` image build could not be completed: Docker Desktop failed with I/O errors because the host disk was nearly full (about 650 MB free). Camoufox's Linux arm64 build was confirmed to download during that build. The `full` image and its browser smoke test remain to be run. |
| SC-013 | Met | `test_origin_markdown_passthrough_via_router`. |
| SC-014 | Met | `test_fifty_concurrent_requests_respect_domain_limits`. |
| SC-015 | Met | `test_backoff.py`, `test_deferred_outcomes_are_not_recorded`. |

## Known gaps

- SC-003 below target on the sample sites (see above).
- `full` Docker image not built or smoke-tested; Linux CI matrix not yet executed.
- Pages with very little text (for example `example.com`) are treated as empty shells and escalate
  to a browser; `min_content_chars` can be lowered.
