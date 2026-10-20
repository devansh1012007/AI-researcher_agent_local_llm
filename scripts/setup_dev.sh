#!/usr/bin/env bash
# Fresh developer setup (spec #149)
#
# `python3 -m venv` fails on machines without the python3-venv package (no
# ensurepip) — that is the case on this workstation, so `uv` is preferred and
# is the only path that works here.
# The runtime dependencies (fastapi/uvicorn included) come from
# [project.dependencies] through the editable install; nothing extra to install.
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1; then
  # --allow-existing: re-running this script must not abort. `uv venv` refuses
  # to touch an existing environment unless told to.
  uv venv --allow-existing .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  uv pip install --python .venv/bin/python -e ".[dev]"
else
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -e ".[dev]"
fi

# `-n` (no-clobber) keeps an existing local config, but warns on every run.
cp -n gar.example.yaml gar.yaml 2>/dev/null || true
cp -n .env.example .env 2>/dev/null || true

# No extra `-q`: pyproject.toml already sets addopts="-q", and a second -q
# suppresses pytest's final pass/fail summary line.
pytest

echo "OK. Try: research new --mode academic 'your question'"
