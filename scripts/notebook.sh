#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

pip install --upgrade pip -q
pip install -q -r requirements.txt
pip show marimo > /dev/null 2>&1 || pip install -q marimo

# exec marimo edit "$@"

exec marimo edit --watch "$@"
