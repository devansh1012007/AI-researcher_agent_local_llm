# SECURITY AUDIT

## Verified sound (FACT, tested this session or in suite)
- **PathSandbox**: `.resolve()`-based containment blocks symlink escape and `..` traversal (verified); forbidden components (.ssh/.aws/...) checked post-resolve.
- **Experiment sandbox**: audit-hook denies socket/subprocess/out-of-root writes before user code; RLIMIT_AS/CPU/NPROC; scrubbed env; ssl-import safe (suite).
- **cmd_serve**: refuses non-local bind without auth token (suite + code read).
- **MCP permission implication** is downward-only; READ client denied RESEARCH tools with -32001 (suite).
- **Report path-traversal guard** on report reads (knowledge_service).

## Findings

### S-01 [FACT][Medium] Localhost API is unauthenticated by default
Token enforced only for non-local binds (D15). Any local process (malicious npm package, other user session) can drive the full research API — create projects, run jobs, read all stored research, trigger experiment execution approval flows that require only RESEARCH/WRITE perms. On a single-user laptop this is a documented tradeoff; as soon as `serve` runs on 0.0.0.0 WITH a token but filesystem holds research_data/, the token protects HTTP but nothing else local. Recommendation: default-on loopback token with auto-generated value printed once; opt-out flag.

### S-02 [FACT][Medium] Prompt-injection surface into extraction/planning
Web chunk text flows verbatim into evidence_extractor / planner prompts (documented boundary tests exist for report synthesis). Injection can steer extraction JSON (fabricated claims with in-chunk quotes PASS quote verification by construction) and steer query generation toward attacker-chosen sources. Mitigations present: schema validation + quote verification + tier weights; missing: claim-faithfulness check (BUG-09) and source-allowlist weighting for planner-proposed queries. Severity bounded by LOCAL_ONLY defaults.

### S-03 [FACT][Low] Unknown LLM provider silently becomes MockProvider
router.py:29-32 logs a warning then degrades. In HYBRID deployments a typo'd provider name silently produces mock-grade "evidence" marked EXTRACTED — a data-quality/security-adjacent footgun rather than classic vuln. Should hard-fail outside offline profiles.

### S-04 [FACT][Low] Experiment child env relies on GAR_EXPERIMENT_WORKDIR trust
User code can *overwrite* its own workdir env var pre-write to widen write containment to any path (guard compares against env value at event time). Network/RLIMIT still hold. Fix: pass root via argv constant compiled into guard prefix, not env.

### S-05 [INFERENCE][Low] MCP stdio server trusts framing
Hand-rolled line-delimited JSON-RPC without max-length guards; a hostile co-resident process on the same stdin pipe is already game-over; risk accepted for local-first scope.

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
