# CI regression cases

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
