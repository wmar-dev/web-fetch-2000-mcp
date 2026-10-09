# Security review (T072)

Scope: SSRF paths, log redaction, cache contents, container hardening. Reviewed against the
implementation in `src/webfetch2000/` on 2026-10-08. Findings marked **fixed** were corrected as part
of this review and are covered by tests.

## SSRF and network reach

| Path | Status |
|---|---|
| Initial URL (scheme, userinfo, host, private ranges) | Checked by `safety.ensure_allowed` before any strategy runs. Tests: `tests/unit/test_safety.py`. |
| HTTP redirects | Every hop re-validated (scheme, host, resolved addresses) and rate limited. Tests: `test_redirect_to_private_address_is_blocked`, `test_each_redirect_hop_is_rate_limited`. |
| DNS rebinding (name resolves public at check time, private at connect time) | **Fixed**: after the response starts, the HTTP strategy checks the address actually connected to (`_check_peer`) and rejects private peers. Test: `test_dns_rebinding_is_caught_by_checking_the_connected_peer`. Only a GET request is ever sent, and the body is not read when rejected. |
| Browser sub-requests, redirects and iframes | Every request passes through the context-level route guard (`_playwright._Guard`): private hosts are aborted, main-frame navigations to other domains take a rate-limit token. A blocked main navigation fails the fetch with `blocked_address`. |
| Browser DNS rebinding | Not mitigated: the guard resolves each host once per fetch and the browser resolves independently. Residual risk accepted for v1 (the browsers only run in headless contexts without credentials); run the container with a network policy that blocks private ranges if this matters. |
| Non-HTTP schemes in redirects (`file:`, `ftp:`) | Rejected as `unsupported_scheme`. In the browser, `data:`/`blob:` never touch the network. |
| `localhost`, `*.localhost`, IPv4-mapped IPv6, link-local (169.254.169.254), CGNAT | Blocked by `is_blocked_ip` (anything not globally routable) plus name checks. |
| Allow/deny lists | `allow_domains` / `deny_domains` enforced for the initial URL and each hop. |

## Resource exhaustion

- Decompression bombs: bodies are read through the decoded stream and cut at `max_response_bytes`.
- Redirect loops bounded by `max_redirects`; browser concurrency bounded by semaphores; per-domain
  concurrency and rate limits bound load on any one site.
- Open item (accepted): HTML and PDF conversion of a body up to `max_response_bytes` runs in a worker
  thread without its own timeout. A pathological 10 MB document can occupy a thread for a long time.

## Logging and privacy

- All URLs reach logs through `redact_url` (userinfo, query and fragment removed). **Fixed**: `httpx`
  and similar libraries log full URLs at INFO; their loggers are raised to WARNING in
  `logging.configure`. Test: `test_third_party_libraries_cannot_leak_urls`.
- Strategy memory stores only domain and path section, never query strings.
- stdout carries only protocol messages (`test_stdout_only_carries_protocol`).
- Error messages contain hosts, not full URLs.

## Cache contents

- The cache stores full URLs and page bodies (needed for correct keys and raw output). Entries expire
  (default 1 hour), honor `Cache-Control: no-store`, and `cache: "bypass"` avoids reading and writing.
- **Fixed**: the data directory is created `0700` and the database `0600`, so other local users cannot
  read cached pages. Test: `test_store_files_are_owner_only`.
- The cache is shared by every project that uses the server, and nothing is account-specific because
  callers cannot send cookies or credentials.
- SQL: all statements are parameterized; the only interpolated fragment is a list of `?` placeholders.

## Browser contexts

- **Fixed**: contexts are created with `accept_downloads=False` and `service_workers="block"`; each
  fetch uses a fresh isolated context that is closed in `finally`, so no cookies or storage persist.

## Container hardening

- Runs as non-root user `fetch` (uid 10001) under `tini`; data only in `/data`.
- Chromium's own sandbox is disabled in the image (`WEBFETCH_NO_SANDBOX=1`); the container is the
  isolation boundary. Recommended run flags for stricter deployments:
  `--security-opt no-new-privileges --cap-drop ALL --read-only --tmpfs /tmp -v name:/data`.
- Private addresses stay blocked in the container, including `host.docker.internal` and Docker
  networks.

## Accepted limitations (documented in README)

Prompt injection through fetched content is not filtered; `robots.txt` is not consulted; rate limits
are per process; no overall request deadline.
