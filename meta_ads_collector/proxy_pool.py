"""
Proxy pool for Meta Ads Collector.

Provides round-robin proxy selection with failure tracking,
automatic dead-proxy exclusion, and cooldown-based recovery.
"""

import logging
import time

from .exceptions import ProxyError

logger = logging.getLogger(__name__)


def parse_proxy(proxy_string: str) -> str:
    """Parse a proxy string into a standard URL format.

    Supported input formats:
      - ``host:port`` (no authentication)
      - ``host:port:user:pass`` (embedded credentials)
      - ``http://user:pass@host:port`` (standard URL)
      - ``socks5://host:port`` (SOCKS5 URL)

    Args:
        proxy_string: Raw proxy string in any supported format.

    Returns:
        A normalized proxy URL (e.g. ``http://host:port``).

    Raises:
        ProxyError: If the format cannot be parsed.
    """
    stripped = proxy_string.strip()
    if not stripped:
        raise ProxyError("Empty proxy string")

    # Already a URL?
    if "://" in stripped:
        return stripped

    parts = stripped.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    elif len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    else:
        raise ProxyError(
            f"Invalid proxy format: {proxy_string!r}. "
            "Expected host:port, host:port:user:pass, or a URL."
        )


class ProxyPool:
    """Round-robin proxy pool with per-proxy failure tracking.

    Args:
        proxies: List of proxy strings (any format accepted by
            :func:`parse_proxy`).
        max_failures: Number of consecutive failures before a proxy is
            marked dead.
        cooldown: Seconds before a dead proxy is eligible for retry.

    Raises:
        ProxyError: If no valid proxies are provided.
    """

    def __init__(
        self,
        proxies: list[str],
        max_failures: int = 3,
        cooldown: float = 300.0,
    ) -> None:
        if not proxies:
            raise ProxyError("Proxy list is empty")

        self.max_failures = max_failures
        self.cooldown = cooldown

        # Normalize all proxy strings
        self._proxies: list[str] = []
        for p in proxies:
            self._proxies.append(parse_proxy(p))

        # Per-proxy state
        self._failures: dict[str, int] = {p: 0 for p in self._proxies}
        self._dead_since: dict[str, float] = {}

        # Round-robin index
        self._index = 0

        logger.debug("ProxyPool initialized with %d proxies", len(self._proxies))

    @classmethod
    def from_file(cls, filepath: str, **kwargs: object) -> "ProxyPool":
        """Load proxies from a text file.

        Blank lines and lines starting with ``#`` are skipped.

        Args:
            filepath: Path to the proxy list file.
            **kwargs: Additional keyword arguments passed to ``__init__``.

        Returns:
            A new ProxyPool instance.

        Raises:
            ProxyError: If the file contains no valid proxy lines.
        """
        proxies: list[str] = []
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                proxies.append(line)

        if not proxies:
            raise ProxyError(f"No proxies found in file: {filepath}")

        return cls(proxies, **kwargs)  # type: ignore[arg-type]

    @property
    def alive_proxies(self) -> list[str]:
        """Return the list of proxies that are currently alive or have
        passed their cooldown period."""
        now = time.time()
        alive: list[str] = []
        for proxy in self._proxies:
            if proxy not in self._dead_since:
                alive.append(proxy)
            elif now - self._dead_since[proxy] >= self.cooldown:
                # Cooldown expired -- revive this proxy
                alive.append(proxy)
        return alive

    def get_next(self) -> str:
        """Return the next proxy in round-robin order.

        Dead proxies are skipped unless their cooldown has expired.

        Returns:
            A proxy URL string.

        Raises:
            ProxyError: If all proxies are dead and none have passed
                their cooldown.
        """
        alive = self.alive_proxies
        if not alive:
            raise ProxyError(
                "All proxies are dead. Reset the pool or wait for "
                "cooldown to expire."
            )

        # Wrap the index around alive list length
        proxy = alive[self._index % len(alive)]
        self._index = (self._index + 1) % len(alive)
        return proxy

    def mark_success(self, proxy: str) -> None:
        """Record a successful request through the given proxy.

        Resets the consecutive failure counter to zero and revives
        the proxy if it was dead.

        Args:
            proxy: The proxy URL string.
        """
        self._failures[proxy] = 0
        if proxy in self._dead_since:
            del self._dead_since[proxy]
            logger.info("Proxy revived after success: %s", proxy)

    def mark_failure(self, proxy: str) -> None:
        """Record a failed request through the given proxy.

        If the consecutive failure count reaches ``max_failures``,
        the proxy is marked as dead.

        Args:
            proxy: The proxy URL string.
        """
        self._failures[proxy] = self._failures.get(proxy, 0) + 1
        count = self._failures[proxy]
        logger.debug(
            "Proxy failure %d/%d: %s", count, self.max_failures, proxy
        )
        if count >= self.max_failures and proxy not in self._dead_since:
            self._dead_since[proxy] = time.time()
            logger.warning("Proxy marked as dead: %s", proxy)

    def reset(self) -> None:
        """Reset all failure counters and revive all dead proxies."""
        self._failures = {p: 0 for p in self._proxies}
        self._dead_since.clear()
        self._index = 0
        logger.info("ProxyPool reset: all proxies revived")

    def get_proxy_dict(self, proxy_url: str) -> dict[str, str]:
        """Convert a proxy URL into a proxy dict.

        Args:
            proxy_url: A proxy URL string.

        Returns:
            Dict with ``http`` and ``https`` keys.
        """
        return {"http": proxy_url, "https": proxy_url}

    def __len__(self) -> int:
        return len(self._proxies)

    def __repr__(self) -> str:
        alive = len(self.alive_proxies)
        total = len(self._proxies)
        return f"ProxyPool(total={total}, alive={alive})"
