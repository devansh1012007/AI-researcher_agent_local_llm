#!/usr/bin/env python3
"""Apply the CI/stabilization changes to a clean checkout of GAR.

This bundle was prepared against main at ad3ff24d3efc6f8b7af599de76a82b7054371ff2.
It intentionally refuses to edit a different revision or a dirty checkout unless
--allow-non-baseline is passed. It never commits, pushes, or opens a PR.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_SHA = "ad3ff24d3efc6f8b7af599de76a82b7054371ff2"

WORKFLOW = r'''name: CI and release gates

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  offline-tests:
    name: Offline test suite
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    env:
      PYTHONUNBUFFERED: "1"
      PIP_DISABLE_PIP_VERSION_CHECK: "1"
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Set up Python
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.12"
      - name: Install project and test dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - name: Run sandbox override-write regression
        run: python -m pytest tests/unit/test_sandbox_override_write.py -v
      - name: Run complete offline test suite
        run: python -m pytest

  mutation-check:
    name: Critical mutation checks
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    env:
      PYTHONUNBUFFERED: "1"
      PIP_DISABLE_PIP_VERSION_CHECK: "1"
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Set up Python
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.12"
      - name: Install project and test dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - name: Verify every critical mutation is detected and reverted
        run: python scripts/mutation_check.py

  audit-reproductions:
    name: Original audit reproductions
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    env:
      PYTHONUNBUFFERED: "1"
      PIP_DISABLE_PIP_VERSION_CHECK: "1"
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Set up Python
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.12"
      - name: Install project and test dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - name: Replay original audit reproductions
        run: python scripts/reaudit.py

  distribution:
    name: Built wheel verification
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    env:
      PYTHONUNBUFFERED: "1"
      PIP_DISABLE_PIP_VERSION_CHECK: "1"
    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Set up Python
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: "3.12"
      - name: Install build tooling
        run: python -m pip install --upgrade pip setuptools wheel
      - name: Verify the built distribution artifact
        run: python scripts/check_dist.py
'''

SANDBOX_TEST = r'''"""Regression test for write-root rebinding in the experiment sandbox.

