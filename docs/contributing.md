# Contributing

Contributions to `meta-ads-collector` are welcome. This guide covers the development setup, testing, and submission process.

## Development Setup

### Prerequisites

- Python 3.9 or later
- Git
- A virtual environment tool (venv, virtualenv, etc.)

### Clone and Install

```bash
git clone https://github.com/promisingcoder/MetaAdsCollector.git
cd MetaAdsCollector

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in editable mode with all dev dependencies
pip install -e ".[dev,async,stealth]"
```

Or use the Makefile:

```bash
make install-dev
```

### Dependency Groups

| Group | What it includes | When to install |
|---|---|---|
| (none) | `requests>=2.28.0` | Always (core dependency) |
| `async` | `httpx>=0.24.0` | Async fallback when curl_cffi is unavailable |
| `stealth` | `curl_cffi>=0.7.0` | TLS fingerprint impersonation for sync and async clients (recommended) |
| `dev` | `pytest`, `pytest-cov`, `pytest-asyncio`, `ruff`, `mypy`, `types-requests` | Always for development |

## Running Tests

```bash
# Run all tests
make test

# Run tests with coverage report
make test-cov

# Run a specific test file
python -m pytest tests/test_collector.py

# Run tests matching a pattern
python -m pytest -k "test_search"

# Run with verbose output
python -m pytest -v
```

### Test Configuration

Tests are configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
asyncio_mode = "auto"
markers = [
    "integration: tests that hit real Meta API servers (deselected by default)",
]
```

Integration tests (marked with `@pytest.mark.integration`) are excluded from normal test runs. They require network access and are intended for manual verification.

## Code Style

### Linting with Ruff

The project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check for issues
make lint

# Auto-format code
make format
```

Ruff configuration from `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py39"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]
```

Selected rule sets:
- **E**: pycodestyle errors
- **F**: pyflakes
- **W**: pycodestyle warnings
- **I**: isort (import ordering)
- **UP**: pyupgrade (modern Python idioms)
- **B**: bugbear (common bugs)
- **SIM**: simplify (unnecessary complexity)

### Type Checking with mypy

```bash
make typecheck
```

mypy configuration from `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false
```

### Run All Checks

```bash
make check  # lint + typecheck + test
```

## Project Structure

```
meta-ads-collector/
  meta_ads_collector/         # Source package
    __init__.py               # Public exports
    __main__.py               # python -m entry point
    cli.py                    # Command-line interface
    client.py                 # Sync HTTP client
    async_client.py           # Async HTTP client
    collector.py              # Sync collector (high-level API)
    async_collector.py        # Async collector
    models.py                 # Data models (Ad, AdCreative, etc.)
    filters.py                # Client-side filtering
    dedup.py                  # Deduplication tracker
    events.py                 # Event emitter system
    webhooks.py               # Webhook sender
    media.py                  # Media downloader
    proxy_pool.py             # Proxy rotation
    fingerprint.py            # Browser fingerprint generation
    url_parser.py             # Facebook URL parsing
    constants.py              # Constants and defaults
    exceptions.py             # Exception hierarchy
    logging_config.py         # Logging setup
    reporting.py              # Collection report formatting
    py.typed                  # PEP 561 marker
  tests/                      # Test suite
  docs/                       # Documentation
  .github/                    # CI/CD and templates
```

## Adding a Feature

1. **Check existing issues** to see if the feature has been discussed.
2. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Write your code** following the existing patterns:
   - Add the public API to `__init__.py` and `__all__`
   - Add corresponding tests in `tests/`
   - Use type hints on all public methods
   - Add docstrings following the existing Google-style format
4. **Write tests** covering the happy path and edge cases.
5. **Run all checks**:
   ```bash
   make check
   ```
6. **Update documentation** if the feature adds new user-facing behavior:
   - Update `README.md` if it's a headline feature
   - Add or update the relevant `docs/*.md` file
   - Update `CHANGELOG.md` under `## [Unreleased]`

## Fixing a Bug

1. **Create a failing test** that reproduces the bug.
2. **Fix the bug** in the source code.
3. **Verify the test passes**.
4. **Add a `CHANGELOG.md` entry** under `### Fixed`.

## Submitting a Pull Request

1. Push your branch to your fork.
2. Open a pull request against `main`.
3. Fill out the PR template:
   - Summary of changes
   - Type of change (bug fix, feature, refactor, docs)
   - Checklist: ruff passes, tests pass, mypy passes, docs updated, CHANGELOG updated
   - Test plan
4. Wait for CI to pass (Python 3.9--3.13 matrix, linting, type checking, tests).
5. Address any review feedback.

## Commit Messages

Use clear, descriptive commit messages:

- `Add proxy rotation support to async collector`
- `Fix session refresh loop when all tokens are stale`
- `Update CLI to support --webhook flag`

## Important Constraints

- **Never modify Python source files in documentation-only PRs.** Keep docs and code changes in separate commits when possible.
- **All public classes and methods must have docstrings.**
- **Test coverage should not decrease.** New features must include tests.
- **The library must remain compatible with Python 3.9+.** Do not use features from 3.10+ without `from __future__ import annotations`.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](../CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.
