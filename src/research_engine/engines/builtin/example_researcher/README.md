# Example Researcher Engine Pack (`example_researcher`)

This built-in engine pack demonstrates **Way 1** of adding a new researcher agent to GAR: placing a complete engine pack directory inside `src/research_engine/engines/builtin/example_researcher/`.

## Included Example & Jibrish Components
- **`engine.yaml`**: Declares branches (`EXAMPLE_ALPHA`, `EXAMPLE_BETA`, `EXAMPLE_JIBRISH`, `EXAMPLE_WIDGETS`), source routing, loop steps, and tunables.
- **`schema.json`**: Validates extracted domain attributes (`example_widget_id`, `jibrish_score`, `florb_category`, `example_metric_note`).
- **`skills/`**:
  - `example_discovery.md` (`phase: clarify`, `priority: 10`)
  - `example_planning_jibrish.md` (`phase: plan`, `priority: 20`)
  - `example_extraction_rules.md` (`phase: extract`, `priority: 15`)
  - `example_synthesis_guide.md` (`phase: synthesize`, `priority: 30`)
- **`prompts/`**: Pack-specific prompt overlays for `problem_clarifier` and `evidence_extractor`.
