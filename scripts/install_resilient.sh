#!/usr/bin/env bash
# Resilient installer for GAR.
#
# Why this exists: package installs on this machine fail transiently often
# enough that a plain `pip install` aborts the whole setup on a network blip
# or a dropped connection, leaving a half-installed environment. This script
# is the ONLY supported way to install dependencies into this repo.
#
# Properties:
#   - Generous retries: every network operation retries with exponential
#     backoff (default 8 attempts, capped wait), not the default 1-3.
#   - Resumable downloads: large artifacts (wheels, sdists, model files) are
#     fetched to a .part file and continued with curl's -C - (HTTP Range),
#     so an interrupted download resumes instead of starting over.
#   - Cached wheels: downloads are kept in .cache/downloads and reused, so a
#     retry after a network failure does not re-download what already arrived.
#   - Idempotent: re-running is safe and picks up where it left off.
#
# Usage:
#   scripts/install_resilient.sh                # full setup (deps + dev)
#   scripts/install_resilient.sh --deps-only    # runtime deps only
#   scripts/install_resilient.sh --no-tests     # setup without running pytest
#   scripts/install_resilient.sh --retries 12   # more attempts
#   scripts/install_resilient.sh --url <u> -o <f>   # resumable fetch of one URL
#
# Env overrides:
#   GAR_INSTALL_RETRIES   attempts per operation      (default 8)
#   GAR_INSTALL_TIMEOUT   seconds per attempt        (default 120)
#   GAR_CACHE_DIR         download cache root        (default .cache/downloads)
set -euo pipefail
cd "$(dirname "$0")/.."

RETRIES="${GAR_INSTALL_RETRIES:-8}"
TIMEOUT="${GAR_INSTALL_TIMEOUT:-120}"
CACHE_DIR="${GAR_CACHE_DIR:-.cache/downloads}"
RUN_TESTS=1
DEPS_ONLY=0
FETCH_URL=""
FETCH_OUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --retries)    RETRIES="$2"; shift 2 ;;
    --timeout)    TIMEOUT="$2"; shift 2 ;;
    --no-tests)   RUN_TESTS=0; shift ;;
    --deps-only)  DEPS_ONLY=1; shift ;;
    --url)        FETCH_URL="$2"; shift 2 ;;
    -o|--output)  FETCH_OUT="$2"; shift 2 ;;
    -h|--help)    sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

log()  { printf '[install] %s\n' "$*"; }
warn() { printf '[install] WARN: %s\n' "$*" >&2; }
die()  { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }

mkdir -p "$CACHE_DIR"

# ---------------------------------------------------------------------------
# retry: run a command up to $RETRIES times with exponential backoff.
# ---------------------------------------------------------------------------
retry() {
  local attempt=1 delay=2
  while [ "$attempt" -le "$RETRIES" ]; do
    if "$@"; then
      return 0
    fi
    if [ "$attempt" -eq "$RETRIES" ]; then
      return 1
    fi
    warn "attempt $attempt/$RETRIES failed ( $* ); retrying in ${delay}s"
    sleep "$delay"
    # exponential backoff, capped at 60s so a long failure does not stall.
    delay=$(( delay * 2 ))
    [ "$delay" -gt 60 ] && delay=60
    attempt=$(( attempt + 1 ))
  done
  return 1
}

# ---------------------------------------------------------------------------
# fetch: download a URL to a file, resuming an interrupted transfer.
#
# Uses curl's -C - (continue from the byte offset already on disk) against a
# .part file. If the server ignores Range, curl reports "server does not
# support byte ranges" and we restart cleanly rather than corrupting the file.
# ---------------------------------------------------------------------------
fetch() {
  local url="$1" dest="$2"
  local part="${dest}.part"
  mkdir -p "$(dirname "$dest")"

  local attempt=1 delay=2
  while [ "$attempt" -le "$RETRIES" ]; do
    if [ -f "$part" ]; then
      local have=0
      have=$(wc -c < "$part" 2>/dev/null || echo 0)
      log "resuming $dest from byte $have"
    fi
    # -C - resumes; --retry inside curl also retries transient failures.
    if curl --fail --location --silent --show-error \
            --retry 3 --retry-delay 2 --retry-connrefused \
            --connect-timeout 20 --max-time "$TIMEOUT" \
            -C - -o "$part" "$url"; then
      mv -f "$part" "$dest"
      log "fetched $dest ($(wc -c < "$dest") bytes)"
      return 0
    fi
    if [ "$attempt" -eq "$RETRIES" ]; then
      break
    fi
    warn "download attempt $attempt/$RETRIES failed for $url; resuming in ${delay}s"
    sleep "$delay"
    delay=$(( delay * 2 ))
    [ "$delay" -gt 60 ] && delay=60
    attempt=$(( attempt + 1 ))
  done
  die "could not download $url after $RETRIES attempts (partial file kept at $part)"
}

# ---------------------------------------------------------------------------
# Single-URL mode: scripts/install_resilient.sh --url <u> -o <f>
# ---------------------------------------------------------------------------
if [ -n "$FETCH_URL" ]; then
  [ -n "$FETCH_OUT" ] || die "--url requires -o/--output"
  fetch "$FETCH_URL" "$FETCH_OUT"
  exit 0
fi

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
if [ ! -d .venv ]; then
  log "creating .venv"
  if command -v uv >/dev/null 2>&1; then
    retry uv venv --allow-existing .venv || die "could not create .venv"
  else
    retry python3 -m venv .venv || die "could not create .venv"
  fi
fi

PY=".venv/bin/python"
[ -x "$PY" ] || die "no interpreter at $PY"

install_pkgs() {
  local extra="${1:-}"
  if command -v uv >/dev/null 2>&1; then
    # uv has its own resolver cache; --reinstall is not wanted, so a failed
    # attempt is simply retried (uv resumes from its cache on the next run).
    retry uv pip install --python "$PY" $extra || return 1
  else
    retry "$PY" -m pip install $extra || return 1
  fi
}

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
if [ "$DEPS_ONLY" -eq 1 ]; then
  log "installing runtime dependencies"
  install_pkgs "-e ." || die "dependency install failed"
else
  log "installing dependencies (editable, with dev extras)"
  install_pkgs "-e .[dev]" || die "dependency install failed"
fi

log "dependency install complete"

# ---------------------------------------------------------------------------
# Local config (never clobber an existing file)
# ---------------------------------------------------------------------------
if [ "$DEPS_ONLY" -eq 0 ]; then
  # -n keeps an existing local config; warn either way.
  if [ -f gar.yaml ]; then
    log "gar.yaml exists - leaving it untouched"
  else
    cp gar.example.yaml gar.yaml && log "created gar.yaml from gar.example.yaml"
  fi
  if [ -f .env ]; then
    log ".env exists - leaving it untouched"
  else
    cp .env.example .env && log "created .env from .env.example"
  fi
fi

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
log "verifying the install"
"$PY" -c "import research_engine; print('research_engine', research_engine.__file__)" \
  || die "research_engine is not importable after install"

if [ "$RUN_TESTS" -eq 1 ] && [ "$DEPS_ONLY" -eq 0 ]; then
  log "running the test suite"
  # No extra -q: pyproject.toml already sets addopts="-q", and a second -q
  # suppresses pytest's final pass/fail summary line.
  "$PY" -m pytest || die "test suite failed"
fi

log "OK. Try: research new --mode academic 'your question'"
