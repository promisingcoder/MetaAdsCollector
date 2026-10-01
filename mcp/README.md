# MetaAdsCollector MCP extension

A local MCP server over the existing MetaAdsCollector library. The extension
adds tools, durable jobs, stored results, monitoring, and private proxy profiles.
It uses the core collector for Meta access, parsing, pagination, enrichment,
deduplication, media downloads, filtering, reports, and webhook delivery.

## Install and connect

The MCP extra requires Python **3.10 or newer**. The core collector retains its
Python 3.9 support and does not require the MCP SDK.

Install the published MCP extra (version 1.6.0 or newer):

```bash
python -m pip install --upgrade "meta-ads-collector[mcp]"
meta-ads-mcp --help
```

Or install from the repository root:

```bash
python -m pip install -e ".[mcp]"
meta-ads-mcp --help
```

An extra is
an optional dependency group of the same distribution, not a second collector.
The ordinary collector import and CLI retain their existing implementation.

Configure an MCP client that supports local stdio servers:

```json
{
  "mcpServers": {
    "meta-ads": {
      "command": "meta-ads-mcp",
      "args": []
    }
  }
}
```

Use the executable's absolute path if the client does not inherit your Python
environment's PATH. The client launches the server; installation alone does not
start a daemon. Protocol messages use stdout and redacted logs use stderr.

Default storage is `~/.meta-ads-collector-mcp`. Set `METAADS_MCP_DATA_DIR` or pass
`--data-dir` to choose another directory. Use **the same directory** for your
server and persistent worker. SQLite stores job definitions, results, events,
leases, checkpoints, proxy references, schedules, and monitor observation IDs.

## Tools

| Tool | Operations |
| --- | --- |
| `discover` | Supported values, schemas, fields, budgets, coverage, and worker liveness |
| `advertisers` | Page-name candidates or numeric page-ID extraction from supported URLs |
| `search` | Keyword/page searches with supported native parameters and local filters; interactive or background |
| `continue_search` | Another batch from the same search, with native pagination and deduplication |
| `inspect_ads` | Batch inspection, optional detail enrichment, and bounded media downloads |
| `results` | Stored-result pagination, field selection, local filtering, sorting, and newly observed records |
| `export_results` | JSON, JSONL, CSV, and explicitly requested webhook delivery |
| `jobs` | List, status, events, report, cancel, resume, delete |
| `monitoring` | Create, list, enable, disable, delete recurring collection definitions |
| `proxy` | Configure reference profiles, list redacted profiles, select a default, check actual Meta connectivity |

Resources: `metaads://capabilities` and `metaads://results/{result_set_id}`.
Resources return bounded data; use the tools for pagination and field selection.

### Search example

Arguments for the `search` tool:

```json
{
  "search": {
    "query": "nike",
    "country": "US",
    "status": "ACTIVE",
    "page_size": 20,
    "max_results": 100,
    "max_requests": 20,
    "max_seconds": 600
  },
  "batch_size": 20,
  "background": false
}
```

Keep the returned `result_set_id`. `continue_search` retrieves more evidence;
`results`, `inspect_ads`, and `export_results` reuse that collection. Advertiser
searches may be ambiguous: select the intended numeric ID before searching with
`page_ids`. Numeric IDs in supported Facebook URLs can be resolved directly;
vanity URLs require a name search and are not silently treated as numeric IDs.

Native parameters include query, country, category, status, search mode,
advertiser IDs and supported sorting. Local filters cover impressions/spend
ranges, delivery **start** date bounds, media type, platforms, languages, and
image/video presence. Discovery lists the exact supported values.

Range filters use **overlap**, not proof of an exact metric. `missing_data` is
`include` by default; select `exclude` to require the relevant metric bounds,
dates, platform or language data. Missing values never become zero.

Responses default to summary fields. Request `view="detailed"` for normalized
fields, `view="raw"` for the complete supplied Meta row, or `fields` to select
specific fields. Default summaries omit long media URLs, show up to three creative
variations, and limit each text field to 1,500 characters with explicit truncation
markers. Detailed/selected-field inspection retains complete creative data.
Raw data is preserved through the core's `api_fields` property.
Normalized fields follow the existing core model's defaults; raw `api_fields`
identifies the keys actually supplied by Meta. Ad bodies and links are untrusted
third-party content, not instructions.

## Background jobs and recovery

Set `background=true` to queue collection and return without waiting for it to
finish. Inspect its status or events using `jobs`. Events have sequence IDs for
incremental reading. Requests and network concurrency are bounded; core HTTP
retries/bootstrap are separate from the search-page request budget.

Interactive calls preserve a live native generator between batches. On restart,
the server replays the **last requested page**, reuses saved search tokens where
possible, and skips already committed ads. Saving the next-page cursor alone
would lose ads if a process died halfway through a page. Invalid/expired cursor
responses restart the search with deduplication and report that recovery mode.
Other upstream failures remain explicit failures with partial results retained.

Jobs have `QUEUED`, `RUNNING`, `PAUSED`, `COMPLETED`, `LIMIT_REACHED`, `FAILED`,
or `CANCELLED` states. Only `COMPLETED` means that this query was exhausted; it
does not prove coverage of every ad on Meta. Resume paused, cancelled or failed
jobs with `jobs(action="resume")`. Original budgets remain in force.

