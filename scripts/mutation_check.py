#!/usr/bin/env python
"""Mutation testing harness (stabilization spec §57).

Applies each known-critical mutation to the source, runs its targeted test
subset, reverts, and reports whether the suite DETECTED the mutation.

Usage:
    python scripts/mutation_check.py            # run all mutations
    python scripts/mutation_check.py M-1 M-5    # run a subset

Exit code 0 iff every mutation was detected AND every mutated source file
was restored byte-identically. A failed restore fails the gate: a run that
leaves a mutated file in the tree is a false all-clear.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (id, file, old_snippet, new_snippet, targeted_tests)
MUTATIONS = [
    ("M-1", "src/research_engine/specialists/startup/opportunities.py",
     'priority = ("high" if len(missing) <= 2 and not speculative and demand_ok',
     'priority = ("high" if len(missing) <= 9 and not speculative and demand_ok',
     "tests/invariants/test_system_invariants.py::TestOpportunitySchema"),

    ("M-2", "src/research_engine/reasoning/convergence.py",
     '''        if new_ev == 0 and retrieval_failures > 0:''',
     '''        if (False):''',
     "tests/invariants/test_convergence_semantics.py::TestFailureVsConvergence::test_provider_outage_is_not_convergence"),

    ("M-3", "src/research_engine/pipeline/claim_support.py",
     '''    if verdict in ("CONTRADICTS", "UNRELATED"):
        return EvidenceStatus.REJECTED''',
     '''    if verdict in ("NEVER",):
        return EvidenceStatus.REJECTED''',
     "tests/invariants/test_claim_faithfulness.py::TestIntegration::test_status_mapping_fail_closed"),

    ("M-4", "src/research_engine/storage/reasoning_repos.py",
     '''        existing = self.find_by_natural_key(entity.project_id, key)
        if existing is not None:''',
     '''        existing = None
        if False:''',
     "tests/invariants/test_entity_identity.py::TestBug02Idempotency::test_natural_key_resolution_keeps_identity"),

    ("M-5", "src/research_engine/storage/platform_db.py",
     '''        if fence is not None and current.attempts != fence:
            raise StaleTaskOwner(task_id, worker_id,
                                 current.attempts, fence,
                                 reason="fencing token mismatch")''',
     '''        if False:
            pass''',
     "tests/invariants/test_single_writer.py::TestFencing"),

    ("M-6", "src/research_engine/reasoning/hypothesis_engine.py",
     '''    if sup:
        weights = [_ev_weight(e) for e in sup]
        best_single = max(weights)''',
     '''    if sup:
        weights = [_ev_weight(e) for e in sup]
        best_single = min(1.0, sum(weights) / 3.0 + 0.35 * (len(weights) // 3))''',
     "tests/invariants/test_claim_faithfulness.py::TestHypothesisWeighting"),

    # INV-014: the bind address the server uses and the address the API
    # authorises on must be the same value. M-7 breaks the propagation, M-8
    # breaks the predicate — either one re-opens the "serve the whole API
    # unauthenticated on 0.0.0.0" hole.
    ("M-7", "src/research_engine/cli/main.py",
     '''    ctx.cfg.platform.api.host = host''',
     '''    pass  # MUTATION: effective bind address not propagated to the app''',
     "tests/invariants/test_api_auth_boundary.py"),

    ("M-8", "src/research_engine/api/app.py",
     '''        if is_loopback_host(host_cfg):''',
     '''        if True:  # MUTATION: treat every bind as loopback''',
     "tests/invariants/test_api_auth_boundary.py"),

    # The dependency must resolve the context the same way the routes do.
    # Reading the raw holder left it None at check time, so an app created
    # without an explicit context could never require a token.
    ("M-9", "src/research_engine/api/app.py",
     '''    auth = make_auth_dependency(get_ctx)''',
     '''    auth = make_auth_dependency(lambda: holder.get("ctx"))''',
     "tests/invariants/test_api_auth_boundary.py"),

    # P0-04: a search-provider failure must stay distinguishable from an
    # empty result, all the way to the convergence decision.
    # M-10 flattens the failure back into "no results" at the worker.
    ("M-10", "src/research_engine/pipeline/retrieval.py",
     '''                    q.failed = True''',
     '''                    q.failed = False''',
     "tests/invariants/test_search_failure_semantics.py"),

    # M-11: the provider wrapper swallows the failure again.
    ("M-11", "src/research_engine/providers/search/duckduckgo.py",
     '''            raise SearchProviderError("duckduckgo: all attempts failed")''',
     '''            return []''',
     "tests/invariants/test_search_failure_semantics.py::TestProviderContract"),

    # M-12..M-15: the same contract, per academic provider file. The contract
    # test is parameterised over all six providers, so each site needs its own
    # mutation to prove it is guarded.
    ("M-12", "src/research_engine/providers/academic/openalex.py",
     '''            raise SearchProviderError(f"openalex: {exc}") from exc''',
     '''            return []''',
     "tests/invariants/test_search_failure_semantics.py::TestProviderContract"),

    ("M-13", "src/research_engine/providers/academic/arxiv.py",
     '''            raise SearchProviderError(f"arxiv: {exc}") from exc''',
     '''            return []''',
     "tests/invariants/test_search_failure_semantics.py::TestProviderContract"),

    ("M-14", "src/research_engine/providers/academic/crossref.py",
     '''            raise SearchProviderError(f"crossref: {exc}") from exc''',
     '''            return []''',
     "tests/invariants/test_search_failure_semantics.py::TestProviderContract"),

    ("M-15", "src/research_engine/providers/academic/semantic_scholar.py",
     '''                raise SearchProviderError("semantic scholar: rate limited (429)")''',
     '''                return []''',
     "tests/invariants/test_search_failure_semantics.py::TestProviderContract"),

    # M-16: the duplicate repair must PARSE the payload timestamp, never
    # compare it as text. As text, '...:00Z' sorts AFTER '...:00.500000Z'
    # although it is the older instant, so the repair would keep the newer
    # row and DELETE the genuinely oldest one - silent data loss.
    ("M-16", "src/research_engine/specialists/startup/data_repair.py",
     '''    stamp = parse_payload_timestamp(data.get("created_at"))''',
     '''    stamp = data.get("created_at")''',
     "tests/invariants/test_entity_identity.py::TestBug02Idempotency::test_data_repair_parses_the_timestamp_never_compares_it_as_text"),

    # M-17: the report must state which meaning the count carries. Rendering
    # the new basis as the legacy one is the defect INV-026 forbids.
    ("M-17", "src/research_engine/reports/generator.py",
     '''    RESULTS_COUNT_DISTINCT_URLS: "distinct urls",''',
     '''    RESULTS_COUNT_DISTINCT_URLS: "legacy hits",''',
     "tests/invariants/test_search_outcome_honesty.py::TestReportStatesTheHonestNumbers::test_the_report_renders_both_count_bases_and_the_leg_outcomes"),

    # M-18: the count is DISTINCT canonical http(s) URLs, not raw hits. Two
    # legs on the same provider surface the same documents, so the raw hit
    # count overstates what was found.
    ("M-18", "src/research_engine/pipeline/retrieval.py",
     '''                q.results_count = len({url_canonicalize(h.url) for h in hits
                                       if h.url.startswith(("http://", "https://"))})''',
     '''                q.results_count = len(hits)''',
     "tests/unit/test_stage1_dead_legs.py::TestLegOutcomes::test_the_persisted_query_row_carries_the_count_and_the_outcomes"),

    # C07: next_id() must stay monotonic so two processes never mint the same
    # id; the same-millisecond increment is what makes ids unique within one
    # millisecond. Resetting the random component breaks uniqueness there.
    ("M-19", "src/research_engine/core/ids.py",
     '''            _last_random += 1
            if _last_random >= _RANDOM_LIMIT:''',
     '''            _last_random = 0
            if _last_random >= _RANDOM_LIMIT:''',
     "tests/unit/test_stage1_dead_legs.py::TestUlidIds"),

    # M-20: duplicate_rate must use duplicate_ratio, not rejected_ratio (C18 / 0.3).
    ("M-20", "evals/metrics/eval_metrics.py",
     '''    s.duplicate_rate = repos.evidence.duplicate_ratio(project_id)''',
     '''    s.duplicate_rate = repos.evidence.rejected_ratio(project_id)''',
     "tests/evaluation/test_eval_framework.py::test_duplicate_rate_uses_duplicate_ratio_not_rejection"),

    # M-21: P3-1 rendered report citation coverage must verify [ev_...] against verified_ev_ids.
    ("M-21", "evals/metrics/eval_metrics.py",
     '''                if any(eid in verified_ev_ids for eid in eids):''',
     '''                if True:''',
     "tests/unit/test_phase5_research_quality.py::test_p3_1_citation_coverage_and_report_citation_coverage"),

    # M-22: P3-2 research_gain must discount duplicate quote re-ingestion.
    ("M-22", "src/research_engine/core/orchestrator.py",
     '''            raw_ev_accepted * (1.0 - max(0.0, min(1.0, float(getattr(cur, "duplicate_rate", 0.0))))),''',
     '''            float(raw_ev_accepted),''',
     "tests/unit/test_phase5_research_quality.py::test_p3_2_research_gain_ignores_duplicate_quote_reingestion"),

    # M-23: P3-3 consolidate_claims duplicate count must be recorded on ResearchMetrics.
    ("M-23", "src/research_engine/core/orchestrator.py",
     '''        m.duplicate_claims_this_iter = int(dup_by_iter.get(it, 0))''',
     '''        m.duplicate_claims_this_iter = 0''',
     "tests/unit/test_phase5_research_quality.py::test_p3_3_consolidate_claims_dup_count_persisted_on_metrics"),

    # M-24: P3-6 pain_evidence_class must not classify vendor funding/valuation as actual_payment.
    ("M-24", "src/research_engine/specialists/startup/policies.py",
     '''    if re.search(r"\\b(rais(?:ed|es|ing)|funding(?: round)?|series [a-f]|seed round|valuation|valued at|venture capital|led by .* ventures?)\\b", t) and \\
            not re.search(r"\\b(customers?|users?|clients?|buyers?|retailers?|merchants?|clinics?|shops?)\\s+(?:paid|paying|pays|spent|spend)\\b", t):
        return "reported_pain"''',
     '''    if False:
        return "reported_pain"''',
     "tests/unit/test_phase5_research_quality.py::test_p3_6_pain_evidence_class_separates_vendor_funding_from_customer_payment"),

    # M-25: P3-7 P4 pattern strength must be derived from evidence rather than hardcoded 0.45.
    ("M-25", "src/research_engine/specialists/startup/opportunities.py",
     '''                "strength": p4_strength,''',
     '''                "strength": 0.45,''',
     "tests/unit/test_phase5_research_quality.py::test_p3_7_p4_opportunity_strength_derived_from_evidence"),

    # M-26: P3-9 DecisionEngine.readiness must scope experiments to opportunity_id.
    ("M-26", "src/research_engine/specialists/startup/decisions.py",
     '''                if getattr(e, "opportunity_id", "") == opportunity_id''',
     '''                if True''',
     "tests/unit/test_phase5_research_quality.py::test_p3_9_readiness_scopes_experiments_to_opportunity_id"),

    # M-27: INV-031 engine manifest validator must reject allow_skip_quote_verification=True.
    ("M-27", "src/research_engine/engines/loader.py",
     '''    if manifest.safety.allow_skip_quote_verification:''',
     '''    if False:''',
     "tests/invariants/test_engine_invariants.py::test_inv_031_engine_manifest_cannot_disable_verification_or_egress_locks"),

    # M-28: INV-032 question quality gate must drop questions with empty changes field.
    ("M-28", "src/research_engine/pipeline/questions.py",
     '''        if not q.changes or not q.changes.strip():''',
     '''        if False:''',
     "tests/invariants/test_engine_invariants.py::test_inv_032_user_questions_require_changes_and_record_tier2_user_observation"),

    # M-29: INV-032 user answer provenance must be recorded at tier 2, never tier 1.
    ("M-29", "src/research_engine/pipeline/questions.py",
     '''        source_tier=2,''',
     '''        source_tier=1,''',
     "tests/invariants/test_engine_invariants.py::test_inv_032_user_questions_require_changes_and_record_tier2_user_observation"),

    # M-30: INV-033 negative trail must include rejected evidence items.
    ("M-30", "src/research_engine/services/trail_service.py",
     '''        rejected_ev = [e for e in evidence if e.status == EvidenceStatus.REJECTED]''',
     '''        rejected_ev = []''',
     "tests/invariants/test_engine_invariants.py::test_inv_033_negative_trail_preserves_rejected_evidence_and_single_source_claims"),

    # M-31: INV-035 domain schema validator must forbid $ref.
    ("M-31", "src/research_engine/engines/schema.py",
     '''            if k == "$ref":''',
     '''            if False:''',
     "tests/invariants/test_engine_invariants.py::test_inv_035_domain_schema_forbids_external_or_internal_ref"),

    # M-32: INV-013 RelationalKnowledgeBase.seed_project_from_kb must be a no-op unless use_global_kb=True.
    ("M-32", "src/research_engine/memory/relational_kb.py",
     '''        if not use_global_kb:''',
     '''        if False:''',
     "tests/unit/test_relational_kb.py::test_relational_kb_project_isolation_and_opt_in_seeding_inv_013"),
]


def _run(cmd: list[str]) -> int:
    return subprocess.call(cmd, cwd=ROOT)


def _invalidate_bytecode(target: Path) -> None:
    """Drop the cached bytecode for a mutated file.

    Decision: the mutated file's ``__pycache__`` entry is removed after
    the mutation is reverted.
    Why: CPython validates a cached ``.pyc`` against its source using
    (mtime-seconds, source-size). M-1 rewrites ``<= 2`` to ``<= 9`` -
    the same byte length - and the revert lands in the same second the
    mutation was written, so the MUTATED bytecode still looks valid and
    Python keeps importing it after the source was restored. The symptom
    is a test that fails against a source tree that no longer contains
    the defect (observed: ``assert 'high' in ('medium','low')`` while
    the source said ``<= 2``). A stale ``.pyc`` also outlives the
    mutation run and poisons later, unrelated test runs.
    Constraint: only the mutated file's cache entry is removed; the
    rest of the tree's bytecode cache is left intact.
    """
    cache_dir = Path(importlib.util.cache_from_source(str(target))).parent
    stem = target.stem
    for cached in cache_dir.glob(f"{stem}.*.pyc"):
        try:
            cached.unlink()
        except OSError:
            pass


def _assert_reverted(target: Path, original: str, mid: str) -> bool:
    """Confirm the source really is back to its original text.

    Decision: a failed restore FAILS the gate.
    Why: there is no CI in this repository - this script IS the gate. A
    run that reports "tests DETECTED" while leaving a MUTATED file in the
    tree is a false all-clear: the defect is inherited by the next run
    and by every test run afterwards. The old code printed a WARNING and
    returned a value nobody read, so the exit code stayed 0.
    Constraint: the restore is done from the pre-mutation backup, so a
    failure here means the file on disk differs from the file the
    mutation was applied to - it is never a false alarm.
    """
    current = target.read_text()
    if current == original:
        return True
    print(f"ERROR: {mid} - {target} was NOT restored cleanly")
    return False


def main(selected: list[str]) -> int:
    results = []
    # (mutation id, mutated file, the text the file had before the run)
    mutated: list[tuple[str, Path, str]] = []
    for mid, rel, old, new, tests in MUTATIONS:
        if selected and mid not in selected:
            continue
        target = ROOT / rel
        original = target.read_text()
        if old not in original:
            results.append((mid, "STALE-MUTATION (anchor missing)", False))
            continue
        tmpdir = tempfile.mkdtemp()
        backup = Path(tmpdir) / target.name
        shutil.copy(target, backup)
        restored = True
        try:
            target.write_text(original.replace(old, new, 1))
            _invalidate_bytecode(target)
            rc = _run([sys.executable, "-m",
                       "pytest", "-x", "-q", tests])
            detected = rc != 0
            results.append((mid, f"tests {'DETECTED' if detected else 'SURVIVED'}",
                            detected))
        finally:
            shutil.copy(backup, target)
            _invalidate_bytecode(target)
            restored = _assert_reverted(target, original, mid)
            shutil.rmtree(tmpdir, ignore_errors=True)
        if not restored:
            results.append((mid, "RESTORE FAILED (source left mutated)", False))
        mutated.append((mid, target, original))

    # Safety net: every file this run mutated must be byte-identical to the
    # text it had BEFORE the run. The per-mutation restore above already
    # checks this; this is the independent end-of-run verification, because
    # a file left mutated turns the NEXT run into a false all-clear.
    already_failed = {mid for mid, _, ok in results if not ok}
    for mid, target, original in mutated:
        if target.read_text() == original:
            continue
        print(f"ERROR: verify revert of {target} ({mid})")
        if mid not in already_failed:
            results.append((mid, "VERIFY REVERT FAILED (file differs from the "
                                "pre-run text)", False))

    print("\n=== MUTATION RESULTS ===")
    all_ok = True
    for mid, msg, ok in results:
        print(f"{mid}: {msg}")
        all_ok &= ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
