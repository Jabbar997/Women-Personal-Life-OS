#!/usr/bin/env bash
# Create the virtualenv and install the project with its dev tooling.
set -euo pipefail

python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
