"""Override-write regression test for the sandbox guard (W3-IMPL-13, T-014).

Verifies that experiment code rebinding globals()["_ALLOWED_WRITE_ROOT"]
cannot escape the sandbox write containment — the W3-IMPL-12 fix binds the
write root at definition time (default argument), so rebinding the global is
a no-op and any write outside the workdir is denied.

This test MUST fail against the unfixed guard (rebinding works -> write
succeeds -> status COMPLETED, file exists) and PASS after W3-IMPL-12's fix
is applied (PermissionError -> status FAILED, file absent).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_engine.experiments.runner import LocalExperimentRunner

OVERRIDE_CODE = (
    "globals()[\"_ALLOWED_WRITE_ROOT\"] = \"/tmp\"\n"
    "with open(\"/tmp/escape_test.txt\", \"w\") as fh:\n"
    "    fh.write(\"escape\")\n"
)


def test_sandbox_override_write_cannot_rebind_write_root(platform_ctx):
    runner = LocalExperimentRunner(platform_ctx.cfg)
    target = Path("/tmp/escape_test.txt")
    if target.exists():
        target.unlink()
    ex = runner.execute(
        "proj_sbx_override_write",
        {"code": OVERRIDE_CODE, "timeout_seconds": 15},
    )
    assert ex.status == "FAILED", ex.stderr
    assert "sandbox" in ex.stderr or "PermissionError" in ex.stderr, ex.stderr
    assert not target.exists()
