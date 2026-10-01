# MetaAdsCollector

Collect ads from the [Meta Ad Library](https://www.facebook.com/ads/library/) using a command-line tool, Python, or an AI assistant through MCP. No Meta API key is required.

## Installation

Install [Python](https://www.python.org/downloads/) first. The collector requires **Python 3.9+**; MCP requires **Python 3.10+**. On Windows, enable **Add Python to PATH** during installation. Open PowerShell on Windows or Terminal on macOS/Linux.

Create a separate environment for this project:

**Windows (PowerShell):**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use `.venv\Scripts\python.exe` wherever the commands below say `python`; use the module form shown below for the MCP server.

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Choose the installation you need:

| Use | Command |
| --- | --- |
| Collect ads yourself with Python or the command line | `python -m pip install --upgrade meta-ads-collector` |
| Let an AI assistant collect ads through MCP | `python -m pip install --upgrade "meta-ads-collector[mcp]"` |

The MCP extra includes the collector and adds its optional server dependencies. You do not need to install both commands. MCP is available in **version 1.6.0 or newer**.

If you already cloned this repository, run `python -m pip install -e "."` from its root for the collector, or `python -m pip install -e ".[mcp]"` for MCP. Installing from a checkout uses that checkout's version; installing by package name uses a published PyPI release.

## MCP quick start

MCP connects an AI assistant to tools it can use. Install the MCP extra above, then:

1. Open your AI application's **MCP server settings**. It must support local **stdio** servers. Applications differ in where this setting lives; some accept JSON, while others ask for a command and arguments.
2. Add the following server configuration:

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

3. Replace `meta-ads-mcp` with the **absolute path** to the executable in your environment: `.venv/Scripts/meta-ads-mcp.exe` on Windows or `.venv/bin/meta-ads-mcp` on macOS/Linux. An absolute path lets the AI application find the server even when your terminal environment is not activated.
4. Restart or reconnect the AI application. Ask: **"Use the Meta Ads tools to find up to 10 active Nike ads in the US. Summarize the creatives and export the results to CSV."**

The AI client starts the server automatically. You do not need to run a second server in your terminal. To check installation yourself:

```bash
python -m meta_ads_collector_mcp discover
```

This prints capabilities without collecting ads. If your client cannot use the executable directly, set its command to the absolute path of your environment's Python and its arguments to `["-m", "meta_ads_collector_mcp"]`.

**What you can ask the assistant to do:**

| Goal | MCP tools |
| --- | --- |
| Find advertisers and collect matching ads | `advertisers`, `search`, `continue_search` |
| Inspect details, retrieve stored results, and download available media | `inspect_ads`, `results` |
| Export JSON, JSONL, or CSV; explicitly deliver stored results to a webhook | `export_results` |
| Run background collections, inspect progress, cancel, or resume | `jobs` |
| Schedule recurring searches and identify newly observed ads | `monitoring` |
| Discover supported fields/options or configure private proxy profiles | `discover`, `proxy` |

Results and job progress are saved locally in `~/.meta-ads-collector-mcp`. Later inspection and export reuse the saved collection. Interrupted jobs can resume; Meta may invalidate an old cursor, requiring a fresh search with deduplication. "Newly observed" means new to that monitor, not necessarily newly launched.

For monitoring or jobs that should keep running after the AI client closes, open a separate terminal in the same environment and run:

```bash
python -m meta_ads_collector_mcp worker
```

Keep the terminal open. The server and worker must use the same data directory; both use the default above unless you pass `--data-dir`. You can ask the assistant to configure a proxy using a private environment-variable or file reference. Keep actual credentials out of chat, committed files, and shared client configurations. See the [full MCP guide](https://github.com/promisingcoder/MetaAdsCollector/blob/main/mcp/README.md) for configuration, budgets, and recovery details.

## Collector basics

**Collect ads without writing code.** Copy this command into your terminal:

```bash
python -m meta_ads_collector -q "nike" -c US -n 10 -o ads.csv
```

It saves up to 10 matching active ads to `ads.csv` in your current folder. Open that file in Excel, Numbers, or another spreadsheet app. Change `nike` to your search term, `US` to another country code such as `GB` or `EG`, and `10` to your result limit. Change the output filename to `ads.json` or `ads.jsonl` for those formats.

| Option | Meaning |
| --- | --- |
| `-q "nike"` | Search words |
| `-c US` | Country where ads were delivered |
| `-n 10` | Maximum number of results |
| `-o ads.csv` | Output file; required for CLI collection |
| `--status all` | Include active and inactive ads |
| `--ad-type political` | Search political/issue ads; also accepts `all`, `housing`, `employment`, `credit` |
| `--help` | Show all command-line options |

**Use it in Python.** Save this as `collect_ads.py` and run `python collect_ads.py`:

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for ad in collector.search(query="nike", country="US", max_results=5):
        advertiser = ad.page.name if ad.page is not None else "Unknown page"
        print(ad.id, advertiser)
```

The library also supports pagination, async collection, filters, exports, media downloads, and HTTP/HTTPS/SOCKS proxies. Fields supplied by Meta are preserved in `ad.api_fields`; individual ads may lack spend, impressions, media, or audience details. JSON/JSONL exports retain `api_fields`; CSV includes it as a JSON column.

MetaAdsCollector uses internal Meta endpoints. Meta can change or restrict access, so network, proxy, verification, or rate-limit failures can occur. An empty query result does not establish that no matching ads exist. Keep result limits small when starting, and check errors before treating a collection as complete.

Visit the [documentation website](https://promisingcoder.github.io/MetaAdsCollector/) for the full collector guides and API reference, or the [issue tracker](https://github.com/promisingcoder/MetaAdsCollector/issues) to report a problem.