The target is unique to this test and outside the experiment's work directory.
The attack resets the old guard's global write root to the target's parent.
Against the vulnerable guard the write succeeds and this test fails; with the
fixed guard, whose root is captured in the audit-hook function defaults, the
write is refused before the file is created.
"""
from __future__ import annotations

from research_engine.experiments.runner import LocalExperimentRunner


def test_sandbox_override_write_cannot_rebind_write_root(platform_ctx, tmp_path):
    runner = LocalExperimentRunner(platform_ctx.cfg)
    target = tmp_path / "escape.txt"
    attack_root = str(tmp_path)
    code = (
        f'globals()["_ALLOWED_WRITE_ROOT"] = {attack_root!r}\n'
        f'with open({str(target)!r}, "w") as fh:\n'
        "    fh.write('escape')\n"
    )

    execution = runner.execute(
        "proj_sbx_override_write",
        {"code": code, "timeout_seconds": 15},
    )

    assert execution.status == "FAILED", execution.stderr
    assert "sandbox" in execution.stderr.lower() or "PermissionError" in execution.stderr, execution.stderr
    assert not target.exists(), "the sandbox escape target must not be created"
'''

CI_DOC = r'''# CI and release gates

The required workflow is `.github/workflows/ci.yml`. It runs on pull requests to
`main`, pushes to `main`, and manual dispatch. All action dependencies are
pinned to immutable commit SHAs; the Python version is explicitly set to 3.12.

## Required gates

| Job | Command | Purpose |
|---|---|---|
| Offline test suite | `python -m pytest` | Complete deterministic test suite, including the focused sandbox regression |
| Critical mutation checks | `python scripts/mutation_check.py` | Every registered critical mutation must be detected; modified source must be restored byte-identically |
| Original audit reproductions | `python scripts/reaudit.py` | Replay the original stabilization reproductions; this script also invokes mutation checks internally |
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

`AGENTS.md` recommends using `.venv/bin/python` for local development. The
mutation runner is made interpreter-portable in this change, so it uses the
same interpreter that launched the script and also works on a GitHub-hosted
runner without a repository-local `.venv`.

## Network separation and limitations

The PR workflow runs deterministic tests only; it does not run live research
or real-model evaluations. Live evaluations remain an operator-triggered task
and require the intended model/provider configuration and credentials. Do not
put secrets in committed YAML or enable live network tests as a required PR
check.

The test suite is designed to use fakes and local fixtures. This workflow does
not claim to provide a runner-level outbound-network firewall: package
installation and wheel build tooling need access to package indexes. Tests that
need an HTTP server should bind only to loopback and must not call live research
providers.

## Evidence and closure rules

A green workflow run proves only that the checks in that run passed on that
commit. It does not prove that every audit finding is covered. Record the
commit SHA and link the run when updating `FIX_PLAN.md` and the operations
ledger. Do not mark an issue `CLOSED` merely because the implementation exists;
use distinct states for implementation, focused regression verification, full
gates, and independent review.
'''

PLAN_STATUS_TABLE = r'''**Status reconciled against source inspected at baseline `ad3ff24d3efc6f8b7af599de76a82b7054371ff2` (2026-10-25):** stabilization remains in progress. P0-1, P0-2 and P0-4 have previous verification evidence in their implementation records; P1-11 also has prior hermeticity evidence. The implementation for P0-3, P0-5 and P0-6 is present in the inspected source, as are the routing/watcher changes associated with P1-13 and P1-14. The sandbox override-write test is unsafe because it uses and deletes a shared fixed `/tmp` path; this bundle replaces it with a unique test-owned path. **No final gates have been run by this authoring environment on the candidate changes. Do not mark current-head verification complete until the workflow runs.**

| Area | Current implementation status | Verification status at baseline |
|---|---|---|
| P0-1 packaging | Fix and release-check script present | Previously reported passing; re-run on candidate commit |
| P0-2 API auth boundary | Effective bind address is propagated; external binds require token | Previously reported real-uvicorn 401/401/200; re-run on candidate commit |
| P0-3 entity IDs | Monotonic prefixed ULIDs, cross-process tests and mutation M-19 present | Target and full gates need re-run on candidate commit |
| P0-4 search failure semantics | Provider failure is recorded distinctly from empty results | Previously reported end-to-end verification; re-run on candidate commit |
| P0-5 experiment sandbox | Dedicated guard captures root in callback defaults | Existing sandbox suite reported passing; run corrected override-write test and full gates |
| P0-6 local-only privacy gate | Environment resolution, registry short-circuit and request-time egress guards present | Targeted tests exist; full gates need re-run |
| P1-11 test hermeticity | Test environment pins local/mock providers and developer config overrides | Prior socket-level verification recorded; re-run suite and keep live evaluation out of CI |
| P1-13 / P1-14 routing and watcher | Current route map and watcher use the provider registry and preserve failure outcomes | Relevant stage-1 regression tests exist; full gates need re-run |
| P1-1…P1-7, P1-8…P1-10, P1-12, P1-15…P1-16 | Still open in the plan unless separately evidenced | Re-validate each against current source before scheduling work |

**Execution status:**
- W4 sandbox guard: implementation present; focused exploit regression and full gate on the candidate revision must pass.
- W5 ULID: implementation, ordering tests and mutation M-19 are present; full gate on the candidate revision must pass.
- W6 local-only: local-only resolution, provider construction gating and per-request egress enforcement are present; full gate on candidate revision must pass.
- CI workflow: not yet installed/run by this authoring environment; this bundle adds the files and commands for a checkout at the baseline SHA.

**Status vocabulary:** `OPEN` → `IMPLEMENTED` → `TARGETED TESTS PASSED` → `FULL GATES PASSED` → `REVIEWED/CLOSED`. A prior run or a test file's existence does not establish a passing result on a later commit.'''

P0_3 = r'''### P0-3 Entity IDs collided across processes — **IMPLEMENTATION PRESENT; FINAL GATES PENDING**

The current `src/research_engine/core/ids.py` implements prefixed 26-character
Crockford-base32 ULIDs with a monotonic per-process random component. It also
re-seeds the random component after detecting a fork, avoiding the identical
same-millisecond increment that a forked child could otherwise inherit. Existing
rows retain their legacy IDs; no re-keying migration should be performed because
IDs are part of persisted evidence/claim/source traceability.

Current regression evidence in source:

- `tests/unit/test_stage1_dead_legs.py::TestUlidIds` checks 10,000 IDs in a
  frozen millisecond, format/prefix, and two processes writing to the same DB.
- `tests/unit/test_stage2_id_ordering.py` checks that consumers use persisted
  `created_at` ordering rather than assuming mixed legacy IDs and ULIDs sort
  globally by creation time.
- `scripts/mutation_check.py` uses **M-19** for ULID monotonicity.

This is implementation evidence, not a current run result. Run the ULID tests,
mutation gate and full CI on the candidate SHA before closure. Any old report that
labels M-19 as the duplicate-rate mutation is stale; use a separate mutation ID
for duplicate-rate (added as M-20 by this bundle).

---

'''

P0_5 = r'''### P0-5 Experiment sandbox write-root escape — **IMPLEMENTATION PRESENT; FINAL GATES PENDING**

The current source moves the audit hook into `src/research_engine/experiments/_sandbox_guard.py`.
The callback captures the allowed write root and network-deny flag in default
arguments at function definition time, preventing experiment code executed by
`exec()` from changing the guard's captured root by rebinding a module global.
`runner.py` imports and installs this hook in the isolated child process.

Regression coverage is in `tests/unit/test_sandbox_override_write.py` and the
existing `tests/experiments/` and `tests/security/` suites. The prior regression
test wrote to a fixed `/tmp/escape_test.txt` and deleted it before running,
which could interfere with another process. This bundle replaces that shared
path with a unique `tmp_path` target and directs the simulated attack at that
specific temporary directory.

Closure requires that the targeted test fail against the old vulnerable guard,
pass against the current implementation, leave the target absent, and that the
full suite plus independent security review pass on the same candidate commit.

---

'''

P0_6 = r'''### P0-6 `LOCAL_ONLY` / `privacy_mode` enforcement — **IMPLEMENTATION PRESENT; FINAL GATES PENDING**

The current source appears to enforce the intended guarantee through multiple
layers:

- `PlatformConfig.effective_environment()` maps `offline` to `LOCAL_ONLY`, lets
  `security.local_only` and `security.privacy_mode` force `LOCAL_ONLY`, and maps
  unknown modes to `LOCAL_ONLY` with an error rather than silently upgrading to
  a permissive environment.
- `core/orchestrator.py::build_default_registry()` returns an empty registry
  when the egress policy is strict.
- `core/http_policy.py::EgressPolicy` is passed through provider construction
  and checked at request sites, including redirect hops. Existing egress tests
  cover provider requests and the external redirect boundary.
- `tests/unit/test_local_only_gating.py` checks configuration resolution,
  unknown-mode fail-closed behavior and the empty registry.

The inspected `SecurityConfig` and `gar.example.yaml` no longer expose the old
`respect_robots` promise. Full gates have not been run on the bundle candidate,
so this finding remains implementation-present rather than formally closed.

---

'''

P1_13_14 = r'''### P1-13 / P1-14 Retrieval routing and watcher failure reporting — **IMPLEMENTATION PRESENT; FINAL GATES PENDING**

The current route map and regression suite in `tests/unit/test_stage1_dead_legs.py`
address the previously reported dead `forum` route leg, unavailable provider
legs, duplicated same-query legs and untrusted planner source preferences. The
watcher now obtains providers through `build_default_registry()`, uses the
registry accessors (`get_search` / `get_any`), and stores search failures separately
from unconfigured providers rather than silently flattening both into no hits.

The corresponding current code is in `src/research_engine/pipeline/routing.py`,
`src/research_engine/pipeline/retrieval.py`, and `src/research_engine/platform/watchers.py`.
The implementation is present and dedicated tests exist; the current full suite
must run before these findings can be closed against the latest commit.

---

'''

WAVE_PLAN = r'''## 7. Current execution order and gates

The originally proposed wave table below has been replaced with current-source
status. The wave identifiers in this file are plan waves; identifiers in
`docs/agent-ops/20261023-evidence-pipeline-fix/` describe a separate historical
execution run and should not be cross-read as the same wave numbering.

| Order | Scope | Current state | Acceptance gate |
|---|---|---|---|
| 1 | Sandbox regression safety (P0-5) | Implementation/test present; test path needs to be made unique | Exploit test proves old guard fails, fixed guard blocks write and creates no target |
| 2 | Automated CI gates | Added by this bundle, pending application and run | All four GitHub Actions jobs pass on the same candidate SHA |
| 3 | Reconcile status records | Plan/ledger reconciliation included in this bundle | Status claims name exact SHA and distinguish implementation from verified closure |
| 4 | Final regression run | Not run in authoring environment | Full pytest, mutation checker, reaudit and distribution checks succeed |
| 5 | Independent review | Not available in this solo execution environment | Complete-diff review records findings and dispositions; disclose this process deviation |
| 6 | Next P1 selection | Deferred until gates have evidence | Re-check open P1 findings against candidate source, then select one by impact and reproducibility |

**Required workflow:**

```bash
python -m pytest tests/unit/test_sandbox_override_write.py -v
python -m pytest
python scripts/mutation_check.py
python scripts/reaudit.py
python scripts/check_dist.py
```

The automated workflow runs the sandbox test and full suite, mutation gate,
reaudit, and built-wheel gate. Live-network/model evaluations are deliberately
excluded from required PR checks; see `docs/CI.md`.

---

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise ValueError(f"expected exactly one anchor for {label}; found {n}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    i = text.find(start)
    if i < 0:
        raise ValueError(f"start marker not found for {label}: {start!r}")
    j = text.find(end, i + len(start))
    if j < 0:
        raise ValueError(f"end marker not found for {label}: {end!r}")
    return text[:i] + replacement + text[j:]


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def transform_fix_plan(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_between(text, "**Status:**", "\n\n**Decisions taken", PLAN_STATUS_TABLE + "\n\n", "FIX_PLAN header/status table")
    section0 = r'''## 0. Findings already implemented or previously verified

| Finding | Current evidence | Current closure state |
|---|---|---|
| BUG-01/02/03/04/05/06/08/09/10; BUG-07 FTS resave duplication; BUG-11 event drop counter | Existing source and regression tests | Previous fix evidence exists; current full gates still required |
| P0-1 packaging | `pyproject.toml`, `prompts/registry.py`, `tests/unit/test_packaging.py`, `scripts/check_dist.py` | Previously verified; rerun on candidate SHA |
| P0-2 API auth | `cmd_serve`, `make_auth_dependency`, `tests/invariants/test_api_auth_boundary.py` | Previously verified against real uvicorn; rerun on candidate SHA |
| P0-3 IDs | `core/ids.py`, `TestUlidIds`, `test_stage2_id_ordering.py`, M-19 | Implementation present; current gate pending |
| P0-4 search failure semantics | Provider contract, retrieval worker, convergence tests | Previously verified end-to-end; rerun on candidate SHA |
| P0-5 sandbox write-root | `_sandbox_guard.py`, `runner.py`, override-write regression | Implementation present; corrected regression and current gates pending |
| P0-6 local-only egress | `effective_environment`, default-registry gate, request-time EgressPolicy, local-only/egress tests | Implementation present; current gates pending |
| P1-11 hermeticity | Test configuration pins mock/local providers; previous socket-level probe was recorded | Re-run suite and preserve evidence for candidate SHA |
| P1-13/P1-14 routing/watcher | Current route map, retrieval and watcher implementations; stage-1 regression tests | Implementation present; current full gates pending |

Historical audit labels are preserved in the detailed audit documents. A status
from an earlier commit is not a claim that the current commit passed its tests.

---

'''
    text = replace_between(text, "## 0. Findings that are already closed (do not re-open)", "## 1. P0 — silent correctness / security failures", section0, "FIX_PLAN section 0")
    text = replace_between(text, "### P0-3 Entity IDs collide across processes and silently destroy rows", "### P0-4 A search-provider outage", P0_3, "FIX_PLAN P0-3")
    text = replace_between(text, "### P0-5 Experiment sandbox write-root is rebindable from user code", "### P0-6 `LOCAL_ONLY` / `privacy_mode` are decorative", P0_5, "FIX_PLAN P0-5")
    text = replace_between(text, "### P0-6 `LOCAL_ONLY` / `privacy_mode` are decorative", "## 2. P1 — correctness, honesty, contract", P0_6, "FIX_PLAN P0-6")
    text = replace_between(text, "### P1-13 The \"forum\" route leg resolves to a provider that does not exist", "### P1-15 A search backend", P1_13_14, "FIX_PLAN P1-13/P1-14")
    text = replace_between(text, "## 7. Proposed execution order", "## 8. Explicitly out of scope", WAVE_PLAN, "FIX_PLAN section 7")
    return text


def transform_ledger(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    notice = r'''Historical operations log for run `20261023-evidence-pipeline-fix`.

**Current canonical status is the reconciliation block below.** The detailed
plan/task/wave rows after it are preserved historical snapshots. `pending` in
those rows describes the state during the original run; do not dispatch from
those entries without checking `FIX_PLAN.md` and the current source.

## Current status reconciled against inspected main

Baseline inspected before this bundle: `ad3ff24d3efc6f8b7af599de76a82b7054371ff2`
(2026-10-25). This authoring environment did not execute repository tests or
push a candidate branch, so every current-head gate below remains **NOT RUN**.

| Work item | Source status | Evidence present | Current-head validation |
|---|---|---|---|
| P0-1 packaging | Implemented | Packaging unit tests and `scripts/check_dist.py` | NOT RUN |
| P0-2 API auth | Implemented | `tests/invariants/test_api_auth_boundary.py`; previous real-uvicorn report | NOT RUN |
| P0-3 ULID IDs | Implemented | `core/ids.py`, `TestUlidIds`, stage-2 ordering tests, M-19 | NOT RUN |
| P0-4 failure semantics | Implemented | Search-failure invariant tests and previous end-to-end report | NOT RUN |
| P0-5 sandbox containment | Implemented; override test needs a unique target path | `_sandbox_guard.py`, runner, corrected test included in bundle | NOT RUN |
| P0-6 local-only/privacy | Implementation present | `effective_environment`, registry short-circuit, `EgressPolicy`, local-only/egress tests | NOT RUN |
| P1-11 hermeticity | Test configuration present | `tests/conftest.py`; prior zero-outbound-socket report | NOT RUN |
| P1-13 / P1-14 route and watcher | Implementation appears present | stage-1 route/watcher regression tests and current registry usage | NOT RUN |
| CI automation | Missing on baseline | Workflow and docs included in bundle | NOT RUN |
| Duplicate-rate mutation | Missing as a dedicated mutation | M-20 added by this bundle; M-19 remains reserved for ULID | NOT RUN |

## Required gates for the candidate commit

1. `python -m pytest tests/unit/test_sandbox_override_write.py -v`
2. `python -m pytest`
3. `python scripts/mutation_check.py` (must report every mutation DETECTED and exit 0)
4. `python scripts/reaudit.py` (must exit 0 and report all original reproductions fixed)
5. `python scripts/check_dist.py`
6. GitHub Actions run for the exact candidate SHA, with all four jobs green.
7. Independent complete-diff review. In this solo execution, no separate agent
   was available; that deviation remains open and must not be represented as a
   completed independent review.

The next P1 item is intentionally **not selected here**: select it only after
these gates have run on one candidate SHA and the P1 findings have been checked
against that same source revision.

---'''
    text = replace_once(text, "Orchestrator-owned; source of truth for resume. Updated at every wave boundary.", notice, "ledger current-status insertion")
    text = replace_once(text, "## Plan coverage\n", "## Historical plan coverage (snapshot from 2026-10-24; not current status)\n", "ledger plan-coverage heading")
    text = replace_once(text, "## Tasks\n", "## Historical task ledger (snapshot; statuses may be stale)\n", "ledger task heading")
    text = replace_once(text, "## Waves\n", "## Historical wave records (preserved for audit; use current status block above)\n", "ledger wave heading")
    return text


def transform_mission(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    note = r'''**Historical snapshot notice (2026-10-25):** the original baseline, task ownership
and branch entries in this mission log were recorded at `cd6b948` on 2026-10-23.
They are preserved for provenance, not as current status. The currently inspected
main commit is `ad3ff24d3efc6f8b7af599de76a82b7054371ff2`; reconcile implementation
and current verification using `FIX_PLAN.md` and `01-work-ledger.md`. No final gates
were run by the authoring environment on a candidate commit.

'''
    text = replace_once(text, "## 1. Scope (what we are fixing)\n\n", "## 1. Scope (what we are fixing)\n\n" + note, "mission historical notice")
    updates = {
        "Partial — module + construction gating exist; zero request-time enforcement": "Implementation present across provider request sites and redirect hops; final gates on the candidate SHA are pending",
        "Not done — `_ALLOWED_WRITE_ROOT` still a rebindable module global": "Guard implementation and override-write regression exist; current test uses a shared fixed `/tmp` target and is corrected by this bundle; final gates pending",
        "Partial — `eval_metrics.py:75` sets `rejected_ratio`, not true duplicate ratio": "`duplicate_rate` now uses `duplicate_ratio()` and dedicated tests exist; M-20 is added by this bundle; current mutation gate pending",
        "Not done — INV-029 missing; service-boundaries.md missing review op": "INV-029 and the review-decision operation are present in current documentation",
        "Not done — M-1..M-18 exist; none target `core/ids.py`": "ULID implementation/tests and mutation M-19 are present in current source",
        "Not done — field defined but never read; no gating test": "`local_only`/`privacy_mode`, fail-closed resolution, registry gating and request-time egress tests are present; current full gates pending",
        "Not done — waves W7-W10 open per FIX_PLAN.md §7": "P1/P2/P3 backlog remains open; select the next P1 only after candidate gates run",
    }
    for old, new in updates.items():
        text = replace_once(text, old, new, f"mission status: {old[:32]}")
    return text


def apply(repo: Path, allow_non_baseline: bool) -> None:
    if not (repo / "FIX_PLAN.md").is_file() or not (repo / "pyproject.toml").is_file():
        raise SystemExit(f"{repo} does not look like the GAR repository root")
    if not allow_non_baseline:
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        if head != BASE_SHA:
            raise SystemExit(f"expected baseline {BASE_SHA}, found {head}; use --allow-non-baseline only after reviewing the diff")
        status = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
        if status.strip():
            raise SystemExit("checkout is dirty; commit/stash changes first, or apply manually after reviewing")

    # Preflight all transformation anchors before writing any file.
    plan = (repo / "FIX_PLAN.md").read_text(encoding="utf-8")
    ledger = (repo / "docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md").read_text(encoding="utf-8")
    mission = (repo / "docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md").read_text(encoding="utf-8")
    mutation = (repo / "scripts/mutation_check.py").read_text(encoding="utf-8")
    required = [
        (plan, "**Status:**", "FIX_PLAN header"),
        (plan, "## 0. Findings that are already closed (do not re-open)", "FIX_PLAN section 0"),
        (plan, "### P0-3 Entity IDs collide across processes and silently destroy rows", "FIX_PLAN P0-3"),
        (plan, "### P0-5 Experiment sandbox write-root is rebindable from user code", "FIX_PLAN P0-5"),
        (plan, "### P0-6 `LOCAL_ONLY` / `privacy_mode` are decorative", "FIX_PLAN P0-6"),
        (plan, "### P1-13 The \"forum\" route leg resolves to a provider that does not exist", "FIX_PLAN P1-13"),
        (plan, "## 7. Proposed execution order", "FIX_PLAN execution order"),
        (ledger, "Orchestrator-owned; source of truth for resume. Updated at every wave boundary.", "ledger header"),
        (mission, "## 1. Scope (what we are fixing)\n\n", "mission scope"),
        (mutation, 'rc = _run([str(ROOT / ".venv" / "bin" / "python"), "-m",', "mutation interpreter path"),
        (mutation, '     "tests/unit/test_stage1_dead_legs.py::TestUlidIds"),\n]', "M-19 append anchor"),
    ]
    for contents, anchor, label in required:
        if anchor not in contents:
            raise SystemExit(f"preflight failed: missing {label} anchor {anchor!r}; no changes written")

    # Prepare every change in memory first. If any anchor is stale, fail before
    # writing any repository file; do not leave a half-applied bundle.
    # Make the mutation runner work in any Python environment, including CI.
    mutation = replace_once(
        mutation,
        'rc = _run([str(ROOT / ".venv" / "bin" / "python"), "-m",\n                       "pytest", "-x", "-q", tests])',
        'rc = _run([sys.executable, "-m", "pytest", "-x", "-q", tests])',
        "portable mutation interpreter",
    )
    m19_anchor = '     "tests/unit/test_stage1_dead_legs.py::TestUlidIds"),\n]\n\n\ndef _run(cmd: list[str]) -> int:'
    m20 = r'''     "tests/unit/test_stage1_dead_legs.py::TestUlidIds"),

    # M-20: duplicate_rate must measure duplicate evidence, not rejected
    # evidence. The test fixture distinguishes these two ratios explicitly.
    ("M-20", "evals/metrics/eval_metrics.py",
     's.duplicate_rate = repos.evidence.duplicate_ratio(project_id)',
     's.duplicate_rate = repos.evidence.rejected_ratio(project_id)',
     "tests/evaluation/test_eval_framework.py::test_duplicate_rate_uses_duplicate_ratio_not_rejection"),
]


def _run(cmd: list[str]) -> int:'''
    mutation = replace_once(mutation, m19_anchor, m20, "M-20 duplicate-rate mutation")
    updated_plan = transform_fix_plan(repo / "FIX_PLAN.md")
    updated_ledger = transform_ledger(repo / "docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md")
    updated_mission = transform_mission(repo / "docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md")

    updates = {
        repo / "tests/unit/test_sandbox_override_write.py": SANDBOX_TEST,
        repo / "scripts/mutation_check.py": mutation,
        repo / "FIX_PLAN.md": updated_plan,
        repo / "docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md": updated_ledger,
        repo / "docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md": updated_mission,
        repo / ".github/workflows/ci.yml": WORKFLOW,
        repo / "docs/CI.md": CI_DOC,
    }
    for path, content in updates.items():
        write_text(path, content)

    print("Applied CI/stabilization bundle. No tests were executed by this script.")
    print("Next: inspect git diff; then run the five commands in docs/CI.md; then push a branch and review GitHub Actions results.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="GAR repository root (default: current directory)")
    parser.add_argument("--allow-non-baseline", action="store_true", help="skip exact-HEAD/clean-tree guard; use only after manual review")
    args = parser.parse_args()
    try:
        apply(args.repo.resolve(), args.allow_non_baseline)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
