**Short verdict:**  
Your idea is viable, but your current plan is over-scoped, over-recursive, and under-specified where it matters most: **source access, evidence management, evaluation, and local inference constraints**.

If you want the best path:

> Build a **deterministic local orchestration harness** first, not a loose “agent swarm”.  
> Use **MCP only as a tool interface layer later**, not as the core agent architecture.  
> Make the system **evidence-first**, not summary-first.  
> Start with **one core loop + two domains**: research papers and startup research. Finance should come later unless it is the primary user need.

You probably do **not** need fully decentralized subagents at the start. You need a **central controller + specialized workers** with strict budgets, retries, and structured outputs.

---

# 1. The real problem you are solving

You are not really building “a research agent”.

You are building a **local evidence accumulation and reasoning system** that can:

1. Take a fuzzy research goal.
2. Convert it into a precise problem statement.
3. Search reliable sources.
4. Extract grounded facts.
5. Store evidence with citations.
6. Identify gaps.
7. Generate next queries.
8. Synthesize a report.
9. Allow follow-up Q&A.
10. Optionally generate hypotheses, startup niches, methodologies, or investment angles.

That is closer to a **research operating system** than a chatbot.

The hardest part is not “making agents talk”. The hardest part is preventing the system from becoming:

- noisy,
- recursive without convergence,
- hallucination-prone,
- slow on local hardware,
- impossible to debug,
- full of markdown files that no one can query cleanly.

---

# 2. Where your current assumptions are weak

## Assumption 1: “I can beat Google Deep Research Pro mode locally”

**Challenge:** You probably cannot beat it broadly.

Google has:
- massive search infrastructure,
- strong models,
- huge compute,
- mature retrieval pipelines,
- distributed scraping,
- ranking data from billions of queries.

But you **can** beat it in a narrow workflow if you optimize for:

- structured evidence,
- local privacy,
- customizable research modes,
- persistent project memory,
- transparent source trails,
- user-controlled iteration,
- domain-specific schemas.

**Better goal:**  
Do not build “better than Google Deep Research”.

Build:

> “A local, auditable, recursive research workbench for papers, startups, and finance that produces structured evidence with citations.”

That is more defensible.

---

## Assumption 2: “Decentralized subagents are optimal”

**Challenge:** Decentralization adds coordination cost.

On a non-gaming laptop, you do not want many agents independently planning, searching, summarizing, and editing files. That creates:

- duplicated work,
- file conflicts,
- context bloat,
- hallucination cascades,
- uncontrolled token usage,
- slow inference,
- debugging hell.

**Better architecture:**

Use a **central orchestrator** with specialized roles:

- Planner
- Search query generator
- Fetcher
- Extractor
- Verifier
- Critic
- Synthesizer
- Memory manager
- Q&A agent

These can be implemented as separate functions, prompts, or processes, but they should all write to a shared structured state.

**Do not make them autonomous equals.**

Make them workers under a controller.

---

## Assumption 3: “Markdown files are enough as the database”

Markdown is good for human review. It is bad as the primary machine-readable state.

If `info.md` becomes the main database, you will get:

- giant files,
- duplicated claims,
- weak search,
- weak filtering,
- fragile edits,
- poor source tracking,
- difficult confidence scoring,
- poor Q&A retrieval.

**Better design:**

Use:

- **SQLite/JSONL** for structured evidence.
- **Markdown exports** for human-readable reports.
- Optional **vector DB** for semantic Q&A.

Example:

```text
/evidence/evidence.jsonl
/evidence/db.sqlite
/reports/info.md
/reports/problem.md
/reports/hypotheses.md
/reports/methodology.md
/logs/research_log.md
```

Markdown should be generated from structured evidence, not the other way around.

---

## Assumption 4: “Recursive 5–10 loops are the main intelligence mechanism”

Recursion is useful, but dangerous.

If you simply repeat:

> search → read → compress → find gaps → search again

you can get:

- repeated queries,
- marginal new information,
- increasingly generic summaries,
- hallucinated “blind spots”,
- context degradation,
- infinite loop behavior.

You need **stopping conditions**.

Use budgets and convergence metrics:

- max pages,
- max tokens,
- max time,
- max new evidence per cycle,
- max duplicate sources,
- max blind-spot severity,
- diminishing returns detection.

Stop when:

