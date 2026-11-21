# Human-reviewed research gold set

`gold_items.jsonl` currently contains starter fixtures. They are useful for
testing scorer plumbing, but they are **not** a statistically credible or
independently human-reviewed benchmark. Do not report their scores as model
quality evidence.

## Annotation contract

Each item must include a stable `kind`, a content-derived key, a human label,
and source provenance. New annotations should also include:

- `source_url`: canonical public source URL (DOI landing page is acceptable)
- `source_title` and `published_at`
- `annotator_id` (pseudonymous) and `reviewer_id`
- `rationale`: why the label follows from the source text
- `adjudication`: `single_review`, `double_review_agreed`, or `adjudicated`

For `support` items, store the exact quote and the atomic claim. For
`contradiction` items, store both claims plus the dimensions that differ
(time, population, scope, metric, or polarity). A difference in time or
population is not automatically a logical contradiction. For `opportunity`
items, preserve the decision rubric and a written rationale for the rank.

Before gating a release, assemble at least 40-50 distinct research tasks,
double-review the claim/evidence pairs, adjudicate disagreements, and publish
per-class counts plus precision/recall or agreement intervals. Keep a separate
unseen holdout split. Do not use synthetic labels or model-generated labels as
human gold.

The offline fake-provider benchmark and the human-reviewed gold set answer
different questions. Report them separately.
