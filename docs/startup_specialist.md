# Startup Research Specialist (Phase 5)

Evidence-grounded startup intelligence layered on the core research engine.
The specialist owns **domain models, policies, analyzers and reports only** —
retrieval, evidence storage, reasoning stores, jobs, API/MCP/CLI plumbing are
all reused from the platform.

```
EXISTING RESEARCH PLATFORM (sources → evidence → claims → gaps → contradictions)
                              │
                              ▼
                 specialists/startup (this package)
      MarketAnalyzer  CustomerAnalyzer  CompetitorAnalyzer  SignalAnalyzer
                              │
                       OpportunityEngine
                     (patterns → candidates)
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
     BusinessAssumptionBuilder        ValidationPlanner
     (ranked assumptions)             (staged tests, info-gain order)
              └───────────────┬────────────────┘
                              ▼
                      DecisionEngine
        readiness · research-vs-validation · recommendation
```

## Module map

| Module | Responsibility |
|---|---|
| `models.py` | Market, MarketSizeEstimate, Persona, JobToBeDone, CurrentAlternative, CompetitorProfile, PricingPlan, DistributionChannel, TechnologyShift, OpportunityVersion, OpportunityDecision, FounderProfile |
| `repos.py` | `StartupRepos` bundle over per-project DB (`_EXTRA_TABLES` tables); `get_startup_repos(orch)` idiom |
| `policies.py` | Pain taxonomy (14 categories), pain evidence hierarchy, competitor/pricing/distribution taxonomies, source routing, freshness policies, rubric weights, quality-gate requirements, behavioral-uncertainty set |
| `market.py` | Definition-first market modeling; attributed size estimates; cross-validation with `MARKET_SIZE_CONFLICT` (never averaged) |
| `customers.py` | Segments, speculative-flagged personas, JTBD, pain classification + hierarchy, current alternatives (incl. *do nothing*), workflow mapping |
| `competitors.py` | Competitor classification, pricing normalization (raw preserved), distribution channels w/ evidence class, landscape axes from pain data, gap detection, distribution difficulty |
| `signals.py` | Signal independence dedup (10 articles = 1 event), STRONG/MEDIUM/WEAK/UNKNOWN grading, tech-shift detection, why-now assembly (`WHY_NOW_WEAK` when unsupported) |
| `opportunities.py` | Evidence patterns P1–P4 → candidates; transparent rubric; quality gate; counterevidence pairs; why-not-built; moat analysis (evidence-gated); comparison matrix; versioning + decision log |
| `assumptions.py` | Real `Assumption` entities for business hypotheses, ranked by priority = importance × uncertainty × impact × testability |
| `validation.py` | Interview guides + leading-question detector; test design/persist (idempotent); information-gain ranking; staged sequencing; pricing-evidence ladder |
| `decisions.py` | Readiness levels, research-vs-validation transition, research efficiency, recommendation format, founder fit (separate axes) |
| `kb.py` | Cross-project market knowledge base at `<data_dir>/startup_kb/market_kb.sqlite`; seeds later projects on the same market |
| `service.py` | `StartupResearchService`: 8 modes + `run_full_pipeline` (orchestrator hook) |
| `reports.py` | 25-section `startup_research.md`, per-opportunity reports, mandatory epistemic blocks |

## Modes

`MARKET_DISCOVERY`, `MARKET_DEEP_DIVE`, `CUSTOMER_RESEARCH`,
`COMPETITOR_RESEARCH`, `OPPORTUNITY_DISCOVERY`,
`OPPORTUNITY_DUE_DILIGENCE`, `VALIDATION_PLANNING`, `STARTUP_COMPARISON`.

All modes consume the same `build_market_context()` substrate; each returns a
structured dict. CLI/API/MCP are thin wrappers over these.

## Non-negotiable behaviors

1. **Category discipline** — FACT / OBSERVATION / EVIDENCE / INFERENCE /
   HYPOTHESIS / ASSUMPTION / OPPORTUNITY / RECOMMENDATION are never silently
   promoted. Reports close with explicit WHAT WE KNOW / THINK / ASSUME /
   DON'T KNOW / SHOULD TEST blocks.
