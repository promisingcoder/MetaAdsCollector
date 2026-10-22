# CI regression cases

## Live transport reruns

All actual Meta invocations (`scripts/check_distribution.py --live ...` and
`mcp/check_distribution.py --live`) run pytest with `--reruns 2 --reruns-delay 15`
and an `--only-rerun` allowlist of transport failures: curl timeouts, stalled or
refused upstream tunnels (`CONNECT tunnel failed, response 590`), connection
resets, DNS failures, Meta rate limits and bootstrap authentication errors caused
by them. Every other failure (wrong field values, missing ads, library errors)
fails on the first attempt. `test_live_invocations_retry_only_transport_failures`
keeps the two scripts' allowlists identical and checks representative messages.
The live test gateways also retry one stalled upstream attempt within a single
client request (`tests/meta_forward_proxy.py`).

## SOCKS DNS modes and private CI sessions

`live-proxy` installs the built wheel outside the checkout and runs all six
SOCKS regression cases before the slower full-suite result is available. Both
`socks5://` (client DNS) and `socks5h://` (proxy DNS) remain real Meta tests.
Related parameter cases share a derived residential session; each test family
has its own session so earlier full-suite traffic does not determine its exit.
Explicit user-selected proxy sessions and other providers are preserved.

The JUnit `meta_transport` property records actual Meta destination addresses,
HTTP status, numeric GraphQL error codes, and whether an LSD token is present.
It excludes response bodies, error messages, token values, cookies, request
payloads, URL query strings, and proxy credentials. Privacy unit contracts use
an ephemeral canary; integration cases collect actual Meta ads.

Run the six cases with your private proxy configured:

```bash
python -m pytest tests/test_live_proxy_transport.py --run-integration -m integration -k "different_python_dns_view or authenticated_socks_proxy" -o junit_family=legacy
```

Or verify the distribution built in `dist/`:

```bash
python scripts/check_distribution.py --live --proxy-diagnostics
```

All diagnostics failures block CI. The full live suite still runs the same
cases, and MCP live tests still require the core live suite to pass.

## Meta media tunnel failures

These cases reproduce the two failures in tag CI run
[36910660546](https://github.com/promisingcoder/MetaAdsCollector/actions/runs/36910660546).
The sample ads and asset URLs are fetched from the real Meta Ad Library at test time.
Successful recovery must download real Meta CDN bytes; no substitute response or
dummy URL is used. Controlled 590 exceptions exercise the failure path before
delegating to the real session. Persistent upstream failures still fail recovery tests.

| Test case | Conditions | Required result |
| --- | --- | --- |
| `test_live_relative_media_directory_reports_an_absolute_path[clean]` | Relative output directory; real transfer; three-attempt budget | Successful, nonempty file; absolute path inside the requested directory; no partial files |
| `test_live_relative_media_directory_reports_an_absolute_path[two-tunnel-failures]` | First two attempts raise CONNECT 590; third transfers real Meta media | Exactly three attempts; same path and byte checks as the clean case |
| `test_live_meta_media_with_controlled_proxy_connect_590_is_bounded[clean]` | No injected error; real network may encounter transient errors | Successful real transfer within one to three attempts |
| `test_live_meta_media_with_controlled_proxy_connect_590_is_bounded[recovers]` | One injected CONNECT 590; remaining attempts use real Meta | Successful real transfer within two to three attempts |
| `test_live_meta_media_with_controlled_proxy_connect_590_is_bounded[third-attempt-recovers]` | Two injected CONNECT 590 errors | Successful real transfer on attempt three |
| `test_live_meta_media_with_controlled_proxy_connect_590_is_bounded[exhausts]` | All three attempts raise CONNECT 590 | Explicit failure with the 590 error; exactly three attempts; no path, size, or files |

The former recovery assertion demanded exactly two requests after one injected
failure. That assumed the next real request could not fail. Recovery now checks
actual success and the configured retry budget. The path test explicitly uses
three attempts so it also covers recovery after the two observed tunnel failures;
the library's default retry setting remains unchanged.

Run these cases with your private proxy environment configured:

```bash
python -m pytest tests/test_audit_live_io.py --run-integration -k "relative_media_directory or controlled_proxy_connect_590"
```

## CI configuration contracts

`test_ci_configuration.py` reads the actual workflow files, including their
copies from source distributions during installed-wheel verification.

| Test | Required behavior |
| --- | --- |
| `test_every_branch_push_runs_ci_but_tag_push_does_not_duplicate_release_ci` | Every branch push, including main, triggers CI; tag pushes do not create another copy |
| `test_published_releases_keep_full_validation_and_private_proxy_forwarding` | A published release runs full reusable CI with the private proxy secret before publication |
| `test_live_failures_remain_blocking_and_mcp_live_runs_after_core_live` | Actual Meta failures block CI; MCP live tests follow core live tests |
| `test_public_package_verification_includes_core_and_mcp_live_tests` | Published artifacts are independently checked against real Meta through both core and MCP |

The branch filter follows [GitHub's workflow trigger rules](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushbranchestagsbranches-ignoretags-ignore).
Core media regressions run in the existing `live-meta` CI job; configuration checks
run in the regular Python matrices and isolated distribution suites. MCP regressions
remain in their separate matrix and live job.

## Source archive staging

`test_sdist_build_uses_private_staging_instead_of_mutating_checkout` verifies a
real source build uses a temporary source snapshot. Running a separate build
beside pytest previously produced a Windows file-lock error while both processes
used `meta_ads_collector-1.6.0` staging files. Archive regression builds now have
their own staging directory. Installed-wheel tests reconstruct the shipped source
archive and exercise the same real build and staging guard. The archive must also
contain all workflow fixtures needed by the configuration tests.
