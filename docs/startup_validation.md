# Startup idea evaluation and validation (`startup_validation`)

`startup` discovers opportunities from a market. `startup_validation` evaluates **one idea
you already have**: is the problem real, who has it, what do they do today, will they pay,
what kills it, and what is the cheapest real test.

```bash
python scripts/validate_idea.py "AI bookkeeping for kirana stores" \
  --problem "owners spend hours on manual GST entries" \
  --customer-segment "kirana store owners in India" \
  --alternative "Tally and a part-time accountant" \
  --price-point "Rs 500 per month" \
  --riskiest-assumption "owners will trust AI with GST filings" \
  --founder-constraints "skills=python,ml; capital=bootstrap; time=15 hours per week"
# same thing: research new --engine startup_validation "<idea card text>"
```

Output: `idea_evaluation.md` (verdict, 12-dimension scorecard with reasons, evidence for and
against, assumptions ranked by risk, tests with success and kill thresholds, readiness, what
would change the verdict, founder fit), plus `validation_plan.md`, `source_trail.md`, and the
standard reports.

## How it differs from `startup`

| | `startup` | `startup_validation` |
|---|---|---|
| Subject | opportunities derived from evidence patterns | the user's stated idea (`USER_IDEA` opportunity) |
| Specialist | `run_full_pipeline` | `run_validation_pipeline` (no discovery) |
| Branch priorities | market breadth | pain, alternatives, pricing, competitors, failures first |
| FUNDING branch | yes | no (investor hype is not validation) |
| Counterevidence | locked on | locked on, and **measured**, not assumed |
| Positive verdict | n/a | `VALIDATE_NEXT` only if counterevidence AND competition were actually researched |

## Policy (INV-036)

* Evidence is linked to the idea only when it overlaps the idea's own words. Zero overlap is
  `NOT_ENOUGH_EVIDENCE`, never "refuted".
* Traction and answers you provide are shown, labelled as your statements, and never stored
  as evidence.
* An undefined `customer_segment` or `problem` gives `DEFINE_THE_IDEA`.
* `STOP_OR_PIVOT` needs a completed real test (`research add-result`) that contradicted a
  hypothesis. Research alone cannot kill an idea.
* The verdict is computed in one read-only place (`StartupResearchService.idea_evaluation_view`).

## Known limits (read before trusting a verdict)

1. Evidence linking is a word-overlap heuristic (at least 2 shared words of 4+ letters).
   Paraphrased evidence can be missed, which produces a conservative `NOT_ENOUGH_EVIDENCE`.
2. The rubric (`score_rubric`) scores "0 researched competitors" as a strong
   competition-weakness. The report flags it as UNRESEARCHED and the verdict guard blocks a
   positive verdict, but the underlying scoring is unchanged.
3. The runtime currently executes a fixed phase order; the pack's `loop:` block is declared
   as the canonical loop so it stays valid when the loop becomes executable.
4. Required-input detection is a substring match on the card labels. Write the card with the
   exact labels (the script does). Answers given to questions refine the evaluation but do
   not change retrieval in the current runtime; put the essentials in the card.
5. `Assumption.status` is never updated by any code path in this repository, so
   `DecisionEngine.readiness()` cannot reach `PILOT_READY` or `DECISION_READY` through normal
   use. The verdict therefore reads contradicted hypotheses, which result ingestion does set.
6. The rubric and verdict are heuristics over desk research. Only customer behaviour
   validates an idea.

## Changes outside the pack (all covered by tests)

* `decisions.readiness()` accepted only `verified/falsified`, while `Assumption.status` uses
  `validated/invalidated`. Both vocabularies are now recognised.
* `_gate_ctx` hard-coded `counterevidence_searched = True`. It now honours a measured value
  when a pipeline provides one; the legacy `startup` path is unchanged.
