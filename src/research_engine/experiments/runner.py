"""Sandboxed local experiment execution (spec #34-45).

Design -> register -> approve -> execute -> capture -> analyze -> update.

Safety model (spec #37/#145):
  - subprocess isolation: python -I, fresh cwd inside project workspace
  - resource limits via RLIMIT_CPU / RLIMIT_AS / RLIMIT_NPROC
  - wall-clock timeout with hard kill
  - network denied by default: guard module patches socket before user code
  - filesystem containment via PathSandbox (cwd pinned under the project)
  - raw stdout/stderr/exit code preserved; LLM interpretation never overwrites

Reproducibility block (#39): code hash, config, seed, environment, versions.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from research_engine.core.config import AppConfig
from research_engine.security.permissions import PathSandbox

# Runs INSIDE the child process first (via -c wrapper).
# Audit-hook sandbox: denies networking/subprocesses and contains file
# WRITES to the experiment workdir (reads stay open so imports work).
_SANDBOX_GUARD = r"""
import os as _os
import sys as _sys

_ALLOWED_WRITE_ROOT = _os.environ.get("GAR_EXPERIMENT_WORKDIR", "")
_DENY_NET = _os.environ.get("GAR_EXPERIMENT_NETWORK", "") != "1"

def _guard(event, args):
    if _DENY_NET and event in ("socket.connect", "socket.getaddrinfo",
                               "socket.bind"):
        raise PermissionError(
            "network access disabled by experiment sandbox")
    if event == "subprocess.Popen":
        raise PermissionError(
            "process spawning disabled by experiment sandbox")
    if event == "open" and len(args) >= 3:
        path, mode, flags = args[0], args[1], args[2]
        if not isinstance(path, (str, bytes, _os.PathLike)):
            return
        writable_flags = (_os.O_WRONLY | _os.O_RDWR | _os.O_CREAT |
                          _os.O_APPEND | _os.O_TRUNC)
        try:
            is_write = bool(flags & writable_flags) or any(
                c in str(mode) for c in ("w", "a", "+", "x"))
        except TypeError:
            is_write = False
        if is_write and _ALLOWED_WRITE_ROOT:
            p = _os.path.abspath(
                path.decode() if isinstance(path, bytes) else str(path))
            root = _os.path.abspath(_ALLOWED_WRITE_ROOT)
            if not p.startswith(root + _os.sep) and p != root:
                raise PermissionError(
                    f"write outside experiment sandbox denied: {p}")

