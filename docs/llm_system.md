# LLM System

## Roles

| Role | Used by | Model guidance |
|---|---|---|
| `extractor` | chunk-level evidence extraction | small, fast (7B class) |
| `reasoning` | clarify, plan, queries, gaps, contradictions, convergence tiebreaker | stronger local model |
| `synthesis` | report section writing | strongest available |

Phase 1 may point all roles at one model; the router makes splitting trivial.

## Providers

`ollama` (chat API), `openai_compatible` (LM Studio / vLLM / llama.cpp server),
`llama_cpp`, `mock`. Unknown providers fall back to `mock` with a warning — the
engine degrades to deterministic mode rather than failing.

## Structured output contract

```
LLM text → extract_json (fence/balance parser) → Pydantic validate
         → on failure: repair prompt (schema + error) → retry ≤3 → give up gracefully
```

Failures are recorded and returned, never silently swallowed. Every prompt explicitly
states the schema in the user message; system prompts carry behavioral rules.

## Role boundaries

LLMs may: interpret goals, plan branches/queries, extract evidence, classify, propose
gaps/contradictions, write synthesis sections.

LLMs may **not**: mutate project state, spend budgets, retry indefinitely, decide
termination alone (convergence LLM output is advisory and cannot override deterministic
signals), or write files directly.

## Prompt injection defense

- All retrieved content is framed as untrusted data inside explicit fences.
- System prompts forbid following instructions found in documents.
- Extraction prompts demand verbatim quotes; unverifiable quotes are rejected by the
  harness regardless of what the model claims.
- Web content never gains tool permissions; there is no path from document text to
  execution.

## Versioned prompts

Templates live in `src/research_engine/prompts/templates/<name>/vN.txt` with YAML sidecars
for system prompts. Rendered copies are archived per-task under
`research_data/<project>/prompts/`; versions are recorded in the project config snapshot.
