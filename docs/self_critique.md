# Self-Critique System

Independent review of completed research (§42-§46). The critic produces
FINDINGS ONLY — it never modifies reports or primary state (INV-004).

## Independence requirements (§43)

- Deterministic checks run with NO LLM at all (always available offline).
- The optional LLM pass uses the dedicated `critic_review` prompt template
  and the REASONING-role model — never the synthesis model that produced
  the report, never identical context.
- LLM findings citing unknown ids are DROPPED and counted, so a hallucinating
  critic cannot inject phantom targets.

## Checks by rigor level (`adaptive/critic.rigor_profile`)

| check | STANDARD | DEEP | HIGH_RIGOR |
|---|---|---|---|
| citation audit (dangling evidence refs) | ✓ | ✓ | ✓ |
| unsupported FACT-claim detection | ✓ | ✓ | ✓ |
| quote spot-check vs chunk text | – | 10 samples | 25 samples |
| counterevidence-unprobed detection | – | – | ✓ |
| suspicious-magnitude numerical audit | – | – | ✓ |
| independent LLM critique pass | – | – | ✓ |
| source-concentration bias proxy | ✓ | ✓ | ✓ |

Run it: `research review <pid> [--level HIGH_RIGOR]` ·
`POST /projects/{id}/review` · MCP `review_research`.

## Honest evaluation of the critic itself (§69)

The self-critique benchmark injects KNOWN defects (dangling citations,
unsupported FACT claims, broken quotes) into controlled fixtures and
measures recall. The critic is scored only on controlled cases with known
defects plus real runs reviewed manually — never on self-generated outputs
alone.

## Automatic recheck (§45)

HIGH_RIGOR rechecks run before finalization on request; they are read-only
passes that append review rows and surface critical findings as alerts.
