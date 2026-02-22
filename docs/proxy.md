# Proxy Configuration Guide

Proxies help avoid rate limiting and IP-based blocks when collecting large volumes of ads.

## Single proxy

### Python

```python
from meta_ads_collector import MetaAdsCollector

# host:port:user:pass format
collector = MetaAdsCollector(proxy="proxy.example.com:8080:myuser:mypass")

# host:port format (no authentication)
collector = MetaAdsCollector(proxy="proxy.example.com:8080")
```

### CLI

```bash
meta-ads-collector -q "test" --proxy "proxy.example.com:8080:myuser:mypass" -o ads.json
```

### Environment variable

```bash
export META_ADS_PROXY="proxy.example.com:8080:myuser:mypass"
meta-ads-collector -q "test" -o ads.json
```

## Proxy rotation with ProxyPool

`ProxyPool` rotates through multiple proxies using round-robin selection with automatic failure tracking.

### From a list

```python
from meta_ads_collector import MetaAdsCollector, ProxyPool

pool = ProxyPool(
    proxies=[
        "proxy1.example.com:8080:user1:pass1",
        "proxy2.example.com:8080:user2:pass2",
        "proxy3.example.com:8080:user3:pass3",
    ],
    max_failures=3,    # Mark proxy as dead after 3 consecutive failures
    cooldown=300.0,    # Revive dead proxies after 300 seconds
)

with MetaAdsCollector(proxy=pool) as collector:
    for ad in collector.search(query="test", max_results=1000):
        print(ad.id)
```

### From a file

Create a text file with one proxy per line:

```
# proxies.txt
# Lines starting with # are ignored
# Blank lines are ignored

proxy1.example.com:8080:user1:pass1
proxy2.example.com:8080:user2:pass2
proxy3.example.com:8080
http://user:pass@proxy4.example.com:8080
socks5://proxy5.example.com:1080
```

```python
pool = ProxyPool.from_file("proxies.txt")
collector = MetaAdsCollector(proxy=pool)
```

### CLI with proxy file

```bash
meta-ads-collector -q "test" --proxy-file proxies.txt -o ads.json
```

## Supported proxy formats

| Format | Example |
|---|---|
| `host:port` | `proxy.example.com:8080` |
| `host:port:user:pass` | `proxy.example.com:8080:myuser:mypass` |
| HTTP URL | `http://user:pass@proxy.example.com:8080` |
| SOCKS5 URL | `socks5://proxy.example.com:1080` |

## Failure tracking

ProxyPool tracks consecutive failures per proxy:

1. Each failed request increments the proxy's failure counter
2. Each successful request resets the counter to zero
3. When a proxy reaches `max_failures` consecutive failures, it is marked as dead
4. Dead proxies are skipped in the rotation
5. After `cooldown` seconds, dead proxies become eligible for retry
6. A successful request through a revived proxy removes the dead status

```python
pool = ProxyPool(proxies, max_failures=3, cooldown=300)

# Check alive proxies
print(pool.alive_proxies)

# Manually reset all proxies
pool.reset()
```

## ProxyPool API

| Method/Property | Description |
|---|---|
| `get_next()` | Return next proxy URL (round-robin, skips dead proxies) |
| `mark_success(proxy)` | Record success, reset failure counter, revive if dead |
| `mark_failure(proxy)` | Record failure, mark dead if threshold reached |
| `reset()` | Revive all proxies, reset all counters |
| `alive_proxies` | List of currently usable proxy URLs |
| `from_file(path)` | Create pool from a text file |
| `get_proxy_dict(url)` | Convert URL to `{"http": url, "https": url}` dict |

## Disabling proxies

```bash
# CLI: explicitly disable proxy (overrides META_ADS_PROXY env var)
meta-ads-collector -q "test" --no-proxy -o ads.json
```

```python
# Python: simply omit the proxy parameter
collector = MetaAdsCollector()  # Direct connection
```
