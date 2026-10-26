# CI and release gates

The required workflow is `.github/workflows/ci.yml`. It runs on pull requests to
`main`, pushes to `main`, and manual dispatch. All action dependencies are
pinned to immutable commit SHAs; the Python version is explicitly set to 3.12.

## Required gates

| Job | Command | Purpose |
|---|---|---|
| Offline test suite | `python -m pytest` | Complete deterministic test suite, including the focused sandbox regression |
| Critical mutation checks | `python scripts/mutation_check.py` | Every registered critical mutation (`M-1` through `M-26`) must be detected; modified source must be restored byte-identically |
| Original audit reproductions | `python scripts/reaudit.py` | Replay original stabilization reproductions; this script also invokes mutation checks internally |
| Built wheel verification | `python scripts/check_dist.py` | Inspect the actual wheel for prompt templates, dependency metadata, and importability |

The mutation gate and audit job intentionally remain separate status checks. The
reaudit script currently calls the mutation runner itself, so some mutation work
is repeated; this preserves the existing audit contract rather than silently
changing what `reaudit.py` means. If runtime becomes excessive, introduce and
review an explicit `--skip-mutations` option before optimizing this duplication.

## Local reproduction

From a clean checkout with project dependencies installed:

```bash
python -m pytest tests/unit/test_sandbox_override_write.py -v
python -m pytest
python scripts/mutation_check.py
python scripts/reaudit.py
python scripts/check_dist.py
```

`AGENTS.md` recommends `.venv/bin/python` for local development. The mutation
runner is made interpreter-portable in this change, so it uses the same
interpreter that launched the script and also works on GitHub-hosted runners
without a repository-local `.venv`.

## Network separation and limitations

The PR workflow runs deterministic tests only; it does not run live research
or real-model evaluations. Live evaluations remain an operator-triggered task
and require the intended model/provider configuration and credentials. Do not
put secrets in committed YAML or enable live-network tests as a required PR
check.

The test suite is designed to use fakes and local fixtures. This workflow does
not claim to provide a runner-level outbound-network firewall: package
installation and wheel build tooling need access to package indexes. Tests that
need an HTTP server should bind only to loopback and must not call live research
providers.

## Evidence and closure rules

A green workflow run proves only that the checks in that run passed on that
commit. It does not prove every audit finding is covered. Record the commit SHA
and link the run when updating `FIX_PLAN.md` and the operations ledger. Do not
mark an issue `CLOSED` merely because implementation exists; distinguish
implementation, focused regression verification, full gates, and review.
