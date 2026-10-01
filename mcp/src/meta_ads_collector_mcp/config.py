"""Private configuration, safe paths and log redaction."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from meta_ads_collector.proxy_pool import ProxyPool

from .schemas import MCPError, ProxyProfile

_SECRETS: set[str] = set()


def redact(value: str) -> str:
    for secret in sorted(_SECRETS, key=len, reverse=True):
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"(?i)(https?|socks[45]h?)://[^\s/]+@", r"\1://[redacted]@", value)
    return value


class RedactLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


class PrivateFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logs() -> None:
    # Protocol stdout is reserved for the SDK. Core logging stays on stderr.
    logging.basicConfig(level=logging.WARNING, force=True)
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactLogs())
        handler.setFormatter(PrivateFormatter("%(levelname)s:%(name)s:%(message)s"))


def safe_path(root: Path, name: str) -> Path:
    if not name or "\x00" in name or Path(name).is_absolute():
        raise MCPError("invalid_path", "Use a relative path within the configured directory")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise MCPError("invalid_path", "Path escapes the configured directory")
    return path


def private_value(environment: str | None, secret_file: str | None, root: Path) -> str:
    if environment:
        value = os.environ.get(environment, "")
    elif secret_file:
        try:
            value = safe_path(root, secret_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise MCPError("missing_secret", "Cannot read the configured private file") from exc
    else:
        value = ""
    if not value.strip():
        raise MCPError("missing_secret", "The configured secret is unavailable in this process")
    _SECRETS.add(value.strip())
    for line in value.splitlines():
        _SECRETS.add(line.strip())
        try:
            password = urlsplit(line.strip()).password
        except ValueError:
            password = None
        if password:
            _SECRETS.update({password, unquote(password), quote(unquote(password), safe="")})
    return value.strip()


def proxy_from(config: dict | None, private_dir: Path) -> ProxyPool | None:
    if config is None:
        return None
    profile = ProxyProfile.model_validate(config)
    value = private_value(profile.environment, profile.secret_file, private_dir)
    entries = [line.strip() for line in value.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    try:
        return ProxyPool(entries, max_failures=profile.max_failures, cooldown=profile.cooldown)
    except Exception as exc:
        raise MCPError("invalid_proxy", "The private proxy configuration is invalid") from exc


def public_profile(config: dict) -> dict:
    return {
        "name": config["name"],
        "source": "environment" if config.get("environment") else "private_file",
        "max_failures": config["max_failures"],
        "cooldown": config["cooldown"],
    }
