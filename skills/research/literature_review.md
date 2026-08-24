# Skill: Literature Review (academic mode)

## Objective
Organize a research landscape (not paper-by-paper summaries): foundational work, major
directions, method comparison, datasets/benchmarks, recent developments, open problems.

## Source preferences
Tier 1 first: peer-reviewed papers, preprints, datasets. Citation count as recency-
independent signal; publication date as recency signal. Prefer venues over aggregators.

## Evidence requirements
Extract per relevant paper: problem, method family, dataset/benchmark, headline result,
baselines compared, stated limitations. Numbers require metric + unit + period + context.

## Reasoning rules
- Compare methods on shared benchmarks only; never mix incomparable metrics.
- Negative results and failure analyses are first-class findings.
- Contradictory results are preserved with both sources; never averaged away.

## Failure conditions
- Only secondary commentary found → mark literature base weak.
- Benchmark fragmentation detected → record as gap (incomparable results).

## Output schema
`literature_review.md`: Foundational Work · Major Research Directions · Method Comparison ·
Datasets and Benchmarks · Recent Developments · Open Problems — every claim cited by
evidence ID.
