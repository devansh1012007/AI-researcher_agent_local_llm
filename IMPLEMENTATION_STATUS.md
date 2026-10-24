# Implementation status for the stabilization bundle

Baseline inspected: `ad3ff24d3efc6f8b7af599de76a82b7054371ff2`.

## Included changes

- `.github/workflows/ci.yml`: four independently visible GitHub Actions jobs for the focused sandbox regression + full pytest suite, mutation checks, audit reproductions, and built-wheel verification. Actions are pinned by commit SHA.
- `tests/unit/test_sandbox_override_write.py`: replaces the fixed `/tmp/escape_test.txt` target and destructive cleanup with a target unique to pytest's `tmp_path`; attempts to rebind the vulnerable global to that test-owned directory.
- `scripts/mutation_check.py`: the application script makes the mutation test subprocess use `sys.executable` instead of assuming a repository-local `.venv` and adds M-20 for the duplicate-rate/rejection-rate regression. M-19 remains the ULID mutation.
- `FIX_PLAN.md`, `docs/agent-ops/.../01-work-ledger.md`, and `00-mission.md`: guarded transformations update implementation statuses, preserve historical records while labeling them as snapshots, distinguish source presence from current validation, and defer next-P1 selection until gates run on one candidate SHA.
- `docs/CI.md`: local commands, gate semantics, and separation of live model/network evaluations from PR CI.

## What was actually validated in the authoring environment

- Python syntax compilation of the apply script and standalone sandbox test: passed.
- YAML syntax composition for the workflow: passed.
- Synthetic transformation smoke test for the guarded documentation and mutation-script updates: passed.
- Embedded regression test in the apply script exactly matches the separately packaged test file: passed.

## What was not validated

- The GAR test suite was **not run**.
- The mutation checker, audit reproductions and wheel verification were **not run** against the repository.
- No GitHub Actions run exists for these proposed changes.
- No independent second-agent review was possible in the solo execution environment.
- No branch or pull request was created: the connected GitHub integration rejected branch creation with HTTP 403, and the local runtime could not resolve `github.com`.

Do not treat this bundle as a merged change or as a green CI result. Apply it to the stated baseline, inspect the diff, run all gates, and open a PR for review.
