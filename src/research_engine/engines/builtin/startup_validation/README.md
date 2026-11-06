# Startup Idea Evaluation & Validation Engine (`startup_validation`)

Evaluates **one stated idea**. Use `startup` for market and opportunity discovery;
use this pack when you already have an idea and want to know whether to spend real
time on it.

## Input: the idea card

```text
Evaluate startup idea: <one line>
problem: <who suffers what, in their words>
customer_segment: <the buyer and user, specific>
alternative: <what they do today, including nothing>
price_point: <what you would charge>
riskiest_assumption: <what must be true for this to work>
geography: <where the first customers are>
existing_traction: <interviews, waitlist, revenue, if any; may be none>
founder_constraints: skills=...; capital=...; time=...
```

Only line 1 is mandatory. A field that is present is not asked again; missing fields
become non-blocking questions. Without `problem` and `customer_segment` the verdict is
`DEFINE_THE_IDEA`, because an idea without a defined customer cannot be validated.

Build the text with `python scripts/validate_idea.py --help`, or write it by hand and run
`research new --engine startup_validation "<card>"`.

## Output

`idea_evaluation.md` (verdict, 12-dimension scorecard with reasons, evidence for and
against, assumptions ranked by risk, kill criteria, cheapest next tests, what would change
the verdict), plus the standard reports, `validation_plan.md` and `source_trail.md`.

## Verdicts

`DEFINE_THE_IDEA`, `NOT_ENOUGH_EVIDENCE`, `RESEARCH_MORE`, `VALIDATE_NEXT`,
`REFINE_THE_IDEA`, `COMPARE_ALTERNATIVES`, `STOP_OR_PIVOT` (only after a completed real-world
test, recorded with `research add-result`, contradicted a hypothesis). `VALIDATE_NEXT` requires that counterevidence and competition were actually researched, and
means the desk evidence justifies a real test. It never means the idea will work.

## Locks

Quote verification, claim-support, egress policy and mandatory counterevidence are locked
by the validator and cannot be disabled in `engine.yaml`.

## After you run a real test

```text
research add-result <project> <experiment_id>       # experiment ids are in validation_plan.md
python scripts/validate_idea.py --reevaluate <project>   # new verdict; no research is re-run
```