- new evidence < threshold,
- source diversity saturates,
- claims are sufficiently supported,
- user approves,
- budget exhausted.

Do not rely only on “LLM is satisfied”.

---

## Assumption 5: “MCP + skills + tools is enough”

**No. Not for your target reliability.**

MCP is useful for exposing tools, resources, and prompts. It is not a full agent execution framework.

You still need:

- state machine,
- task queue,
- retries,
- schema validation,
- file versioning,
- evidence deduplication,
- budget enforcement,
- human gates,
- logging,
- error recovery,
- evaluation,
- source routing.

So:

> Build a full harness first.  
> Wrap it as MCP later if you want to connect it to other clients/projects.

If you only use MCP + skills + tools, the host LLM will have to manage too much. Local models especially will fail at long-horizon orchestration.

---

# 3. Best architecture for your constraints

## Recommended architecture: “Centralized controller, specialized workers”

```text
User
  |
  v
Research Controller / Harness
  |
  +-- Problem Clarifier
  |
  +-- Research Planner
  |
  +-- Source Router
  |     |-- Paper sources: arXiv, Semantic Scholar, OpenAlex, Crossref
  |     |-- Web sources: search API / SearXNG / DuckDuckGo
  |     |-- Startup sources: HN, Product Hunt, Reddit, news, company pages
  |     |-- Finance sources: EDGAR, Yahoo Finance, investor pages
  |
  +-- Fetcher / Scraper
  |
  +-- Cleaner / Reader
  |
  +-- Extractor Agent
  |
  +-- Evidence Store
  |     |-- SQLite / JSONL
  |     |-- Vector index optional
  |     |-- Markdown export
  |
  +-- Gap Analyzer
  |
  +-- Query Generator
  |
  +-- Critic / Verifier
  |
  +-- Synthesizer
  |
  +-- Q&A Engine
```

This is not “decentralized” in the fashionable sense. It is **modular but controlled**.

That is better for local hardware.

---

# 4. Do you need MCP + skills + tools or full harness?

## Answer: full harness first, MCP later.

### Use a full harness if you need:
- reliable recursive research,
- local inference,
- structured files,
- source validation,
- budget control,
- repeatable evaluation,
- production-like behavior.

### Use MCP if:
- you want to expose your research system to another agent/client,
- you want tools like `search_web`, `read_file`, `query_vector_db`, `write_report`,
- you want future integration with Claude Desktop, IDE agents, or other MCP-compatible clients.

### Best answer:

> Build the core as a Python harness.  
> Expose selected capabilities through MCP later.

Possible MCP tools later:

```text
start_research_project
clarify_problem
run_search_cycle
extract_from_url
get_blind_spots
generate_hypotheses
generate_methodologies
query_research_memory
export_report
```

But the actual recursive loop should be owned by your harness, not by a chat model alone.

---

# 5. Best local model strategy for a non-gaming laptop

You need model tiering.

Do not use one large model for everything.

## Tier 1: Tiny extraction model

Use for:
- extracting facts from cleaned text,
- identifying quotes,
- extracting numbers,
- tagging entities,
- classifying relevance.

Good profile:
- 1B–4B parameters,
- quantized,
- low temperature,
- strict JSON output.

Examples to test:
- Qwen2.5 1.5B / 3B
- Llama 3.2 1B / 3B
- Phi-3.5-mini / Phi-4-mini depending hardware
- Gemma 2B / 4B if practical

## Tier 2: Planner / critic / synthesizer model

Use for:
- query generation,
- blind-spot detection,
- synthesis,
- hypothesis generation,
- methodology design.

Good profile:
- 7B–14B if RAM/GPU allows,
- otherwise best available 3B–8B quantized model,
- structured output,
- lower temperature than creative tasks.

If your laptop is CPU-only, be realistic. A 7B quantized model may be slow. You may need:
- 3B for most tasks,
- 7B only for final synthesis,
- smaller chunk sizes,
- aggressive caching.

## Tier 3: Embedding model

Use for vector search later.

Examples:
- bge-small
- nomic-embed-text
- all-MiniLM-L6-v2
- multilingual-e5-small if needed

## Important rule

The extraction model should not “think” too much.

It should extract:

```json
{
  "relevant": true,
  "claims": [
    {
      "claim": "...",
      "quote": "...",
      "source_url": "...",
      "date": "...",
      "entities": ["..."],
      "numbers": ["..."],
      "confidence": 0.7
    }
  ]
}
```

