# Literature Intelligence

`intelligence/literature.py` — understand the literature, not just collect it.

## Clustering

Pure-Python TF-IDF + greedy agglomerative clustering with **centroid linkage**
(single-linkage chaining is avoided). Deterministic; no vector DB required.
Each cluster gets top terms as a label and representative papers.

## Foundational vs recent detection

- **Foundational** = `0.5*citation_norm + 0.3*age_factor + 0.2*topic_centrality`
  Citations matter but never alone (spec #22).
- **Recent-relevant** = recency within window × citation momentum × substance.
  Not a sort by date (spec #23).

## Trends

Publication volume by year with an explicitly scoped observation:

> "Publication volume increased from 2 (2022) to 3 (2023) — observed in 5 collected
> papers only; not a field-wide estimate."

No fortune-telling leaps (spec #26).

## Benchmarks & method comparison

`extract_benchmark_results()` pulls metric/benchmark/value/setting/date from evidence.
`compare_methods()` builds pairwise comparison rows and flags pairs WITHOUT shared
evaluation settings as `comparable_on_shared_benchmarks: false` — metrics from different
settings are never compared blindly (spec #24).

## Reports

- `literature_map.md`: clusters → foundational → recent → trend
- `methods_comparison.md`: guarded comparison table + extracted results with IDs
- `benchmark_analysis.md`: per-benchmark usage, date ranges, saturation signals