Workers use renewable leases to prevent duplicate execution. After a hard crash,
another process can reclaim the job once its lease expires (normally within
30 seconds of the last heartbeat). Cancellation and duration limits are checked
at safe boundaries; an in-flight core request can finish before cancellation.
Active duration excludes time waiting between interactive tool calls.

## Monitoring and the persistent worker

Create a monitoring schedule containing a name, `search` specification,
`interval_seconds` (at least 60), and `retention_days`. A monitor does not overlap
its own pending run. Missed intervals coalesce into one current collection.
Observation IDs persist across runs; "newly observed" does not mean "launched
since the last run". Retention removes old terminal collections for that monitor.

A client-launched server stops when the client closes. To run monitoring and
background jobs independently, explicitly start:

```bash
meta-ads-mcp worker
```

The worker remains attached to that terminal. Run it under your operating
system's service/process manager for unattended operation. `worker --once` runs
one scheduling pass and finishes the jobs it starts. It does not loop through
future schedules. Discovery reports persistent-worker liveness.

## Private proxy and session configuration

Put proxy URL(s) in a private environment variable inherited by the server and
worker. Do not put passwords in MCP arguments or client configuration examples.
Alternatively, store a proxy file under `<data-dir>/.private/` and reference its
relative filename. Profiles support newline-separated proxies, failure limits
and cooldowns using the existing core `ProxyPool`.

Arguments for `proxy` after privately setting `METAADS_PROXY`:

```json
{
  "action": "configure",
  "profile": {
    "name": "research",
    "environment": "METAADS_PROXY",
    "max_failures": 3,
    "cooldown": 300
  }
}
```

Select it with `proxy(action="default", name="research")`, or use
`search.proxy_profile` per job. Profile settings are snapshotted when jobs are
created. Secrets resolve at session start and must be available in a process
that resumes the job. Changing defaults does not alter running sessions.
Provider-specific sticky-session parameters should be included in the private
proxy configuration when the provider rotates residential exits per connection.
`proxy(action="clear_default")` clears the selected profile and returns to the
core collector's environment-based proxy behavior.

`--proxy-env METAADS_PROXY` configures a startup profile without putting the URL
on the command line. `search.cookie_env` similarly references a private variable
containing the core-supported cookie header. Search timeout, retry, delay and
jitter settings are also available. Credentials are never stored in job records
or returned by discovery/profile listing. Your MCP client may log tool arguments,
which is why these interfaces accept references rather than passwords.

## Exports, media and webhooks

Exports use existing stored results and never trigger a fresh Meta search. JSON
includes collection metadata; JSONL and CSV have a metadata sidecar. CSV encodes
nested values, including `api_fields`, as JSON cells. Relative filenames are
confined to `<data-dir>/artifacts`; existing filenames are not overwritten.

Media downloads delegate to the core downloader with limits on streamed bytes
and requests. Defaults are 64 MiB per file and 256 MiB per inspection batch.
Only Meta-hosted HTTPS asset URLs are accepted. Failed or unavailable downloads
are reported individually. Previously cached files can be reused.

Webhook delivery is explicit: provide `webhook_environment` to `export_results`
with a private environment-variable reference containing the destination.
Delivery defaults to batches of 50 records; set `webhook_batch_size` from 1 to
100, with 1 selecting individual-record delivery. Delivery reports successes
and failures; export success does not imply webhook delivery success. Failed
collection/delivery calls set the MCP error flag while preserving structured
partial results. Exported files and media remain on disk when SQLite results
are deleted or expire; manage those artifacts separately.

## Capability coverage and verification

| Existing core surface | MCP route |
| --- | --- |
| Page search and page ID/URL/name collection | `advertisers`, then `search(page_ids=...)` |
| Sync/async searches and collection | Native sync collector dispatched off the asynchronous MCP event loop |
| Pagination and deduplication | `continue_search`, durable page replay and committed-result tracking |
| Filtering | `search.filters`, `results.filters`; core filtering plus explicit strict-missing policy |
| Enrichment and media collection | `inspect_ads` with optional enrichment/downloads |
| Normalized models and all supplied fields | Detailed/raw views and selected fields |
| JSON/JSONL/CSV collection | `search`, then `export_results` without recollection |
| Streaming events, callbacks and reports | Durable job events and collection reports |
| Webhooks | Explicit export delivery using the core sender |
| Proxy pools, cookies, retries and timeouts | Private profiles and search configuration |

Run infrastructure, captured-record and actual stdio tests:

```bash
python -m pip install -e ".[dev,mcp]"
python -m pytest mcp/tests -m "not mcp_live"
```

Run real Meta tests (privately configured proxy recommended):

```bash
python -m pytest mcp/tests -m mcp_live --run-mcp-live
```

These checks cover real searches, pagination, all supplied-record preservation,
exports, details, media, stdio restarts, monitoring, and a real worker process
kill followed by lease expiry and recovery. Controlled failure tests supplement
live verification and are clearly labeled; they do not establish connectivity.

CI runs core regressions, MCP checks on Python 3.10–3.14 and Windows, isolated
wheel installation, and live Meta verification using the private CI proxy.
MCP runtime directories and test evidence are ignored and excluded from
distributions. The core source is unchanged by this extension.
