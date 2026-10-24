# GAR CI + stabilization implementation bundle

This is an **overlay bundle**, not a full source archive. It contains a guarded
script that writes the workflow, CI documentation, safer sandbox regression,
portable mutation runner, duplicate-rate mutation, and status reconciliation into
an existing checkout of `AI-researcher_agent_local_llm`.

## Apply

1. Clone/open `https://github.com/devansh1012007/AI-researcher_agent_local_llm`.
2. Check out a clean working tree at baseline commit
   `ad3ff24d3efc6f8b7af599de76a82b7054371ff2`.
3. Copy `apply_ci_stabilization.py` into that repository root and run:

   ```bash
   python apply_ci_stabilization.py
   git diff --check
   git diff
   ```

The script refuses to edit if the checkout is dirty or the HEAD differs from the
baseline unless you explicitly pass `--allow-non-baseline`. Review all changes
before running tests or committing. It never commits, pushes, or merges.

## Checks to run

```bash
python -m pytest tests/unit/test_sandbox_override_write.py -v
python -m pytest
python scripts/mutation_check.py
python scripts/reaudit.py
python scripts/check_dist.py
```

The GitHub workflow independently executes those gates (the audit reproductions
also invoke the mutation runner internally). Live-network/model research runs
are deliberately excluded from required PR checks.

## Important limitation

The authoring session could inspect remote GitHub source but could not create a
branch or push changes: the connected GitHub integration returned HTTP 403 for
branch creation, and the local environment could not resolve `github.com`. No
repository test command was run and no test result is claimed. After applying
this bundle, run the gates and create a PR from the resulting branch.
