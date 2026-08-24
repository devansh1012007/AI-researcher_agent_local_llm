# Source System

## Tiers (prior, not proof)

| Tier | Class | Examples |
|---|---|---|
| 1 | primary/official/original | papers, datasets, government, filings |
| 2 | structured secondary | docs, company pages, industry reports |
| 3 | credible journalism | major outlets |
| 4 | opinion/community | blogs, forums |
| 5 | unknown/low | unclassified search hits |

Tier is a *prior* used for ranking and claim-confidence weighting — it never certifies
truth. Source quality, evidence quality and claim confidence are tracked separately.

## Routing

`pipeline/routing.py` maps branch categories → providers, overridable by branch
preferences. Examples: `METHODS → openalex, arxiv, semantic_scholar, web`;
`REGULATIONS → web, government`; `MARKET → web`. `forum`/`government`/
`documentation` are web-search refinements of the generic `web` provider.

## Classification

Deterministic first-pass from URL patterns (`arxiv.org → research_paper/tier1`,
`reddit.com → forum/tier4`, ...). The LLM may refine later; the DB keeps the initial
classification for reproducibility.

## Providers

| Provider | Key | Notes |
|---|---|---|
| OpenAlex | none | scholarly graph, abstracts, citations, OA PDF links |
| Crossref | none | DOI metadata, citation counts |
| arXiv | none | preprints; rate-limited, queries sanitized |
| Semantic Scholar | optional | keyless is heavily rate-limited |
| DuckDuckGo HTML | none | best-effort; challenge pages degrade to empty results |
| SearXNG | self-hosted | recommended for reliable general web |

All results normalize into one internal schema and are cached
(`hash(provider + query)`), so identical searches never repeat within TTL.

## Fetching

Timeouts, exponential backoff on 429/5xx, fail-fast on other 4xx, max response size,
content-type detection, canonical URL extraction, content hashing, global HTTP cache.
Same-content-different-URL documents collapse via content hash (`DUPLICATE`),
and URL dedup happens at discovery time.

## Rejection & audit

Failed/blocked/duplicate sources keep their records with `rejected_reason`
— `sources.md` lists accepted **and** rejected sources with reasons. Ten syndicated
copies count as one source in diversity metrics.
