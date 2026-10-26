# Configurable Research Engines (`engines/`)

GAR replaces hardcoded mode `if/else` ladders with declarative **Engine Packs**. Every research mode (`academic`, `startup`, `generic`, or custom domain packs) is defined by a validated `engine.yaml` manifest, optional `schema.json` domain attribute schema, `skills/*.md` playbooks, and optional `prompts/<name>/vN.txt` prompt overlays.

## 1. Engine Pack Directory Layout

```text
engines/<engine_name>/
├── engine.yaml                 # Declarative manifest (schema_version: 1)
├── schema.json                 # Optional restricted JSON Schema 2020-12 for Evidence.attributes
├── README.md                   # Human documentation for the engine pack
├── skills/                     # Domain playbooks injected into {{engine_guidance}}
│   └── *.md                    # Optional frontmatter: phase (clarify|plan|extract|synthesize|all), priority
└── prompts/                    # Optional prompt template overlays
    └── <template_name>/
        ├── v1.txt
        └── v1.meta.yaml
```

### Discovery Precedence (Highest to Lowest)
1. **Project-local pack**: `<project_workspace>/engine/engine.yaml`
2. **Workspace / custom search dirs**: `./engines/<name>/engine.yaml` or `$GAR_ENGINES_DIR/<name>/engine.yaml`
3. **User config pack**: `~/.config/gar/engines/<name>/engine.yaml`
4. **Built-in packs**: `src/research_engine/engines/builtin/{academic,startup,generic}/engine.yaml`

## 2. Six-Layer Effective Configuration Precedence

When a project is created or loaded, GAR resolves effective tunables across six explicit layers (`resolve_effective_config` in `engines/loader.py`):

| Layer | Source | Precedence |
|---|---|---|
| **1** | Built-in `AppConfig` defaults (`core/config.py`) | Lowest |
| **2** | Engine pack `tunables:` (`engine.yaml`) | Overrides Layer 1 |
| **3** | User `gar.yaml` (only fields explicitly set by the user) | Overrides Layer 2 |
| **4** | `GAR_*` environment variables (e.g. `GAR_RESEARCH__MAX_ITERATIONS=5`) | Overrides Layer 3 |
| **5** | Per-project `<project_workspace>/overrides.yaml` | Overrides Layer 4 |
| **6** | Per-run CLI `--set key=value` flags | Highest |

Run `research engine explain <name> --vars` to inspect the resolved value and winning layer (`1:builtin_default` through `6:cli(--set)`) for every tunable.

## 3. Static Validation & Locked Safety Invariants (`INV-030`–`INV-035`)

`research engine validate <name_or_path>` runs 15 static checks before an engine can execute:
- **Closed registries**: Steps (`STEP_REGISTRY`), route legs (`LEG_NAMES`, max 4 legs per branch), structural gap checks (`STRUCTURAL_CHECK_REGISTRY`), reports (`REPORT_REGISTRY`), and convergence metrics (`METRIC_REGISTRY`).
- **Mandatory step ordering (`INV-031`)**: `extract_evidence` must be immediately followed by `verify_and_dedup` in `loop.per_iteration`, and `write_reports` must appear in `loop.synthesis`.
- **State-machine walk**: Simulates transitions across `setup -> per_iteration -> synthesis` (including `pause_after: true` transitions to/from `PAUSED`) against `core/state_machine.py:ALLOWED`.
- **Locked safety gates (`INV-031`, `INV-034`)**:
  - `safety.allow_skip_quote_verification` must be `false`
  - `safety.allow_skip_claim_support` must be `false`
  - `safety.allow_network_in_local_only` must be `false`
  - `extraction.require_verbatim_quote` and `extraction.require_claim_support` must be `true`
  - For `startup`, `safety.require_counterevidence_for_opportunities` must be `true`
- **Restricted JSON Schema 2020-12 (`INV-035`)**: `schema.json` forbids any `$ref` (preventing SSRF or local file inclusion) and validates extracted `Evidence.attributes` field-by-field, dropping invalid fields with `validation_notes` rather than discarding a quote-verified claim.

## 4. CLI, API & MCP Commands

```bash
# List, inspect, validate, explain, diff, or scaffold engine packs
research engine list
research engine show academic
research engine validate ./engines/my_pack
research engine explain startup --vars
research engine diff academic startup
research engine new product_teardown --extends generic

# Create and run projects with an engine pack and --set overrides
research new "Evaluate solid-state battery electrolytes" --engine academic --set max_iterations=4
research questions <project_id>
research answer <project_id> <question_id> "Automotive EV packs"
```

- **REST API**: `GET /engines`, `GET /engines/{name}`, `GET /projects/{project_id}/questions`, `POST /projects/{project_id}/questions/{question_id}/answer`
- **MCP Tools**: `list_engines`, `get_pending_questions`, `answer_question`

## 5. Included Example Researcher Packs (All 3 Ways)

The repository ships three working `example_researcher` packs filled with example/jibrish domain rules (`florb`, `zibble`, `blargle`, `wumpus`, `sprocket`, `qux`) to illustrate all three ways of adding a new researcher agent:

1. **Way 1 — Built-in Engine Pack (`src/research_engine/engines/builtin/example_researcher/`)**:
   - Registered as `example_researcher` (`source_layer="builtin"`).
   - Defines branches `EXAMPLE_ALPHA`, `EXAMPLE_BETA`, `EXAMPLE_JIBRISH`, and `EXAMPLE_WIDGETS`, domain schema attributes (`example_widget_id`, `jibrish_score`, `florb_category`, `example_metric_note`), phase-scoped skills (`example_discovery.md`, `example_planning_jibrish.md`, `example_jibrish_rules.md`), and a pack-local `prompts/evidence_extractor/v1.txt` overlay.
2. **Way 2 — Workspace / External Directory Pack (`engines/example_researcher_workspace/`)**:
   - Registered as `example_researcher_workspace` (`source_layer="workspace"` when discovered from `./engines/`, or `source_layer="path"` when loaded via `load_engine_from_dir("engines/example_researcher_workspace")`).
   - Defines branches `EXAMPLE_SPROCKETS`, `JIBRISH_QUX_FLOW`, and `EXAMPLE_FOOBAR_GAPS` with custom sprocket/qux attributes without touching `src/`.
3. **Way 3 — Inherited / Scaffolded Engine Pack (`engines/example_researcher_inherited/`)**:
   - Registered as `example_researcher_inherited` (`extends: example_researcher`).
   - Inherits all 4 branches, loop steps, and safety rules from `example_researcher` while overriding `clarifier.required_inputs` (`turbo_wumpus_seed`), `tunables` (`max_iterations: 4`, `max_queries_per_iteration: 10`), `schema.json` (`turbo_wumpus_mode`), and `skills/inherited_jibrish_extension.md`.
