# SECURITY AUDIT

## Verified sound (FACT, tested this session or in suite)
- **PathSandbox**: `.resolve()`-based containment blocks symlink escape and `..` traversal (verified); forbidden components (.ssh/.aws/...) checked post-resolve.
- **Experiment sandbox**: audit-hook denies socket/subprocess/out-of-root writes before user code; RLIMIT_AS/CPU/NPROC; scrubbed env; ssl-import safe (suite).
- **cmd_serve**: refuses non-local bind without auth token (suite + code read).
- **MCP permission implication** is downward-only; READ client denied RESEARCH tools with -32001 (suite).
- **Report path-traversal guard** on report reads (knowledge_service).

## Findings

### S-01 [RESOLVED BY PATCH] Loopback API authentication
Loopback requests now require a per-process random token by default. `research serve`
prints a generated token once when no token is configured. Unauthenticated loopback
access requires the explicit `platform.api.allow_unauthenticated_loopback: true`
opt-out. External binds still require an operator-configured token.

### S-02 [PARTIALLY MITIGATED] Retrieved-content prompt injection
The reviewed revision already contains untrusted-content prompt fences and a deterministic
claim-support verifier; the previous audit statement that claim-faithfulness checking was
absent was stale. These controls reduce obvious quote/claim inversions but do not prove
semantic entailment or prevent all planner steering. Source-allowlist weighting and a
human-reviewed adversarial false-acceptance/false-rejection study remain open.

### S-03 [STALE FINDING / CLOSED IN BASE REVISION] Unknown LLM provider
The router already raises `ValueError` for an unknown provider, and the config
tests pin this behaviour. The base-revision audit text was stale. This patch also
requires explicit `models.allow_mock: true` before the known `mock` provider can
be selected by `ModelRouter`; the configured provider/model for each role is
available in `ModelRouter.run_metadata` and mock selection is logged as a warning.

### S-04 [PATCHED, DEFENCE-IN-DEPTH] Experiment filesystem containment
The child no longer derives the allowed root from a mutable environment variable.
The parent passes the resolved workdir into a closure-backed audit hook before
executing task code. Write checks resolve symlink targets and cover common
filesystem mutation events, while `dir_fd` mutations are rejected. This remains
defence in depth: Python audit hooks are not a substitute for OS/container
isolation against fully hostile Python code.

### S-05 [RESOLVED IN BASE REVISION] MCP line-size guard
The stdio server already rejects oversized input lines at 1 MiB. The prior note
claiming the guard was absent was stale; transport framing remains a local-process
trust boundary rather than an authenticated remote transport.

### S-06 [FACT][Info] Secrets hygiene
Scrubbed child env covers API keys; redaction exists in obs_logging (tested). No secrets found committed; .env.example placeholders only.

## Cross-project isolation
- Per-project SQLite files isolate knowledge; platform.sqlite intentionally global (jobs/events) — verified project_id scoping on list endpoints.
- Global fetch/search caches keyed by URL/query (not project) — by design for dedup; a poisoned cache entry propagates across projects (documented purge ritual). Cache key completeness: URL+params; model/config changes don't invalidate fetch cache (fine) but search cache ignores recency window settings — [SUSPECTED] stale-results skew under changed freshness config.

## Priorities
1. S-01 (loopback token default)
2. BUG-09 fix (largest injection payoff: fabricated claims become detectable)
3. S-03 hard fail outside offline
4. S-04 argv-borne root