Let the larger reasoning model synthesize later.

---

# 6. The most important thing you are missing: evidence schema

Your plan focuses too much on files and loops, not enough on the atomic unit of research.

The atomic unit should be an **evidence object**, not a paragraph in `info.md`.

Example:

```json
{
  "id": "ev_001",
  "project_id": "proj_123",
  "mode": "startup",
  "claim": "The Indian D2C skincare market is growing due to rising premiumization.",
  "quote": "Indian beauty and personal care market is expected to grow at...",
  "source_url": "https://example.com/report",
  "source_title": "Example Report",
  "source_type": "industry_report",
  "source_tier": 2,
  "published_date": "2025-08-12",
  "fetched_date": "2026-05-30",
  "entities": ["India", "skincare", "D2C"],
  "numbers": ["CAGR 12%", "market size $10B"],
  "confidence": 0.72,
  "status": "unverified",
  "tags": ["market_size", "growth"],
  "supports": [],
  "contradicts": []
}
```

Then `info.md` becomes a generated report from these evidence objects.

This gives you:

- deduplication,
- source tracking,
- confidence scoring,
- contradiction detection,
- easier Q&A,
- easier finance/startup specialization,
- better anti-hallucination.

---

# 7. Best research loop

Do not make it purely LLM-driven.

Make it a controlled loop:

```text
1. User gives topic
2. Problem Clarifier asks questions if unclear
3. Generate problem.md
4. Generate search plan:
   - entities
   - subquestions
   - source types
   - query candidates
   - required evidence
5. Select top queries by expected information gain
6. Fetch results
7. Clean HTML to text
8. Extract evidence with small model
9. Store evidence objects
10. Deduplicate and cluster claims
11. Critic finds:
    - missing info
    - weak claims
    - contradictions
    - low source quality
    - blind spots
12. Generate next queries
13. Stop if convergence/budget reached
14. Synthesize report
15. Export markdown
16. Index for Q&A
```

This is the core.

Everything else is a mode on top of this.

---

# 8. Research papers mode: best path

For research papers, do not rely mostly on web scraping.

Use structured academic APIs first.

## Best sources

- arXiv API
- Semantic Scholar API
- OpenAlex
- Crossref
- CORE
- PubMed if biomedical
- Unpaywall for open access links
- DBLP for computer science

## Paper evidence schema should include:

```json
{
  "paper_id": "...",
  "title": "...",
  "authors": [],
  "year": 2025,
  "venue": "...",
  "abstract": "...",
  "citation_count": 123,
  "doi": "...",
  "url": "...",
  "pdf_url": "...",
  "claims": [],
  "methods": [],
  "datasets": [],
  "results": [],
  "limitations": [],
  "relevance_score": 0.9
}
```

## Paper research loop

1. User gives topic.
2. Generate keywords and synonyms.
3. Query arXiv/Semantic Scholar/OpenAlex.
4. Rank by:
   - relevance,
   - recency,
   - citation count,
   - venue quality,
   - author reputation,
   - match to problem.
5. Fetch abstracts.
6. Extract claims from abstracts.
7. If PDF available, parse PDF.
8. Extract:
   - research question,
   - method,
   - dataset,
   - results,
   - limitations.
9. Build literature clusters.
10. Identify gaps.
11. Generate literature review.

This will be much stronger than random web scraping.

---

# 9. Startup research mode: best path

Startup research is messier because many important signals are not in clean databases.

You need a mix of:

- search engines,
- startup directories,
- forums,
- product pages,
- job listings,
- news,
- funding announcements,
- Reddit,
- Hacker News,
- Product Hunt,
- app store reviews,
- government data,
- financial filings if public companies are involved.

## Startup evidence categories

```text
market_size
customer_pain
willingness_to_pay
competitor
pricing
distribution_channel
regulatory_barrier
technology_shift
funding_signal
job_posting_signal
user_complaint
alternative_solution
```

## Startup research loop

1. Define problem/domain.
2. Generate segments:
   - customer segment,
   - job-to-be-done,
   - pain point,
   - current alternative,
   - spending signal.
3. Search:
   - “problem phrase”
   - “software for X”
   - “alternative to X”
   - “X complaints”
   - “X pricing”
   - “X market size”
   - “startup funding X”
