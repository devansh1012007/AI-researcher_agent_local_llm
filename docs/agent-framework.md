# Subagent Framework

Every mandatory subagent in this repo (context-gathering, phase review,
red-team, final review) is spawned from one of the briefs in this file.

**Why a framework.** A subagent is a separate agent context that must NOT
inherit the author's assumptions — that separation is the entire point
(AGENTS.md §2.1). But a bare prompt produces inconsistent reviews: different
depth, different output shape, and findings that cannot be compared across
phases. These briefs pin the contract so every review answers the same
questions with the same evidence standard.

**The rule that makes it work:** the brief carries the *task*, never the
author's *conclusions*. A reviewer that is told "I fixed the forum leg, check
it" will confirm the fix. A reviewer that is told "here is the requirement
and the diff, find what is wrong with it" will find something.

---

## 1. Roles

| Role | When | May modify files? | Output |
|---|---|---|---|
| `context` | Before any change (AGENTS.md §2.1) | No | Context report: affected files, expected behavior, risks, required tests |
| `review` | After every atomic phase (§2.3) | No | Findings with severity + evidence + suggested fix |
| `redteam` | Before finalizing a high-risk design (§2.4) | No | Failure modes of the design itself |
| `final` | Before completion, on the whole diff (§2.4) | No | Verdict + blocking issues |

A reviewer **never** edits the code it reviews. It reports; the author fixes.

---

## 2. Shared brief preamble

Paste this into EVERY subagent prompt, above the role-specific part:

```
You are a read-only investigator on the repo at /home/devansh/AI-researcher_agent_local_llm.
Do NOT modify any file. Do NOT run the test suite. Do NOT commit.

Ground every claim in the code you actually read, and cite file:line for each
one. If you cannot verify a claim from the source, say so explicitly rather
than asserting it. Distinguish what you VERIFIED from what you INFERRED.
Do not propose designs unless asked. Do not soften findings: a green suite is
evidence that tests pass, NOT evidence that the change is correct.

Repo conventions you must respect and check against:
- AGENTS.md is binding (read it). Especially: §5 invariants, §7 anti-slop,
  §11 testing philosophy, §16 completion checklist.
- docs/invariants.md is the executable contract list.
- The suite is HERMETIC: it must not open sockets and must not read the
  developer's gar.yaml. tests/conftest.py pins providers to mock/none.
- Reports are derived artifacts: report generation must never write primary
  state (INV-004). One operation = one authoritative path (INV-008).
```

---

## 3. Role briefs

### 3.1 `context` — before a change

```
Context: <2-4 lines: what is being changed, and where in the repo it lives>
Question: <ONE specific question>

Return, in under 60 lines:
1. Findings as [FACT path:line-range] bullets (symbol names, signatures, call sites).
2. What you could NOT determine and why.
3. Anything surprising or contradicting the context above.

Do not speculate without labelling it [ASSUMPTION]. Do not propose designs.
```

### 3.2 `review` — after a phase

The author supplies the **diff** and the **requirements**, not a summary of
what was done.

```
Context: <what the phase was supposed to achieve — the REQUIREMENT, not the
author's account of achieving it>
Files changed: <list>
The diff under review: <git diff output or the file list + what to inspect>

Your job is to BREAK this change, not to confirm it.

Return, in under 90 lines:
1. Findings, each with: severity (critical | major | minor), file:line, what
   is wrong, why it matters, and a suggested fix.
2. What you verified by running (state the command and the actual result).
3. What you could NOT verify and why.
4. Anything in the diff that is unnecessary complexity, scope creep, or a
   convention violation.

Audit specifically for:
- Bugs, regressions, flawed assumptions, integration issues.
- Security, error handling, edge cases, violated invariants.
- Missing error paths (what happens when the provider raises, the file is
  missing, the config is wrong?).
- Tests that would pass without testing the intended behavior, or that mock
  away the thing under test.
- Whether the change actually satisfies the stated requirement.
```

### 3.3 `redteam` — design-level

```
Here is the design under consideration: <design>
Here is the evidence list I gathered: <file:line facts>

How does this design break? Find missed callers, race conditions, migration
hazards, test blind spots, spec contradictions, and ways it produces wrong
results while passing its own tests.

Return, in under 90 lines:
1. Failure modes, ranked by likelihood x impact, each with file:line.
2. For each: the earliest signal that would reveal it, and a mitigation.
3. Anything in my evidence list you believe is WRONG — say so and prove it.
```

### 3.4 `final` — whole-diff verdict

```
Context: <the original requirements for the whole task>
The complete diff: <git diff>

Review the complete diff against the original requirements and the system
architecture. Look for cross-phase interactions, regressions, leftover debug
code, missing documentation, schema/migration problems, test-coverage gaps,
and whether the tests genuinely prove correctness.

Return, in under 100 lines:
1. VERDICT: APPROVE | APPROVE WITH NOTES | BLOCK.
2. Blocking issues (critical/major) with file:line and the fix.
3. Non-blocking notes.
4. The exact commands you ran and their actual output.
5. Any requirement from the original request that is NOT met.
```

---

## 4. Rules for the author (me)

