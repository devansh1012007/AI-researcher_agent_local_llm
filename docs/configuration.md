# Configuration

One YAML (`gar.yaml`, see `gar.example.yaml`) + env overrides
(`GAR_SECTION__KEY=value`), now extended with the `platform` section (#112).

## Platform section

```yaml
platform:
  mode: local                 # local|hybrid|online  (env modes #100)
  profile: balanced           # minimal|balanced|high_memory|cpu_only|offline (#152)
  scheduler: {max_jobs: 1, worker_threads: 4, lease_seconds: 120,
              heartbeat_seconds: 15, profile_caps: {}}
  api: {enabled: true, host: "127.0.0.1", port: 8000, auth_token: ""}
  mcp: {enabled: true}
  security: {local_only: true, privacy_mode: false,
             data_classification: INTERNAL, allowed_roots: []}
  experiments: {enabled: true, sandbox: true, timeout_seconds: 1800,
                memory_mb: 4096, cpu_seconds: 1800, network_enabled: false,
                require_human_approval: true}
```

## Environment modes (#100)

- `LOCAL_ONLY` / privacy_mode: no external calls at all — retrieval over
  existing evidence, reasoning, reports still work (#98)
- `HYBRID`: local models + external search
- `ONLINE`: additionally uses explicitly configured external services

Profiles apply automatic limit overrides on load (e.g. `offline` zeroes
network caps; `cpu_only` disables LLM_LARGE concurrency).

## Secrets (#66/#113)

Never in YAML committed to disk with real values; use env:

```bash
GAR_PLATFORM__API__AUTH_TOKEN=...
GAR_SEARCH__SEMANTIC_SCHOLAR_API_KEY=...
```

See `.env.example`.