4. Extract evidence.
5. Score niches using a structured rubric.

Example niche score:

```text
pain severity
frequency
willingness to pay
market size
competitor weakness
distribution access
technical feasibility
regulatory risk
timing
evidence strength
```

Do not let the model just say “this is a good idea”.

Force it to produce:

```json
{
  "niche": "...",
  "target_customer": "...",
  "pain": "...",
  "current_alternative": "...",
  "why_now": "...",
  "evidence": [],
  "risks": [],
  "confidence": 0.6,
  "validation_tests": []
}
```

---

# 10. Finance mode: be careful

Finance mode is high-risk because numbers matter and hallucinations are dangerous.

I would not make finance a first-class MVP unless it is your primary use case.

If you build it:

## Use structured sources where possible

- SEC EDGAR
- company investor relations pages
- earnings call transcripts if accessible
- financial data APIs
- exchange filings
- annual reports
- 10-K / 10-Q
- 8-K
- official financial statements

## Avoid relying on:
- random blogs,
- YouTube summaries,
- low-quality news aggregators,
- outdated metrics,
- unverifiable valuation claims.

## Financial evidence object needs extra fields

```json
{
  "metric": "P/E",
  "value": 24.5,
  "period": "2026-Q1",
  "currency": "USD",
  "source_url": "...",
  "source_tier": 1,
  "verified_against": ["source_2", "source_3"],
  "context": "...",
  "reasoning": "..."
}
```

## Finance anti-hallucination rule

If a number is important, it must have:

- quote,
- source,
- date,
- unit,
- period,
- at least one cross-check if possible.

If not, mark it:

```text
UNVERIFIED
LOW_CONFIDENCE
NEEDS_SOURCE
```

Do not allow final investment conclusions from unverified numbers.

---

# 11. The best anti-hallucination design

Your plan has critic loops, which is good, but not enough.

Use layered grounding.

## Layer 1: Source quality tiers

```text
Tier 1: primary official sources
Tier 2: reputable structured sources
Tier 3: credible journalism / research
Tier 4: forums / blogs / opinions
Tier 5: unknown / scraped noise
```

## Layer 2: Claim status

```text
extracted
supported
weakly_supported
contradicted
unverified
rejected
```

## Layer 3: Evidence requirement

For important claims, require:

```text
claim + quote + url + date + confidence
```

For numerical claims, require:

```text
value + unit + period + source + quote
```

For startup claims, require:

```text
pain evidence + market evidence + competitor evidence
```

For hypotheses, require:

```text
assumptions + evidence + disconfirming evidence + test method
```

## Layer 4: Separate extraction from interpretation

Extractor says:

> “The page says X.”

Reasoner says:

> “This suggests Y.”

The final report must distinguish:

```text
FACT: sourced from evidence
INFERENCE: generated from facts
ASSUMPTION: not yet evidenced
```

This is critical.

---

# 12. Better file structure

Your proposed files are okay, but I would change them.

## Do not use only:

```text
info.md
problem.md
hypothesis.md
methodology.md
```

## Use:

```text
/project.json
/problem.md
/state/
  evidence.jsonl
  claims.jsonl
  queries.jsonl
  sources.jsonl
  gaps.jsonl
/reports/
  info.md
  literature_review.md
  startup_report.md
  finance_report.md
  hypotheses.md
  methodology.md
/logs/
  research_log.md
  iterations.md
  errors.md
/vector/
  index.lancedb or chroma
```

Markdown is for humans. JSON/SQLite is for the system.

---

# 13. Best MVP: do not build all modes yet

Your current plan includes:

- problem clarifier,
- data gatherer,
- hypothesis generator,
- methodology designer,
- startup mode,
- finance mode,
- vector Q&A,
- recursive loops,
- multiple file types,
- local model routing,
- MCP future,
- agent swarms.

That is too much.

## Best MVP

Build this first:

> A local research agent that takes one topic, searches papers and startup-related web sources, extracts evidence into a structured store, identifies gaps, recursively improves 2–3 cycles, and produces a cited markdown report.

That is enough.

### MVP scope

Must-have:

1. Topic input.
2. Problem clarification.
3. Query generation.
4. Source fetching.
5. Text extraction.
6. Evidence extraction.
7. Evidence storage.
8. Gap detection.
9. Next query generation.
10. Final cited report.

