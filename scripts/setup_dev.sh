#!/usr/bin/env bash
# Fresh developer setup (spec #149)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp -n gar.example.yaml gar.yaml || true
cp -n .env.example .env || true
pytest -q
echo "OK. Try: research new --mode academic 'your question'"
