# Configuration

One YAML file (`gar.yaml`, `gar.yml` or `config/gar.yaml`), env overrides via
`GAR_SECTION__KEY=value`. See `gar.example.yaml` for a commented template.

## Reference

```yaml
mode: academic|startup              # default mode for new projects

models:
  extractor|reasoning|synthesis:
    provider: ollama|openai_compatible|llama_cpp|mock
    model: <model name>
    base_url: ""                    # override provider default endpoint
    temperature: 0.1
    max_tokens: 2048
    context_tokens: 8000
    timeout_seconds: 120

research:
  max_iterations: 3                 # hard stop
  max_queries_per_iteration: 8
  max_documents: 50                 # parsed documents budget
  max_llm_calls: 300                # hard stop
  max_wall_clock_minutes: 60        # hard stop
  new_evidence_threshold: 0.10      # converged when new/total below this (and >=10 ev)
  duplicate_rate_converged: 0.7     # converged when rejection/dup rate above this
  review_gates_enabled: false       # pause at AFTER_PROBLEM_DEFINITION etc.

network:
  timeout_seconds: 20
  max_retries: 3

resources:
  max_parallel_fetches: 5           # IO-bound; safe to raise
  max_parallel_llm_tasks: 1         # keep at 1 locally
  max_document_size_mb: 10
  max_chunk_chars: 6000             # deterministic chunking target
  chunk_overlap_chars: 400

search:
  web_provider: duckduckgo          # or searxng (+ base_url)
  results_per_query: 10
  academic_providers: [openalex, crossref, arxiv]
  semantic_scholar_api_key: ""
  cache_ttl_hours: 168

storage:
  data_dir: research_data           # per-project workspaces live here
```

## Precedence

defaults < gar.yaml < `GAR_*` environment variables
(e.g. `GAR_MODELS__EXTRACTOR__PROVIDER=mock`).

## Reproducibility

Each project snapshots the effective research/resources config, model roles and prompt
versions into `project.config_snapshot` at creation — visible in every generated
report's Methodology section.
