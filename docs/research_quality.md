# Research Quality Model

Two axes, never conflated (§5):

**Research quality** — is the answer right and trustworthy?
grounding · citation correctness · source quality · gap coverage ·
contradiction handling · uncertainty honesty (`adaptive/outcomes.quality_dimensions`).

**Process quality** — how much did it cost to get there?
latency · LLM calls · queries · specialists invoked · duplicate retrieval ·
failure rate.

A fast wrong researcher loses to a slow correct one. Strategy improvements
count only when quality is preserved or better AND efficiency improves.

## Dimensions (stored per outcome, kept separate §32)

| dimension | derivation |
|---|---|
| claim_grounded_ratio | claims with ≥1 supporting evidence / claims |
| claim_contradicted_ratio | contradicted / claims |
| avg_source_tier | mean tier of accepted evidence (lower=better) |
| gap_coverage | resolved / total gaps |
| contradiction_integrity | contradictions with both sides identified (INV-009) |
| source_fetch_success | FETCHED+PARSED / sources |
| source_domain_diversity | distinct domains |

## Where it surfaces

- `research quality [pid]` dashboard (CLI) · `/projects/{id}/quality` (API)
  · `get_quality_dashboard` (MCP)
- Per-outcome rows: `research outcome <pid>`
- Specialist trend: `research quality` + `specialist_drift_report`

## High-rigor levels (§45/§46)

STANDARD → DEEP → HIGH_RIGOR add verification passes (quote spot-checks,
counterevidence probes, numerical audit, independent LLM critic), not just
more documents. See `self_critique.md`.
