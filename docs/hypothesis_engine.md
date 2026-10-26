# Hypothesis Engine & Methodology Designer (Phase 3)

## The reasoning layer

Sits on top of the evidence graph; never bypasses the harness. All LLM output is
validated; all persistence goes through repositories.

```
gaps/contradictions ──► HypothesisGenerator ──► COMPETING sets (+ null/artifact)
                              │                    (spec #8: never ask "most likely"
                              ▼                     before generating rivals)
                       HypothesisCritic ──► structured defects
                              ▼
                       RefinementLoop (max 2, explicit stop reasons)
                              ▼
                       rank_hypotheses(objective=...)
```

## Hypotheses

- First-class entity with origin provenance (`evidence|contradiction|gap|assumption|user`)
  and refs — no hypothesis without provenance (spec #99).
- Falsification conditions required; missing ones are flagged `UNFALSIFIABLE` and
  degrade quality (spec #100/#41).
- Generation always produces a family: causal + alternative mechanism + null/artifact,
  linked via `alternative_of`.
- Assumptions become first-class `Assumption` entities with the transparent priority
  `importance × impact_of_failure × uncertainty × test-ease` — consequential-and-cheap
  first (spec #18).
- Lifecycle state machine (PROPOSED→…→SUPPORTED/FALSIFIED/…): illegal transitions raise.
  Result ingestion walks legal paths only (`_walk_path`), never bypasses.
- Versions are immutable snapshots with change reason + confidence delta (spec #14).
- Scoring is multi-dimensional (support/opposition/testability/falsifiability/parsimony/
  explanatory_power/feasibility/novelty) — confidence derives from support minus
  opposition minus critic defects; speculation without evidence is capped at 0.25.
- Ranking objectives configurable: balanced | novelty | feasibility | impact (spec #70).

## Critic

Deterministic checks (unfalsifiable, unsupported, restates-evidence, correlation/causation
conflation, missing discriminating tests vs rivals) plus advisory LLM critique.
Defects persist on the hypothesis for traceability.

## Methodology designer

Three tiers per hypothesis (cheap_fast / balanced / high_rigor) with explicit
independent/dependent/control variables, confounder candidates, baseline ladder
(naive → existing → strong → ablated-internal), hypothesis-tied metrics, ablation plan,
and PRE-REGISTERED success/failure/inconclusive criteria (spec #29). Statistical notes
scale by tier; cheap_fast explicitly forbids significance claims.

**MethodologyCritic** flags: undefined criteria, weak baseline coverage, undefined
variables, missing ablations, unanalyzed leakage, missing reproducibility block,
metric/hypothesis mismatch.

## Startup validation designer

Business hypothesis chain per opportunity (CUSTOMER/MARKET/WILLINGNESS_TO_PAY/DISTRIBUTION).
Test type follows the assumption category — WTP gets preorders (payment evidence),
not surveys (spec #36/#102). Every test carries bias risks, numeric success/failure
thresholds to fix BEFORE running, cost estimate, and an explicit evidence-hierarchy class.
Staged sequencing: problem → WTP → distribution → retention; each stage gates the next.

## Results & knowledge update

Manual ingestion (`research add-result`) → verdict classified against PRE-REGISTERED
criteria (post-hoc overrides recorded as overrides) → result becomes first-class
EXPERIMENT_RESULT-provenance evidence (tier 1 first-hand, distinct from web sources)
→ hypothesis state/confidence updated qualitatively with explicit reasoning —
no fake Bayes (spec #62). Raw results are never overwritten by interpretation.

## Decision layer (`research next`)

Classifies each open uncertainty: informational → more research; empirical → design a
test; user-only → ask. Experiments awaiting human approval always surface first
(spec #77 — the system designs, humans execute). Decision readiness = visible factor
breakdown + research debt list, never presented as objective truth.
