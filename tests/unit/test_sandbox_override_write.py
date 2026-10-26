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


def test_mutation_runner_uses_sys_executable_without_local_venv():
    """0.2: scripts/mutation_check.py must invoke pytest via sys.executable
    and never hard-code a repository-local .venv/bin/python path."""
    import ast
    from pathlib import Path
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "mutation_check.py"
    script = script_path.read_text()
    tree = ast.parse(script)
    string_literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert ".venv" not in string_literals, "mutation_check.py must not hardcode .venv in string literals"
    assert "[sys.executable," in script, "mutation_check.py must invoke pytest via sys.executable"
    assert "M-20" in string_literals, "mutation_check.py must include M-20 for duplicate_rate"