2. **Opportunities come from evidence patterns** — P1 repeated pain +
   expensive workaround; P2 new enabling tech + underserved workflow;
   P3 regulatory change + manual process; P4 attention signal + unserved
   segment. Unlinked spending only yields a half-strength candidate
   (`link: UNVERIFIED`). No-evidence candidates are labeled SPECULATIVE.
3. **Market sizing is definition-first** — missing definition dimensions
   become research gaps; conflicting figures raise visible
   `MARKET_SIZE_CONFLICT` contradictions and are never averaged.
4. **Behavioral > stated** — reported pain < observed workaround < repeated
   behavior < existing spending < switching < actual payment. Vendor prices
   are NOT customer spending. Price opinion < WTP statement < budget <
   expenditure < actual payment.
5. **Skeptical by default** — high priority requires non-weak demand signals;
   absence of competitors is a warning ("why hasn't this been built?" is
   mandatory); every attractive opportunity gets a strongest-for /
   strongest-against pair plus negative-evidence search.
6. **Research→validation handoff** — when the top uncertainty is customer
   behavior (willingness_to_pay, frequency, severity, switching, retention),
   the engine recommends field validation instead of more web searches, with
   a concrete cheapest test.
7. **No fake precision** — rubric dimensions carry scores AND reasons AND
   qualitative labels; the composite is explicitly a ranking aid.

## Quality gate (#98)

High-priority presentation requires: market defined, customer identified,
pain evidence, alternative identified, competition researched, pricing
researched, why-now investigated, counterevidence searched, critical
assumptions identified, validation path exists. Missing items downgrade the
opportunity and stay visible in `score_breakdown.gate.missing`.

## Decision readiness

`NOT_READY → RESEARCH_READY → VALIDATION_READY → PILOT_READY →
DECISION_READY` — driven by coverage ratio + tested critical assumptions,
never iteration counts.

## Recommendation format

Every opportunity report ends:

```
Recommendation: ...
Evidence supporting: ...
Evidence against: ...
Critical uncertainty: ...
Most important assumption: ...
Best next action: ...
What would change this recommendation: ...
```

## Surfaces

- **CLI**: `research startup {discover,research,customer,competitors,
  opportunity,validate,compare,assumptions,next}`
- **API**: `/startup/discover`, `/startup/research`,
  `/startup/opportunities/{id}`, `/startup/validate`, `/startup/compare`,
  `/startup/competitors`, `/startup/segments`, `/startup/market-map`
- **MCP**: `startup_research`, `startup_discover_opportunities`,
  `startup_get_market_map`, `startup_get_customer_segments`,
  `startup_get_competitors`, `startup_get_opportunities`,
  `startup_analyze_opportunity`, `startup_get_assumptions`,
  `startup_design_validation`, `startup_compare_opportunities`

Permission model unchanged: READ tools are read-only; RESEARCH tools gate
discovery/validation design; implication is downward-only.

## Persistence

New per-project tables via `_EXTRA_TABLES`: `startup_markets`,
`market_sizes`, `startup_personas`, `jtbd`, `alternatives`,
`competitor_profiles`, `pricing_plans`, `distribution_channels`,
`tech_shifts`, `opportunity_versions`, `opportunity_decisions`.
Cross-project KB: `<data_dir>/startup_kb/market_kb.sqlite` using the standard
Database schema with `project_id = kb:<market_slug>`.

## Evals

`evals/datasets/startup_tasks.json`: 3 golden tasks + 3 failure scenarios
(market-size conflict must stay visible; no-visible-competitors warning;
overhyped topic stays low-priority). Gates live in
`evals/runners/run_eval.py::_startup_gates`.

## Known limits

- LLM paths are optional enhancements; deterministic fallbacks cover offline
  runs (mock provider). With no local model, extraction yields little
  evidence — the specialist then honestly reports thin coverage.
- Freshness policies are enforced as labels (`fresh/aging/stale`) and drive
  watcher refresh classes; automatic re-fetch scheduling is Phase 4 watchers'
  job.
