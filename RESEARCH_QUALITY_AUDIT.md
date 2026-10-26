# RESEARCH QUALITY AUDIT

All items FACT unless tagged. File:line evidence in BUG_AUDIT / agent trace.

## Evidence integrity
- **Quote verification is necessary but radically insufficient** (BUG-09): no claim↔quote faithfulness check anywhere; truncated/inverted claims pass all gates and feed claims→hypotheses→reports. This is the deepest single integrity hole.
- **No evidence-level dedup**: every accepted extraction persists (pipeline/evidence.py:190-192); `find_by_quote_hash` exists but has zero callers. Syndication multiplies facts.
- **FTS duplication** on re-save pollutes retrieval recall ordering (BUG-07).

## Citation integrity
- **citation_coverage is near-tautological**: fraction of claims with non-empty supported_by, computed from DB plumbing, never from report text (eval_metrics.py:91-93). A report citing nothing scores 1.0 if internal claims have support lists. Metric does not measure citation practice.
- Reports embed ev_* ids but regeneration mixes vintages when a single writer fails mid-run (partial regeneration); no snapshot frontmatter to detect this.

## Convergence honesty
- **"duplicate_rate" = rejection ratio** (orchestrator.py:581): >70% hallucinated-extraction rate reports as CONVERGED ("duplicate rate too high").
- **Dead provider == saturation**: zero new evidence drives new_evidence_rate <0.10 → stop reason CONVERGED; indistinguishable from genuine saturation in state.
- Budget exhaustion lands in state COMPLETED via synthesis path (caveat only in info.md prose).
- dup_count telemetry always 0 (initialized, never incremented — evidence.py:199).

## Gain metrics
- research_gain counts rows, not information: +0.5/accepted row and +1/domain delta → one press release syndicated across 10 domains yields gain ≈16 from a single true fact; paraphrases beyond SequenceMatcher 0.86 even count as multiple claims.

## Contradiction handling
- Specialist conflict rows structurally defeat the analyzer (BUG-10) — the one place where temporal/scope/measurement classification matters most is exactly where it can't run; verdict UNRESOLVED then suppressed from explanations.
- Academic-path contradictions (claim-linked) do analyze correctly.

## Startup reasoning quality
- Severity/frequency aggregates inherit syndication inflation with **no independence correction downstream** of a 0.86 string-similarity threshold; legacy cluster threshold 0.25 cosine is looser still.
- P4 opportunity severity is a hardcoded constant (0.45), not evidence-derived; funding vocabulary leaks into payment-class demand (BUG-15) letting hype reach "high priority".
- Frequency fallback in materialize divides corpus-wide recurring pains across every candidate.
- wtp_evidence now requires linkage (fixed earlier), but economic_value still accepts any payment-class pain in support list — same leak channel as BUG-15.
- Vendor-vs-customer price distinction exists for pain hierarchy but market sizing (BUG-05) mis-parses years/percent/funding as market value; symbolic vs written currencies ($5B vs "USD 5 billion") land in different buckets so real conflicts go unflagged.

## Hypothesis quality
- score_hypothesis sum-over-tiers lets ten tier-5 whispers outvote one tier-1 shout — contradicts documented invariant (evidence_quality.py:11) and ignores the platform's own max-based, independence-aware aggregator.
- Confidence floored at 0.25 with zero support — an unevidenced hypothesis displays non-trivial confidence.
- RefinementLoop bypasses the lifecycle machine (.status direct set), the exact pattern AGENTS.md forbids.
- Tie-bias toward generation order (BUG-14, suspected).

## Methodology/validation quality
- MethodologyDesigner multi-tier + critic is sound; startup confounder set sensible.
- Validation tests carry pre-registered criteria and critic checks (weak-commitment, sample, preset thresholds) — good.
- Gap: success criteria live inside decision_note strings; nothing enforces immutability at result time (post-hoc edit possible via update paths). [HYPOTHESIS — not exploited in code today]

## Verdict
The system's *scaffolding* for honesty (tiers, provenance, gates, critics) is unusually strong; four specific mechanisms currently undercut it:
1) claim-faithfulness unchecked, 2) count-based gain/severity aggregation,
3) metric mislabeling (rejection=duplicate; silence=convergence),
4) hypothesis confidence formula contradicting the evidence-quality module.