1. **Never tell the reviewer my conclusion.** Give the requirement and the
   diff. If I write "I fixed X", the reviewer will look for whether X is
   fixed — not whether the change is right.
2. **Give the reviewer the file list AND the diff**, so it can spot
   accidental edits to files nobody mentioned.
3. **Ask for severity and evidence on every finding**, not prose. A finding
   without file:line is not a finding.
4. **Verify the reviewer's claims myself** by opening the cited lines
   before acting on them. Subagents are a source of leads, not truth.
5. **A passing suite is not a review.** If the reviewer only ran the tests
   and said "looks good", the review failed.
6. **Repeat the same finding three times = escalate**, do not keep fixing.
7. **The final reviewer must be fresh** — no prior context, so it cannot
   inherit accumulated assumptions.

---

## 5. Gates the author runs (never delegated)

The reviewer *reports* on these; the author *runs* them, because a subagent
running the suite is a subagent that can misreport its output.

```bash
pytest                            # full suite, offline
pytest tests/invariants           # executable system invariants
python scripts/mutation_check.py  # known-critical mutations MUST be detected
python scripts/reaudit.py         # replays every original audit reproduction
```

---

## 6. Task breakdown and delegation map

The plan (`docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md`)
is split into atomic tasks so that work can be delegated without ambiguity.
Each task lists its change IDs, the files it owns, and the agent type that
should do it.

**Ownership rule: one task = one file set.** Two agents must never edit the
same file concurrently. Where a task is marked `serial`, it must finish
before the next begins.

| Task | Change IDs | Files owned | Agent | Serial? | Depends on |
|---|---|---|---|---|---|
| T1 | C01-C06 | `pipeline/routing.py`, `pipeline/retrieval.py`, `models/research.py`, `platform/watchers.py`, `services/knowledge_service.py`, `reasoning/novelty.py`, `tests/unit/test_stage1_dead_legs.py` | main agent | - | - |
| T2 | C07 | `core/ids.py`, `tests/unit/test_stage1_dead_legs.py` (ids section) | `coder` | yes | T1 |
| T3 | C08, C22 | `specialists/startup/data_repair.py`, `storage/graph_store.py` | `coder` | yes | T2 |
| T4 | C09 part 1 | `core/http_policy.py` (new) | `coder` | yes | T2 |
| T5 | C09 part 2 | `providers/academic/*.py`, `providers/search/duckduckgo.py`, `providers/llm/*.py`, `providers/embeddings/base.py`, `pipeline/fetching.py`, `memory/retrieval.py` | `coder` | yes | T4 |
| T6 | C10, C23 | `core/config.py`, `core/orchestrator.py`, `providers/llm/router.py` | `coder` | yes | T4 |
| T7 | C11, C12 | `core/config.py`, `api/app.py`, `cli/main.py`, `gar.example.yaml`, `.env.example` | `coder` | yes | T6 |
| T8 | C13 | `models/review.py` (new), `models/__init__.py`, `storage/database.py`, `storage/review_repos.py` (new) | `coder` | yes | T7 |
| T9 | C14, C15 | `services/review_service.py` (new), `cli/main.py`, `api/app.py`, `mcp_server/server.py` | `coder` | yes | T8 |
| T10 | C16 | `reports/generator.py`, `reports/synthesis.py` | `coder` | yes | T9 |
| T11 | C17 | `evals/gold/` (new), `evals/metrics/label_metrics.py` (new), `evals/runners/run_goldset.py` (new) | `coder` | yes | T10 |
| T12 | C18, C21 | `evals/metrics/eval_metrics.py`, `pipeline/evidence.py`, `core/orchestrator.py`, `evals/datasets/*.json`, `evals/runners/run_eval.py`, `scripts/mutation_check.py` | `coder` | yes | T11 |
| T13 | C19, C20 | `docs/invariants.md`, `docs/service-boundaries.md`, `docs/development.md`, `README.md`, `FIX_PLAN.md` | `coder` | yes | T12 |
| R1 | - | review of T1 | `code-reviewer` | - | T1 |
| R2 | - | review of T2-T3 | `code-reviewer` | - | T3 |
| R3 | - | review of T4-T7 | `code-reviewer` | - | T7 |
| R4 | - | review of T8-T10 | `code-reviewer` | - | T10 |
| R5 | - | review of T11-T13 | `code-reviewer` | - | T13 |
| R6 | - | final whole-diff review | `code-reviewer` (fresh) | - | T13 |

**Delegation protocol.** For each `coder` task:

1. The main agent writes the brief from §2 + §3.2, plus the task's change
   IDs, the files it owns, the exact acceptance criteria (usually the test
   IDs from the plan), and the explicit instruction to read `AGENTS.md` and
   the plan section for its change IDs.
2. The coder edits ONLY its owned files and runs the targeted tests for its
   change IDs.
3. The main agent verifies: opens the diff, re-runs the gates, and checks
   that no file outside the owned set changed (`git diff --stat`).
4. A `code-reviewer` subagent reviews the result (brief from §3.2, given
   the requirement and the diff — never the coder's account of what it did).
5. The main agent fixes the findings and re-verifies.

**Never delegate:** the gate runs (§5), the plan, the invariant rows' wording,
and the final verdict.

