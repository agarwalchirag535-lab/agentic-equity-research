.PHONY: install test cov lint typecheck fmt gate clean

install:
	python -m pip install -e ".[dev]"

# Full test suite.
test:
	python -m pytest

# Phase 1 acceptance gate: compute layer must be 100% covered.
# `make cov` FAILS the build if coverage on firm.core.compute drops below 100%.
cov:
	python -m pytest --cov --cov-report=term-missing --cov-fail-under=100

lint:
	ruff check src tests

typecheck:
	mypy src

fmt:
	ruff format src tests

# Convenience: run the multibagger feasibility gate on a synthetic company (Phase 1 acceptance demo).
gate:
	python -m firm gate-demo

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache **/__pycache__ .coverage
