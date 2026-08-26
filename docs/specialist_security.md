# Specialist Security Model

Specialists inherit the core security model; they gain nothing extra.

## Guarantees

| Threat | Enforcement |
|---|---|
| read unrelated projects | `SpecialistApi._scope` rejects any foreign project id (tested §76) |
| write outside permissions | capability check before every mutation (`PermissionDenied`) |
| bypass grounding | facade has no raw-evidence escape; both gates run inside `create_evidence`; INV-014 static scan forbids storage imports in specialists |
| bypass scheduler/ownership | specialists cannot create threads of execution; more work = `CREATE_RESEARCH_TASK` → orchestrator-owned fenced task |
| mutate reports as state | reports are derived-only; purity guarded by fingerprint tests |
| unbounded resource use | per-invocation budgets hard-stop LLM/query/document/time spend |
| silent failure spread | failures raise through the runner → task FAILED with error text; perf registry counts them; events emitted |

## Inherited platform guarantees

loopback-bound API with token-gated external bind · sandboxed experiment
execution untouched · MCP permission choke point unchanged (downward-only) ·
external content remains UNTRUSTED (retrieval never becomes system
instruction with tool privileges) · audit trail: every invocation records
specialist/version/reason/budget/duration/result (§69) into platform events
plus the `specialist_perf` registry.

## Malicious-specialist fixtures (§76)

`tests/specialists/test_contract_harness.py::TestMaliciousSpecialist`
attempts cross-project reads, raw escapes and storage construction — all are
caught by platform enforcement, not by specialist good behavior.
