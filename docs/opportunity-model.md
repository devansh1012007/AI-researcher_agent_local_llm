# Canonical Opportunity Model (INV-010)

One engine: `specialists/startup/opportunities.py` + `service.run_mode`.
The legacy intelligence/startup discovery/scoring paths are retired from all
production callers (CLI, reports, orchestrator fallback removed).

Score contract (score_breakdown.schema_version=2):
  factors: pain_severity, pain_frequency, economic_value, wtp_evidence,
           market_size, competition_weakness, distribution,
           technical_feasibility, timing, retention_potential,
           defensibility_potential, evidence_strength  (each 0..1)
  labels: qualitative per factor; reasons: cited basis per factor
  gate: quality-gate checks + priority (high requires <=2 missing dims AND
        non-weak demand signals — hype alone stays low)
  total: transparent weighted composite (ranking aid ONLY)

v1 legacy breakdowns render as-is with schema_version=1 and are never
reinterpreted under v2 semantics; rerun discovery to upgrade.
