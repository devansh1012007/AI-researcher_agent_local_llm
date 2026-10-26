# Brief — W2-DREV-02 (DELTA TEST REVIEWER) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Delta review of Wave 2 improvement test additions only. Review `git diff 67ae1e9..HEAD -- tests/unit/test_egress_enforcement.py` to verify the 24 new egress enforcement tests are correct, deterministic, and actually test what they claim. Your role: delta test reviewer (READ-ONLY).

## 2. Required reading
1. STANDING-ORDERS.md (binding)
2. W2-REV-02.md report (test gap findings)
3. W2-IMPR-01-T-013.md improvement report (test plan)
4. Diff: `git diff 67ae1e9..HEAD -- tests/unit/test_egress_enforcement.py`
5. http_policy.py contract

## 3. Acceptance criteria
- VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT
- All 24 tests exist and cover the P1 list from W2-REV-02 §7
- Each test asserts behavior, not implementation
- Tests are deterministic and isolated
- `policy=None` backward compat tested
- LOCAL_ONLY → RuntimeError before network tested at each enforcement point
- DocumentFetcher 302-to-external refused at hop 2 tested
- ORCH-DIGEST block

## 4. Ownership
READ-ONLY. Write only your report to reports/w2-review/W2-DREV-02.md.
