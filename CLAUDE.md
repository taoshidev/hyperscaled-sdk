# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Python Environment

Always activate the virtual environment before running any Python commands:

```bash
cd hyperscaled-sdk
source .venv/bin/activate
```

## Documentation

Refer to the project documentation before implementing new features:

- `docs/SPRINT_1.md` — Current sprint tickets, acceptance criteria, and dependency graph
- `docs/CLI_SDK_DESIGN.md` — Full CLI & SDK design spec (feature specs, API contracts, design principles)
- `docs/OVERVIEW.md` — How the three repos (landing page, Chrome extension, Vanta Network) fit together
- `docs/reports/` — Completion reports for finished tickets (SDK-001, SDK-002, etc.)

## Development Commands

```bash
source .venv/bin/activate
ruff check .              # Lint
ruff format .             # Format
mypy hyperscaled          # Type-check
pytest -v                 # Run tests
pip install -e ".[dev]"   # Install with dev dependencies
```

## Package Structure

- `hyperscaled/sdk/` — Python SDK (importable)
- `hyperscaled/cli/` — CLI entry points (Typer)
- `hyperscaled/models/` — Pydantic models
- `hyperscaled/exceptions.py` — Exception hierarchy
- `tests/` — Test suite