Skip for MVP:

- finance mode,
- full methodology mode,
- agent swarm,
- MCP server,
- complex vector Q&A,
- multi-user,
- diagrams,
- fancy UI.

---

# 14. Recommended build order

## Phase 1: Core evidence engine

Build:

```text
topic -> problem.md -> search queries -> fetch -> extract -> evidence.jsonl -> info.md
```

Success means:
- every claim has source,
- no claim appears without citation,
- report is readable.

## Phase 2: Recursive gap loop

Add:

```text
critic -> gaps -> next queries -> new evidence -> updated report
```

Success means:
- second cycle adds meaningful new info,
- no infinite loops,
- duplicate sources reduced.

## Phase 3: Research paper adapter

Add:
- arXiv,
- Semantic Scholar,
- OpenAlex,
- Crossref.

Success means:
- literature review with papers,
- citation metadata,
- research gaps.

## Phase 4: Startup adapter

Add:
- startup source list,
- niche scoring,
- pain/competitor/market extraction.

Success means:
- produces niches with evidence,
- validation tests,
- risks.

## Phase 5: Q&A memory

Add:
- embeddings,
- vector DB,
- retrieval over evidence.

Success means:
- answers cite evidence IDs or URLs.

## Phase 6: MCP/API

Only after the harness works.

---

# 15. Best stack

## Core

- Python 3.11+
- Pydantic for schemas
- SQLite for structured evidence
- JSONL for append-only logs
- httpx for requests
- trafilatura or readability for article extraction
- BeautifulSoup for fallback parsing
- markdown for report generation

## Search

Best if you can use an API:
- Brave Search API
- Serper
- Tavily
- Bing API

If zero budget:
- DuckDuckGo HTML search, but unstable
- self-hosted SearXNG, but may be blocked
- direct APIs where possible: arXiv, Semantic Scholar, OpenAlex, HN Algolia, Reddit, SEC EDGAR

Do not depend only on fragile scraping.

## Local inference

- Ollama or llama.cpp
- quantized GGUF models
- separate extractor and reasoner prompts
- JSON mode if available
- retries and schema validation

## Vector DB

For MVP:
- SQLite FTS5 for keyword search first

Later:
- LanceDB
- Chroma
- sqlite-vec
- FAISS if needed

Do not overcomplicate vector DB early.

---

# 16. Should you use agent swarms?

**Mostly no.**

Agent swarms sound good but often produce:

- duplicated searches,
- conflicting edits,
- high latency,
- high memory use,
- weak accountability.

For your laptop, better to use:

```text
1 controller
N workers
strict task schema
shared evidence store
```

You can parallelize:
- fetching,
- extraction,
- embedding.

But do not parallelize:
- final synthesis,
- file editing,
- state transitions,
- budget decisions.

Those should be centralized.

---

# 17. Second-order effects you are missing

## If you use only markdown files

Second-order effect:

```text
info.md grows
-> context becomes too large
-> model summarizes poorly
-> later cycles lose nuance
-> hallucination increases
-> user trust drops
```

## If you allow recursive loops without convergence metrics

Second-order effect:

```text
more iterations
-> diminishing new evidence
-> model invents gaps
-> searches become generic
-> report becomes bloated
-> user cannot tell what improved
```

## If you use many subagents too early

Second-order effect:

```text
more agents
-> more coordination overhead
-> more inconsistent outputs
-> harder debugging
-> slower local inference
-> less reliable product
```

## If you scrape too aggressively

Second-order effect:

```text
rate limits/blocks
-> unstable retrieval
-> bad data quality
-> legal/ethical risk
-> brittle product
```

## If you prioritize startup/finance/web all at once

Second-order effect:

```text
too many modes
-> weak core loop
-> no mode works well
-> MVP never ships
```

---

# 18. The best possible path forward

If I were building this, I would do this:

## Step 1: Define the core object

Build the `Evidence` object first.

Everything depends on this.

## Step 2: Build a deterministic controller

No full autonomy.

Controller decides:
- what mode,
- what step,
- what budget,
- what tool,
- when to stop.

## Step 3: Build two source adapters

Start with:

1. Academic adapter:
   - arXiv
   - Semantic Scholar
   - OpenAlex

2. Web/startup adapter:
   - search API
   - article extraction
   - HN Algolia
   - Reddit optional
   - Product Hunt optional

