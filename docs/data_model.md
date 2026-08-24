# Data Model

SQLite is the single source of truth (WAL, FTS5). Tables store JSON entity documents
plus indexed columns for querying. JSONL exports and Markdown reports are derived.

## Entity graph

```
ResearchProject 1──1 ResearchProblem (objective, scope, subquestions, Assumptions)
                1──1 ResearchPlan ──* ResearchBranch (category, importance, required_evidence)
                1──* SearchQuery (text, branch, reason, kind, gain, executed, useful)
                1──* SearchResult ──► Source
                1──* Source (url, canonical_url, tier, type, content_hash, status)
                1──* Document ──* DocumentChunk (sequence, heading, page)
                1──* Claim ── supported_by ──* Evidence ──► chunk/source
                1──* Gap (category, severity, recommended_queries, resolved)
                1──* Contradiction (claim_a vs claim_b, explanation, NOT resolved)
                1──* ResearchMetrics (per-iteration counters & rates)
                1──* Task (audit of harness work items)
```

## Evidence schema (atomic unit of knowledge)

```json
{
  "id": "ev_000042", "project_id": "proj_...",
  "claim_text": "The method improves success rate under clutter",
  "quote": "exact verbatim excerpt...",          // verified against chunk text
  "source_id": "src_000014", "document_id": "doc_000009",
  "chunk_id": "chk_000123", "location": "page 7; chunk 3",
  "source_url": "...", "source_title": "...",
  "source_type": "research_paper", "source_tier": 1,
  "entities": [], "tags": [],
  "numbers": [{"metric":"success rate","value_raw":"+12%","unit":"%","period":"2024","context":"sim"}],
  "confidence": 0.8,
  "status": "EXTRACTED|SUPPORTED|WEAKLY_SUPPORTED|CONTRADICTED|UNVERIFIED|REJECTED",
  "kind": "FACT|INFERENCE|ASSUMPTION",
  "supports": ["clm_000007"], "validation_notes": "exact",
  "iteration": 2
}
```

## Invariants

1. An `INFERENCE`/`ASSUMPTION` claim is never silently upgraded to `FACT`.
2. Claim confidence is **computed** from evidence (tier weight × extractor confidence ×
   corroboration − contradiction penalty), never asserted by an LLM.
3. Numbers are meaningless without metric/unit/period/context (`NumericFact`).
4. Every evidence row carries the full provenance chain:
   `evidence → chunk → document → source → URL`, plus quote hash for dedup.
5. Contradictions are stored with a *possible explanation*; resolution is explicit
   human/workflow action, never automatic.

## FTS5

`evidence_fts` indexes `claim + quote` per evidence item. The CLI
(`research evidence <id> --search "..."`) and future Q&A layers query it directly.
