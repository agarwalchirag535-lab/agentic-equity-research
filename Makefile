.PHONY: install test cov lint typecheck fmt gate clean

# Resolve the interpreter instead of hardcoding `python`: a bare `python` does not exist on a stock
# macOS/Homebrew install (only `python3`), which silently turned `make cov` — the Phase-1 acceptance
# gate — into an unconditional "No such file or directory". A gate that cannot run is not a gate.
# Override with `make cov PY=/path/to/python` inside a venv that names it differently.
PY ?= $(shell command -v python3 || command -v python)

install:
	$(PY) -m pip install -e ".[dev]"

# Full test suite.
test:
	$(PY) -m pytest

# Phase 1 acceptance gate: compute layer must be 100% covered.
# `make cov` FAILS the build if coverage on firm.core.compute drops below 100%.
cov:
	$(PY) -m pytest --cov --cov-report=term-missing --cov-fail-under=100

lint:
	ruff check src tests

typecheck:
	mypy src

fmt:
	ruff format src tests

# Convenience: run the multibagger feasibility gate on a synthetic company (Phase 1 acceptance demo).
gate:
	$(PY) -m firm gate-demo

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache **/__pycache__ .coverage

eval:  ## replay the golden set (needs the filings in bronze; not part of `make test` on purpose)
	$(PY) -m firm eval
