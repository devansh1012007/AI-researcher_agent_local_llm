# Startup Intelligence

`intelligence/startup.py` + `models/startup.py`. Same core engine, startup-specific
extraction and reasoning.

## Extraction (deterministic from evidence)

- **Pain points**: regex-detected complaint language; classified stated vs observed;
  near-duplicate complaints merged with `frequency_signals` counts.
- **Price observations**: currency amounts with billing periods; funding magnitudes
  ($5M) excluded; each observation keeps source + date (temporal snapshots).
- **Market signals**: funding / hiring / regulation / launch / pricing_change /
  acquisition / infrastructure / complaint — aggregated by kind, not counted blindly.
- **Competitors**: graph entities with positioning and traction kept SEPARATE —
  existence != success (spec #78).

## Opportunity discovery

Pain points are clustered (TF-IDF cosine). A candidate opportunity requires
**>=2 distinct pain evidences or pain + corroborating market signal**. Single
uncorroborated complaints never become opportunities.

## Transparent scoring

```
score = 0.3*pain_severity + 0.2*willingness_to_pay_evidence + 0.25*evidence_strength
        + 0.05*competition_pressure + 0.2*timing_evidence
```

Every factor ships with its reason string. No opaque 87/100 numbers.

## Assumption engine & falsification (`intelligence/falsification.py`)

Critical assumptions per opportunity (LLM-assisted, deterministic fallback of the five
universal viability assumptions). Each critical assumption gets a falsification test:

```
assumption -> cheapest_test -> success_condition -> failure_condition -> decision_rule
```

Reports: `market_map.md`, `opportunity_map.md`, `validation_candidates.md`.
CLI: `research competitors`, `research opportunities`, `research map` (startup mode).
