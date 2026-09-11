#!/usr/bin/env bash
# Everything that must pass before a push.
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin}"

echo "==> ruff format --check"
"$PY/ruff" format --check .

echo "==> ruff check"
"$PY/ruff" check .

echo "==> mypy --strict"
"$PY/mypy"

echo "==> pytest"
"$PY/pytest"

echo "All checks passed."