## Step 4: Build extraction pipeline

For each source:

```text
fetch -> clean -> chunk -> extract -> validate -> store
```

## Step 5: Build critic loop

Critic should output structured JSON:

```json
{
  "blind_spots": [],
  "weak_claims": [],
  "missing_entities": [],
  "contradictions": [],
  "next_queries": [],
  "stop_reason": null
}
```

## Step 6: Build report generator

Report generator reads evidence DB and outputs:

```text
Executive summary
Key findings
Evidence table
Blind spots
Hypotheses
Recommendations
Sources
```

## Step 7: Add Q&A only after evidence store works

Use hybrid search:

```text
keyword + vector + metadata filtering
```

## Step 8: Wrap as MCP later

Expose stable tools only after the internal system is reliable.

---

# 19. What I would cut from your current plan

Cut or delay:

1. Full finance mode.
2. Fully decentralized subagents.
3. MCP as initial core.
4. Multiple recursive hypothesis loops before core evidence loop works.
5. Methodology generation before enough evidence exists.
6. Vector DB as first dependency.
7. Editing `info.md` directly as primary memory.
8. 5–10 recursive cycles as fixed rule.
9. Agent swarm search.
10. Trying to beat Deep Research broadly.

---

# 20. What I would keep

Keep:

1. Problem clarification.
2. Recursive gap-driven research.
3. Markdown reports.
4. Human review gates.
5. Specialized modes later.
6. Source citations.
7. Blind-spot detection.
8. Hypothesis generation.
9. Startup validation tests.
10. Local-first design.

These are good instincts.

---

# 21. The most important missing pieces

You are missing these more than anything:

## 1. Evaluation set

You need 10–20 benchmark research tasks.

Examples:

```text
- Evaluate the market for AI coding tutors in India.
- Research solid-state battery startups.
- Compare LLM inference optimization techniques.
- Analyze the market for vertical SaaS for clinics.
- Find recent papers on retrieval-augmented agents.
```

For each, define:

- expected sources,
- expected claims,
- expected blind spots,
- expected quality bar.

Without evaluation, you cannot know if the agent is improving.

## 2. Source strategy

The agent is only as good as its sources.

You need:
- allowed domains,
- source tiers,
- APIs,
- fallback search,
- scraping rules,
- rate limits.

## 3. Evidence model

Claims, quotes, sources, confidence, dates.

## 4. Budget controls

Token limits, page limits, time limits, iteration limits.

## 5. Human checkpoints

Do not let it run fully autonomous for too long.

Checkpoints after:
- problem definition,
- first search plan,
- first evidence batch,
- final synthesis.

## 6. Failure recovery

Local models will fail to output JSON.

You need:
- retries,
- schema repair,
- fallback prompts,
- fallback models,
- manual review.

---

# 22. The correct answer to “MCP + skills + tools or full harness?”

**Full harness first.**

Use MCP only as an integration layer.

Why:

- MCP does not solve long-running state.
- MCP does not solve recursion control.
- MCP does not solve evidence consistency.
- MCP does not solve local model weakness.
- MCP does not solve evaluation.

Build:

```text
Python harness + structured tools + SQLite evidence + markdown reports
```

Then later expose:

```text
MCP server
REST API
CLI
```

---

# 23. Best mode design

Instead of separate giant agents, use one core loop with mode-specific schemas.

## Common core

```text
Problem -> Evidence -> Gaps -> Queries -> Synthesis
```

## Mode differences

### Research mode
Focus:
- papers,
- methods,
- datasets,
- results,
- limitations.

### Startup mode
Focus:
- customer pain,
- market size,
- competitors,
- pricing,
- distribution,
- validation.

### Finance mode
Focus:
- financial statements,
- ratios,
- filings,
- management commentary,
- risks,
- valuation.

### Hypothesis mode
Inputs:
- evidence store.
Outputs:
- falsifiable hypotheses,
- assumptions,
- evidence for/against,
- tests.

### Methodology mode
Inputs:
- selected hypotheses.
Outputs:
- experiments,
- data requirements,
- metrics,
- success criteria,
- kill criteria.

This avoids duplicating the entire agent for each mode.

---

# 24. The strongest anti-hallucination rule

The final report should only contain three types of statements:

## 1. Evidenced facts

```text
According to Source X, the market size was $Y in 2025. [source]
```

