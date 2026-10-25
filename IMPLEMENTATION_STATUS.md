# Implementation & Verification Status — GAR Roadmap Phases 0 through 6

Baseline commit inspected: `84fe060e6a7452eef9dd28e75c1925f6b527ba9b` (parent `ad3ff24d3efc6f8b7af599de76a82b7054371ff2`).
Prepared: 2026-10-25.
Candidate SHA verified prior to doc stamp: `34a04dac04d8f015cbf6ba466cf30a25627cba19` (`34a04dac`).

## Four-State Verification Matrix

Each item tracks four explicit states per Roadmap §0.5:
1. **Implementation status**: `absent` | `partial` | `present`
2. **Focused regression**: `not run` | `failed` | `passed`
3. **Full-gate validation**: `not run` | `failed` | `passed` (recorded against exact candidate SHA)
4. **Independent review**: `pending` | `findings` | `passed`

| Phase / Item | Scope | Implementation | Focused Regression | Full-Gate Validation | Independent Review |
|---|---|---|---|---|---|
| **0.1** | Restore user-facing product `README.md`; remove `apply_ci_stabilization.py` | present | passed | passed | passed |
| **0.2** | `scripts/mutation_check.py` portability via `sys.executable` | present | passed (`test_sandbox_override_write.py`) | passed | passed |
| **0.3 / C18** | Add `M-20` for `EvalScores.duplicate_rate` (`duplicate_ratio` vs `rejected_ratio`) | present | passed (`M-20: DETECTED`) | passed | passed |
| **0.4** | GitHub Actions workflow `.github/workflows/ci.yml` & `docs/CI.md` | present | passed (local gate stack) | passed locally (hosted runner pending push) | passed |
| **0.5 / C20** | Reconcile `FIX_PLAN.md`, `00-mission.md`, `01-work-ledger.md`, `IMPLEMENTATION_STATUS.md` | present | passed | passed | passed |
| **P0-1..P0-6** | Packaging (`check_dist.py` 22 templates), auth boundary (`INV-014`), ULID (`INV-028`), outage!=converged (`INV-006`/`INV-012`), sandbox guard (`W4`), `LOCAL_ONLY` egress (`INV-027`/`C09`–`C12`) | present | passed | passed | passed |
| **Stage 1–3 (`C01`–`C12`, `C22`, `C23`)** | `trace_claim` roles, route legs (`INV-029`), distinct URL counts (`INV-026`), watcher failure separation, ULID ordering (`created_at`), per-hop redirect egress check | present | passed | passed | passed |
| **Phase 2A (`P1-1`, `P1-7`, `P1-10`, `P1-12`)** | Unknown LLM provider hard fail; wire/remove dead config knobs; JSON env override coercion for list/dict; CLI `--config` propagation | present | passed (`test_phase2a_config_providers.py`, 14/14) | passed | passed |
| **Phase 2B (`P1-2`, `P1-3`, `P1-8`, `P1-9`)** | Dedicated prompt templates (`assumption_generator`, `methodology_designer`, `falsification_designer`); `structured()` tuple contract + `last_outcome`; `PromptSpec.render()` placeholder safety; numeric version sorting (`v10` > `v2`) | present | passed (`test_phase2b_prompts_llm.py`, 9/9) | passed | passed |
| **Phase 2C (`P1-4`, `P1-5`, `P1-6`)** | Flat API error envelope `{"error": {"code", "message", "trace_id"}}` across 4xx/5xx; `list_projects()` DTO (`question`, `created_at` newest-first); secret redaction in `EventLog` (`events.jsonl` & `research_log.md`) | present | passed (`test_phase2c_api_dto_redaction.py`, 4/4) | passed | passed |
| **Phase 2D (`P1-13`..`P1-16`)** | Route leg mapping, watcher failure semantics, `SemanticScholarProvider` error contract, `DuckDuckGoProvider._parse` challenge vs no-results vs unknown HTML | present | passed (`test_phase2d_duckduckgo_parsing.py`, 5/5) | passed | passed |
| **Phase 3 (`P2-1`..`P2-7`)** | Dynamic 43-route API & 30-tool MCP conformance + docs parity (`P2-1`); property-style invariants (`P2-2`); silent-exception & `assert` removal (`P2-3`, `P2-4`); canonical money parser & dead-code cleanup (`P2-5`); doc drift (`P2-6`); `/health` events degradation (`P2-7`) | present | passed (`test_interface_contracts.py`, `test_system_invariants.py`, `test_phase3_resilience_health.py`) | passed | passed |
| **Phase 4 (`C13`–`C16`)** | Append-only `ReviewDecision` overlay, `ReviewService`, CLI/API/MCP adapters, report claim filtering & purity (`INV-004`/`INV-023`) | present | passed (`test_stage4_review.py`, `test_interface_contracts.py`) | passed | passed |
| **Phase 5 (`P3-1`..`P3-9`, `C17`, `C21`, `C24`)** | `citation_coverage` + `report_citation_coverage` (`M-21`), deduplicated `research_gain` (`M-22`), `dup_count` wiring (`M-23`), unsupported hypothesis cap `<=0.25`, `RefinementLoop` lifecycle transitions, `pain_evidence_class` funding vs payment (`M-24`), P4 evidence-derived strength (`M-25`), content-key hypothesis ranking tie-break, `Experiment.opportunity_id` scoping (`M-26`), `run_eval.py` & `run_goldset.py` | present | passed (`test_phase5_research_quality.py`, `M-20`..`M-26: DETECTED`) | passed | passed |
| **Phase 6 (`6.1`–`6.3`)** | 1 MiB max line limit in `mcp_server/server.py`; `freshness_summary`/`observed_at` & `ReportRepo` wiring | present | passed (`test_phase6_transport_freshness.py`, 2/2) | passed | passed |

## Gate Results Summary (2026-10-25)

- `pytest`: **465 passed, 1 skipped** (0 failed)
- `pytest tests/invariants`: **all passed**
- `python scripts/mutation_check.py`: **26/26 mutations DETECTED** (`M-1` through `M-26`), all source files restored byte-identically, exit code `0`
- `python scripts/reaudit.py`: **14/14 fixed**, exit code `0`
- `python scripts/check_dist.py`: **passed** (wheel ships all 22 template files across 11 prompt families, declares `fastapi`/`uvicorn`, imports cleanly)
- `python evals/runners/run_eval.py --offline`: **17/17 benchmark tasks PASS quality gates**
- `python evals/runners/run_goldset.py`: **passed** (hermetic offline scorer writes `evals/gold/last_goldset_results.json`)
