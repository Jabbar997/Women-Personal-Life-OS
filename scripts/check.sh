#!/usr/bin/env bash
# Full local gate: format, lint, types, tests. Run before every commit.
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"

"$PYTHON" -m ruff format --check .
"$PYTHON" -m ruff check .
"$PYTHON" -m mypy
"$PYTHON" -m pytest
