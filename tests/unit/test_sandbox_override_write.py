"""Regression test for write-root rebinding in the experiment sandbox.

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
