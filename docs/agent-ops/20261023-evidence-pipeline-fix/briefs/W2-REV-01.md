# Brief — W2-REV-01 (CODE REVIEWER) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Independent code review of all Wave 2 C09 egress enforcement source changes. Blind pass first — read the diff and code in context BEFORE reading implementer reports. Verify each implementer's claims against the actual code. Try to break the fixes with concrete inputs/interleavings (host injection, redirect chains, policy bypass).
Your role: code reviewer (READ-ONLY on source — write only your report).

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§15 independent review protocol, §3 No-Band-Aid doctrine)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline)
4. docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md (Wave 2 tasks)
5. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/review-code.md
6. Diff: `git diff 29112d1..HEAD -- src/research_engine/core/orchestrator.py src/research_engine/pipeline/fetching.py src/research_engine/providers/llm/router.py src/research_engine/providers/llm/ollama.py src/research_engine/providers/llm/openai_compat.py src/research_engine/providers/search/duckduckgo.py src/research_engine/providers/embeddings/base.py src/research_engine/providers/academic/openalex.py src/research_engine/providers/academic/crossref.py src/research_engine/providers/academic/arxiv.py src/research_engine/providers/academic/semantic_scholar.py`
7. Implementer reports (read AFTER blind pass): reports/w2-impl/W2-IMPL-05 through W2-IMPL-12
8. COMMS.md from the last WAVE-START
9. http_policy.py: src/research_engine/core/http_policy.py (EgressPolicy contract)

## 3. Task and acceptance criteria
Task: Code review of Wave 2 C09 diff for all 11 provider/source files.
Acceptance criteria:
- VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT
- Every finding: ID, file:line, evidence, severity, recommended fix
- Claims audit: each implementer claim checked against code
- Long-run test: Source / Load / Hostile / Operability / Reversal
- Band-aid hunt: swallowed errors, special-casing, suppressed types, single-call-site fixes
- Check: does `policy.require(host)` actually block non-loopback under LOCAL_ONLY?
- Check: does fetching.py `follow_redirects=False` + per-hop validation prevent redirect-based exfiltration?
- Check: does `build_provider(cfg, policy=None)` default keep backward compat?
- Check: does orchestrator pass policy to ALL 6 providers?
- Optimization pass: DO NOW / DO LATER / NOT WORTH-IT
- ORCH-DIGEST block with verdict, counts, top 3 risks

## 4. Ownership
WRITE-SET: none. READ-ONLY: all source. FORBIDDEN: editing source.

## 5. Parallel siblings
| Agent | Role | Owns |
|---|---|---|
| W2-REV-02 | Test reviewer | test implications, missing tests from W2 NEED items |

## 6. Skip list
- Don't edit source. Don't run full suite.
- W2-IMPL-10 flagged `memory/retrieval.py` as DEFERRED-DEPENDENCY — note this as an open item.

## 7. Environment
Scoped: `git diff 29112d1..HEAD -- <paths>`, `git show <sha>`. Do NOT: full suite, containers.

## 8. Deliverables
Report: reports/w2-review/W2-REV-01.md. Commits: report only. Final message ≤ 8 lines.