## 2. Clearly marked inference

```text
This suggests that demand may be rising, but this is inference from limited sources.
```

## 3. Explicit assumption

```text
Assumption: users are willing to pay for this workflow. No direct evidence yet.
```

If a statement cannot be classified as one of these, remove it.

That rule alone will make your system much better than most agent outputs.

---

# 25. Recommended MVP spec

Build this in 2–4 weeks.

## Input

```text
research_topic
mode = research | startup
max_cycles = 3
max_pages = 50
max_queries = 30
```

## Output

```text
problem.md
info.md
sources.md
gaps.md
hypotheses.md
research_log.md
```

## Core loop

```text
1. Clarify problem
2. Generate problem.md
3. Generate 10 queries
4. Fetch top 5 sources per query, max 50 pages
5. Extract evidence
6. Store evidence
7. Critic finds top 5 blind spots
8. Generate next 5 queries
9. Repeat for max_cycles
10. Generate final report
```

## Constraints

- Every claim in final report must cite evidence ID/source URL.
- No final claim without source.
- If model is uncertain, it must say “LOW_CONFIDENCE”.
- If source quality is weak, mark it.
- If data is numerical, include date and unit.

This is a strong MVP.

---

# 26. What to measure

## Quality metrics

- citation precision: are cited sources actually supporting claims?
- citation recall: are important claims sourced?
- blind-spot coverage: did later cycles find real missing info?
- duplication rate: how many repeated sources/claims?
- hallucination audit: sample claims checked manually.
- source diversity: domains, tiers, dates.
- time per research cycle.
- token/model latency.

## Product metrics

- Did the user learn something new?
- Did the report save time?
- Would the user trust it for decisions?
- Did Q&A answers cite correctly?

Without these, you are just building complexity.

---

# 27. Meta-questions you should ask before building

Ask yourself:

1. What exact research task will this agent do better than existing tools?
2. What sources are allowed, reliable, and accessible?
3. What is the minimum evidence required before a claim is accepted?
4. How will I know the agent is not hallucinating?
5. How will I evaluate improvement across iterations?
6. What is the budget per research task?
7. What happens when search fails?
8. What happens when a local model outputs invalid JSON?
9. What human review points are required?
10. What is the smallest version that would already be useful?

If you cannot answer these, the architecture is not ready.

---

# 28. Your biggest strategic mistake right now

You are designing a large multi-mode recursive agent before proving the basic loop works.

The basic loop must be excellent first:

```text
topic -> queries -> sources -> evidence -> gaps -> better queries -> cited report
```

If that loop is weak, adding modes will not fix it.

If that loop is strong, modes become prompt/schema extensions.

---

# 29. Highest-leverage next action

Do not start by building MCP.

Do not start by building agent swarms.

Do not start with finance mode.

Do this:

## Build a vertical slice in 3–5 days

Goal:

> Given one startup/research topic, produce one cited `info.md` from 20–30 sources using a local model, with every claim linked to a source.

Requirements:

1. Use Python.
2. Use SQLite or JSONL for evidence.
3. Use one search source.
4. Use one academic source if research mode.
5. Use one small local model for extraction.
6. Use one larger local model for synthesis if possible.
7. Generate `info.md` automatically.
8. No vector DB yet.
9. No MCP yet.
10. No multi-agent swarm yet.

Test topics:

```text
1. AI agents for local research workflows.
2. Market opportunity for indie hacker AI tools.
3. Recent papers on retrieval-augmented generation agents.
4. Startup opportunities in AI-powered due diligence.
```

If this vertical slice is not good, stop and fix it before adding more modes.

---

# 30. Final recommendation

Your best path is:

```text
Build a local Python research harness.
Use a central controller, not decentralized autonomous agents.
Use structured evidence storage, not only markdown.
Use academic APIs for papers.
Use controlled web search for startup research.
Use small local models for extraction.
Use a stronger local model for synthesis/critique.
Use recursion with budgets and convergence checks.
Use MCP later as an interface, not as the core.
Delay finance mode until the core evidence loop is excellent.
```

If you want the strongest version of this project, make it:

> “A local, citation-first research engine that turns messy web and paper data into structured, auditable knowledge.”

Not:

> “A giant autonomous multi-agent swarm that tries to do everything.”

The first is buildable. The second will likely collapse under its own complexity.