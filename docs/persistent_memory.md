# Persistent Memory & Hybrid Retrieval

## Layers

1. **SQLite** — claims, evidence, sources, queries, gaps (source of truth)
2. **FTS5** — keyword search over claim+quote text
3. **Vector store** (`storage/vector_store.py`) — embeddings in SQLite blobs;
   brute-force cosine (fine for laptop-scale); swappable for sqlite-vec/FAISS

## Embedding providers (`providers/embeddings/base.py`)

| provider | needs | notes |
|---|---|---|
| `hashing` | nothing | deterministic feature-hashing; lexical semantics only; default |
| `ollama` | local ollama + embed model | real semantic retrieval |
| `openai_compatible` | /v1/embeddings server | LM Studio/vLLM |

Embeddings are optional by design: unavailable model -> automatic fallback to hashing.

## Retrieval pipeline (`memory/retrieval.py`)

```
question -> FTS5 candidates + vector candidates (+ year filters)
         -> merge -> rerank: 0.7*text_relevance + 0.3*(tier x confidence)
         -> min-relevance floor (irrelevant-but-prestigious sources are dropped)
         -> context assembly: dedup, rank, budget to max_chars, citation IDs preserved
```

## Grounded Q&A (`memory/qa.py`)

`research ask <project> "question"` answers ONLY from the archive:

- LLM composes from provided context with citation IDs, never from its own knowledge
- insufficient evidence is stated explicitly instead of improvised
- response carries answer / evidence / sources / confidence / unknowns
- no model? deterministic evidence-list answer, same citations

## Claim tracing & investigation

- `trace_claim()` returns claim -> evidence -> document URL -> sources + contradictions
- `research trace-claim <id>` prints the chain as JSON
- `research verify <claim_id>` queues a focused adversarial branch (independent
  confirmation / criticism / replication) for the next run

## Snapshots & diffs (`memory/snapshots.py`)

- `research snapshot <project> --label pre` — consistent DB copy + manifest
- `research diff` — added/resolved/new/invalidated between iterations plus
  `research_gain` and quality direction (improved / unchanged / decreased)
- `SourceUpdateDetector` — same URL with different content hash records a version event;
  prior documents are retained (temporal observations, spec #98/#99)
