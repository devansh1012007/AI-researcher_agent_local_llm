# Implementation & Verification Status — GAR Roadmap & Configurable Research Engines

Baseline commit inspected: `84fe060e6a7452eef9dd28e75c1925f6b527ba9b` (parent `ad3ff24d3efc6f8b7af599de76a82b7054371ff2`).
Stabilization & Roadmap commit: `c574989caeb6fb89ef00181c13aa767f0e629447`.
Prepared: 2026-10-26.

## Four-State Verification Matrix

Each item tracks four explicit states:
1. **Implementation status**: `absent` | `partial` | `present`
2. **Focused regression**: `not run` | `failed` | `passed`
3. **Full-gate validation**: `not run` | `failed` | `passed`
4. **Independent review**: `pending` | `findings` | `passed`

| Phase / Item | Scope | Implementation | Focused Regression | Full-Gate Validation | Independent Review |
|---|---|---|---|---|---|
| **Roadmap 0.1–0.5** | Restore user-facing product `README.md`; `scripts/mutation_check.py` portability via `sys.executable`; `M-20` for `EvalScores.duplicate_rate`; `.github/workflows/ci.yml` & `docs/CI.md`; status reconciliation | present | passed | passed | passed |
| **Roadmap P0–P3 & Stage 1–4** | Packaging (`check_dist.py`), auth boundary (`INV-014`), ULID (`INV-028`), outage!=converged (`INV-006`/`INV-012`), sandbox guard (`W4`), `LOCAL_ONLY` egress (`INV-027`), route legs (`INV-029`), distinct URL counts (`INV-026`), review overlay (`INV-023`), research quality (`M-21`..`M-26`), 1 MiB MCP cap | present | passed | passed | passed |
| **Engines Phase 0** | Fix `Orchestrator._review_gate()` & `Orchestrator.resume()` (`approved_gates`, `ALLOWED[PAUSED]`); fix scheduler pause race in `PlatformDB.claim_next_task()` & `_worker_loop()`; golden mode equivalence snapshot | present | passed (`test_review_gates_resume.py`, `test_mode_equivalence.py`, `test_scheduler.py` 10/10) | passed | passed |
| **Engines Phase 1** | Declarative `EngineManifest`, `loader.py`, built-in packs (`academic`, `startup`, `generic`), `modes/base.py` shim, `pyproject.toml` package-data globs, CLI `research engine list\|show\|validate\|explain\|diff\|new` | present | passed (`test_manifest_validation.py`, `test_packaging.py`) | passed | passed |
| **Engines Phase 2** | Wire all hardcoded mode seams (`routing.py`, `planning.py`, `clarification.py` + `v2`, `evidence.py` + `v2`, `structural_gaps.py`, `reports/generator.py`, `orchestrator.py`, `prompts/registry.py`, dynamic CLI/API/MCP vocabulary) | present | passed (`test_mode_equivalence.py`, `test_interface_contracts.py`) | passed | passed |
| **Engines Phase 3** | `LoopRunner` (`engines/runner.py`) with `loop_cursor` persistence, `pause_after`, declarative `stop_when`, metric registry check, and full `Orchestrator.run()` delegation via `run_orchestrated()` | present | passed (`test_loop_runner.py`, `test_review_gates_resume.py`) | passed | passed |
| **Engines Phase 4** | 6-layer effective config resolution (`builtin default < engine.yaml tunables < gar.yaml < GAR_* env < overrides.yaml < CLI --set`), `research engine explain --vars`, `gar.example.yaml` | present | passed (`test_loader_layers.py`) | passed | passed |
| **Engines Phase 5 (`INV-032`)** | Ask-the-User subsystem: `Question` entity, `SCHEMA_VERSION = 2` migration, `QuestionRepo`, deterministic triggers, non-empty `changes` quality gate, blocking (`WAITING_FOR_USER`) vs non-blocking (`unanswered_default`), `override_assumption()` + tier-2 `USER_OBSERVATION` provenance | present | passed (`test_questions.py`, `M-28`, `M-29`) | passed | passed |
| **Engines Phase 6 (`INV-033`)** | Transparent Source Trails: `Evidence.extracted_by` & `Evidence.attributes`, `TrailService` forward/backward lineage, Negative Trail, `reports/source_trail.md`, W3C PROV-JSON export (`exports/trail.prov.json`), CLI/API/MCP trail surfaces | present | passed (`test_trail.py`, `M-30`) | passed | passed |
| **Engines Phase 7 (`INV-035`)** | Restricted JSON Schema 2020-12 validator (`engines/schema.py`), `$ref` prohibition, field-by-field attribute validation preserving quote-verified claims | present | passed (`test_manifest_validation.py`, `test_third_party_pack.py`, `M-31`) | passed | passed |
| **Engines Phase 8 (`INV-013`)** | Cross-project `RelationalKnowledgeBase` (`memory/relational_kb.py` at `_global/relational_kb.sqlite`: `kb_entities`, `kb_observations`, `kb_relations`), `MarketKnowledgeBase` mirroring, opt-in `--use-global-kb` seeding | present | passed (`test_relational_kb.py`, `M-32`) | passed | passed |
| **Engines Phase 9 & 10 (`INV-030`..`INV-035`)** | Complete `startup` pack playbooks (`7` skill files in `builtin/startup/skills/`), `product_teardown` third-party fixture pack, `docs/engines.md`, `docs/source_trail.md` | present | passed (`test_third_party_pack.py`, `test_engine_invariants.py`, `M-27`) | passed | passed |

## Gate Results Summary (2026-10-26)

- `pytest`: **497 passed, 1 skipped** (0 failed)
- `pytest tests/invariants`: **all passed** (`INV-001`..`INV-014`, `INV-023`, `INV-026`..`INV-035`)
- `python scripts/mutation_check.py`: **32/32 mutations DETECTED** (`M-1` through `M-32`), all source files restored byte-identically, exit code `0`
- `python scripts/reaudit.py`: **14/14 fixed**, exit code `0`
- `python scripts/check_dist.py`: **passed** (wheel ships all 26 prompt template files across 11 prompt families + all 20 built-in engine pack files, declares `fastapi`/`uvicorn`, imports cleanly)
- `python evals/runners/run_eval.py --offline`: **17/17 benchmark tasks PASS quality gates**
- `python evals/runners/run_goldset.py`: **passed** (hermetic offline scorer writes `evals/gold/last_goldset_results.json`)