_sys.addaudithook(_guard)
"""

_RUNNER_TEMPLATE = """
import json, sys, os
sys.argv = [{argv!r}]
exec(compile(open({entry!r}, encoding='utf-8').read(), {entry!r}, 'exec'))
"""


class ExperimentExecution:
    def __init__(self):
        self.experiment_id = ""
        self.status = "PENDING"
        self.exit_code: int | None = None
        self.stdout = ""
        self.stderr = ""
        self.duration_s = 0.0
        self.timed_out = False
        self.artifacts: list[str] = []
        self.metrics: dict = {}
        self.manifest: dict = {}
        self.workdir = ""


class LocalExperimentRunner:
    def __init__(self, cfg: AppConfig | None = None):
        self.cfg = cfg or AppConfig.load()

    def execute_registered(self, project_id: str, experiment_id: str) -> dict:
        """Full loop for a registered Phase 3 Experiment entity (spec #34)."""
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.storage.reasoning_repos import ReasoningRepos
        orch = Orchestrator.load(self.cfg, project_id)
        rr = ReasoningRepos(orch.db)
        exp = rr.experiments.get(experiment_id)
        if exp is None:
            raise ValueError(f"experiment not found: {experiment_id}")
        if exp.awaiting_approval and not exp.approved_by_user:
            return {"status": "BLOCKED",
                    "reason": "awaiting human approval (spec #45)"}
        spec = self._spec_from_methodology(rr, exp)
        execution = self.execute(project_id, spec,
                                 experiment_id=experiment_id)
        # persist result rows + artifacts manifest
        result = self.persist_result(rr, orch.ws.root, execution)
        return {"status": ("COMPLETED" if execution.exit_code == 0 else
                           "TIMEOUT" if execution.timed_out else "FAILED"),
                "result_id": result["id"],
                "exit_code": execution.exit_code,
                "metrics": execution.metrics}

    # ----------------------------------------------------------- execution
    def execute(self, project_id: str, spec: dict,
                experiment_id: str = "") -> ExperimentExecution:
        """Run a local python experiment per spec dict:

            {"entrypoint": "experiment.py", "code": "...",  # either path or inline
             "configuration": {...}, "seed": 42}
        """
        ex_cfg = self.cfg.platform.experiments
        root = Path(self.cfg.storage.data_dir).resolve()
        _ = ex_cfg  # referenced below via self.cfg.platform.experiments
        sandbox = PathSandbox.for_data_dir(root)
        workdir = root / project_id / "experiments" / \
            (experiment_id or f"run_{int(time.time())}")
        workdir.mkdir(parents=True, exist_ok=True)
        sandbox.validate_write(workdir)

        ex = ExperimentExecution()
        ex.experiment_id = experiment_id
        ex.workdir = str(workdir)

        entry = workdir / "experiment.py"
        if spec.get("code"):
            entry.write_text(spec["code"], encoding="utf-8")
        elif spec.get("entrypoint"):
            src = Path(spec["entrypoint"])
            entry.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            raise ValueError("experiment needs 'code' or 'entrypoint'")
        sandbox.validate_read(entry)

        config = spec.get("configuration", {})
        seed = int(spec.get("seed", 42))
        config_path = workdir / "config.json"
        config_path.write_text(json.dumps({"seed": seed, **config}))

        timeout_s = float(spec.get("timeout_seconds", ex_cfg.timeout_seconds))
        mem_bytes = int(spec.get("memory_mb", ex_cfg.memory_mb)) * 1024 * 1024
        cpu_s = int(spec.get("cpu_seconds", ex_cfg.cpu_seconds))
        network_on = bool(spec.get("network_enabled", ex_cfg.network_enabled))

        preexec = self._limits(mem_bytes, cpu_s) if sys.platform == "linux" else None
        cmd = [sys.executable, "-I", "-c",
               _SANDBOX_GUARD +
               _RUNNER_TEMPLATE.format(entry=str(entry), argv=f"experiment.py")]
        child_env = self._child_env()
        child_env["GAR_EXPERIMENT_WORKDIR"] = str(workdir)
        if network_on:
            child_env["GAR_EXPERIMENT_NETWORK"] = "1"
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, cwd=str(workdir), capture_output=True, text=True,
                timeout=timeout_s, env=child_env,
                preexec_fn=preexec)
            ex.exit_code = proc.returncode
            ex.stdout = proc.stdout[-100_000:]
            ex.stderr = proc.stderr[-50_000:]
        except subprocess.TimeoutExpired as exc:
            ex.timed_out = True
            ex.exit_code = None
            ex.stdout = ((exc.stdout or ""))[-100_000:] if isinstance(
                exc.stdout, str) else ""
            ex.stderr = ((exc.stderr or "") + "\n[sandbox] wall-clock timeout "
                         f"after {timeout_s}s")[-50_000:]
        except PermissionError as exc:
            ex.exit_code = -1
            ex.stderr = f"[sandbox] resource limit hit at spawn: {exc}"
        ex.duration_s = round(time.time() - t0, 2)
        ex.status = ("COMPLETED" if ex.exit_code == 0 else
                     "TIMEOUT" if ex.timed_out else "FAILED")

        # artifacts + metrics + reproducibility manifest
        ex.artifacts = sorted(
            p.name for p in workdir.glob("*")
            if p.name not in ("experiment.py", "config.json") and p.is_file())
        metrics_path = workdir / "metrics.json"
        if metrics_path.exists():
            try:
                loaded = json.loads(metrics_path.read_text())
                if isinstance(loaded, dict):
                    ex.metrics = loaded
            except ValueError:
                pass
        ex.manifest = {
            "experiment_id": experiment_id,
            "seed": seed,
            "config": config,
            "code_hash": hashlib.sha256(
                entry.read_bytes()).hexdigest()[:16],
            "config_hash": hashlib.sha256(
                config_path.read_bytes()).hexdigest()[:16],
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_s": ex.duration_s,
            "network_enabled": network_on,
            "limits": {"memory_mb": mem_bytes // (1024 * 1024),
                       "cpu_seconds": cpu_s, "wall_timeout_s": timeout_s},
        }
        (workdir / "manifest.json").write_text(json.dumps(ex.manifest, indent=2))
        (workdir / "stdout.txt").write_text(ex.stdout)
        (workdir / "stderr.txt").write_text(ex.stderr)
        return ex

    # ------------------------------------------------------------ plumbing
    @staticmethod
    def _limits(memory_bytes: int, cpu_seconds: int):
        import resource

        def apply():
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            # no new processes from experiments (spec #145)
            nproc = 64
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
            except (ValueError, OSError):
                pass
            os.setpgrp()
        return apply

    @staticmethod
    def _child_env() -> dict:
        """Minimal environment: no credentials leak into experiments (#66)."""
        keep = {"PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "PYTHONHASHSEED"}
        env = {k: v for k, v in os.environ.items() if k in keep}
        for k in list(env):
            if any(s in k.lower() for s in ("key", "token", "secret")):
                del env[k]
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    # -------------------------------------------------- registry + results
    @staticmethod
    def _spec_from_methodology(rr, exp) -> dict:
        """Build an executable spec from stored methodology config."""
        spec: dict = {}
        if getattr(exp, "decision_note", ""):
            try:
                spec = json.loads(exp.decision_note)
            except ValueError:
                spec = {}
        meth = rr.methodologies.get(exp.methodology_id) if exp.methodology_id \
            else None
        if meth is not None and hasattr(meth, "protocol_notes"):
            spec.setdefault("notes", (meth.protocol_notes or "")[:200])
        return spec

    def persist_result(self, rr, workspace_root: Path,
                       ex: ExperimentExecution) -> dict:
        from research_engine.models.reasoning import ExperimentResult
        res = ExperimentResult(
            experiment_id=ex.experiment_id,
            observations=[l for l in ex.stdout.splitlines() if l.strip()][:20],
            metrics=ex.metrics,
            raw_notes=ex.stdout[:4000],
            verdict="",   # verdict assigned by ResultIngestor against criteria
            source_kind="experiment_run")
        res.ensure_id()
        rr.experiment_results.save(res)
        return json.loads(res.model_dump_json())
