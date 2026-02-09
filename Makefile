.DEFAULT_GOAL := help

.PHONY: help install install-dev test test-cov lint typecheck format check build clean

## help: Show this help message
help:
	@echo Available targets:
	@echo   make install      - Install the package in editable mode
	@echo   make install-dev  - Install with dev dependencies
	@echo   make test         - Run tests
	@echo   make test-cov     - Run tests with coverage report
	@echo   make lint         - Run ruff linter
	@echo   make typecheck    - Run mypy type checker
	@echo   make format       - Format code with ruff
	@echo   make check        - Run lint + typecheck + tests
	@echo   make build        - Build distribution packages
	@echo   make clean        - Remove build artifacts

## install: Install the package in editable mode
install:
	pip install -e .

## install-dev: Install with all development dependencies
install-dev:
	pip install -e ".[dev,async]"

## test: Run the test suite
test:
	python -m pytest

## test-cov: Run tests with coverage report
test-cov:
	python -m pytest --cov=meta_ads_collector --cov-report=term-missing --cov-report=html

## lint: Run ruff linter
lint:
	python -m ruff check .

## typecheck: Run mypy type checker
typecheck:
	python -m mypy meta_ads_collector/ --ignore-missing-imports

## format: Format code with ruff
format:
	python -m ruff format .
	python -m ruff check --fix .

## check: Run all checks (lint, typecheck, tests)
check: lint typecheck test

## build: Build source and wheel distributions
build:
	python -m build

## clean: Remove build artifacts and caches
clean:
	rm -rf build/ dist/ *.egg-info meta_ads_collector.egg-info/
	rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/
	rm -rf htmlcov/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
