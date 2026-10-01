# Beginner's Quick Start

This guide shows how to install MetaAdsCollector and save search results to a spreadsheet file. You do not need to write code. You will paste a few commands into your computer's command window.

## 1. Install Python

Download Python from [python.org/downloads](https://www.python.org/downloads/) and install it. On Windows, select the option to add Python to PATH if the installer offers it.

## 2. Open a command window

- **Windows:** Open PowerShell from the Start menu.
- **macOS:** Open Terminal from Applications → Utilities.
- **Linux:** Open your Terminal app.

## 3. Install MetaAdsCollector

Copy the command for your system, paste it into the command window, and press Enter.

**Windows:**

```powershell
py -m pip install --upgrade meta-ads-collector
```

**macOS or Linux:**

```bash
python3 -m pip install --upgrade meta-ads-collector
```

## 4. Search and save a CSV file

The following command searches ads delivered in the United States for “solar panels” and saves up to 25 results in `ads.csv` in the current folder. Replace the search words with a topic or brand you want to look up.

**Windows:**

```powershell
py -m meta_ads_collector -q "solar panels" -c US -n 25 -o ads.csv
```

**macOS or Linux:**

```bash
python3 -m meta_ads_collector -q "solar panels" -c US -n 25 -o ads.csv
```

To search another country, replace `US` with a two-letter country code such as `GB` or `EG`. Meta determines which ads and details are available in each country; results can be empty or incomplete.

## 5. Open your results

Find `ads.csv` in the folder shown in your command window and open it with Excel, Numbers, or another spreadsheet app.

If Python cannot find `meta_ads_collector`, confirm the installation completed successfully and that the same Python installation is used in both commands. See the [CLI guide](cli.md) for other options.

## Python example

If you later want to use Python code, this minimal example prints an ad ID and any available page, impressions, and spend data:

```python
from meta_ads_collector import MetaAdsCollector

with MetaAdsCollector() as collector:
    for ad in collector.search(query="solar panels", country="US", max_results=10):
        page_name = ad.page.name if ad.page else "Unknown page"
        print(f"{page_name}: {ad.id}")
        print(f"  Impressions: {ad.impressions}")
        print(f"  Spend: {ad.spend}")
```

## Next steps

- [CLI reference](cli.md) — command options and examples
- [Filtering guide](filtering.md) — filter collected results
- [Media guide](media.md) — download media returned with ads
- [API reference](api-reference.md) — Python classes and methods
