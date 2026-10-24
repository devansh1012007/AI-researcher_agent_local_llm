# Brief — W2-DREV-01 (DELTA CODE REVIEWER) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Delta review of Wave 2 improvement commits only (F-1, F-2, F-3 fixes + new egress tests). Review `git diff 67ae1e9..HEAD -- <paths>` to verify the fixes are correct, complete, and don't introduce regressions. Your role: delta code reviewer (READ-ONLY).

## 2. Required reading
1. STANDING-ORDERS.md (binding)
2. W2-REV-01.md report (findings F-1, F-2, F-3)
3. W2-IMPR-01-T-013.md improvement report (what was fixed)
4. Diff: `git diff 67ae1e9..HEAD -- src/research_engine/core/orchestrator.py src/research_engine/pipeline/fetching.py src/research_engine/providers/search/duckduckgo.py`
5. http_policy.py contract

## 3. Acceptance criteria
- VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT
- F-1: unused `EgressPolicy` import removed from orchestrator.py:15 — verify
- F-2: `httpx.HTTPStatusError` raise restored for 429/503 before body read in fetching.py — verify retry path works
- F-3: `follow_redirects=False` + per-hop `policy.require` redirect loop in duckduckgo.py — verify no exfiltration hole
- No other files changed beyond the 3 source files
- No band-aids introduced
- ORCH-DIGEST block

## 4. Ownership
READ-ONLY. Write only your report to reports/w2-review/W2-DREV-01.md.
