# Deployment

## Primary path: direct Python on the laptop (#150)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp gar.example.yaml gar.yaml       # optional; defaults are safe
research new --mode academic "your question"
research serve                      # API on 127.0.0.1:8000
research mcp                        # MCP over stdio for clients
```

## Docker (optional, #114/#151)

`Dockerfile` + `docker-compose.yml` ship a minimal single-app container
(API+MCP+scheduler in one process) plus optional SearXNG. The core system
must keep running WITHOUT Docker; containers are packaging, not architecture.
Data lives in a mounted volume (`./research_data:/data`).

The image's `CMD` is `research serve --host 0.0.0.0`, so the container
**requires** `GAR_PLATFORM__API__AUTH_TOKEN` — without it the server refuses
to start. `docker-compose.yml` sets it from `${GAR_TOKEN:?set GAR_TOKEN}`.

## Operations runbook (#125)

See docs/recovery.md (start/stop/recover), docs/backups.md (backup/restore),
docs/observability.md (logs/metrics/health). `research doctor` gives a quick
system health summary.

## Resource profiles (#152)

Pick via `platform.profile`; they tune scheduler caps and are the supported
way to run on small laptops or fully offline.
