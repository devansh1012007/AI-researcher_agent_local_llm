"""Tool permission engine + filesystem sandbox (spec #30/#33/#62-65).

Capabilities, not shells. Every external interface (MCP/API/CLI plugins)
declares the permission it needs; the engine grants only what the client
was configured with. Default clients get READ — minimal privileges.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path


class Permission(str, Enum):
    READ = "READ"                        # inspect projects/evidence/reports
    RESEARCH = "RESEARCH"                # start/pause/cancel research jobs
    WRITE = "WRITE"                      # add results/results ingestion
    EXECUTE_EXPERIMENT = "EXECUTE_EXPERIMENT"  # run sandboxed experiments
    ADMIN = "ADMIN"                      # everything; never default


# implied permissions: higher tiers include lower ones (READ always implied
# by anything above it).
IMPLIED: dict[Permission, set[Permission]] = {
    Permission.READ: {Permission.READ},
    Permission.WRITE: {Permission.READ, Permission.WRITE},
    Permission.RESEARCH: {Permission.READ, Permission.RESEARCH},
    Permission.EXECUTE_EXPERIMENT: {Permission.READ, Permission.WRITE,
                                    Permission.EXECUTE_EXPERIMENT},
    Permission.ADMIN: set(Permission),
}


class PermissionDeniedError(PermissionError):
    def __init__(self, required: str, action: str):
        super().__init__(
            f"permission denied for '{action}': requires {required}; "
            "client was not granted this capability")


class PermissionEngine:
    def __init__(self, granted: set[Permission] | None = None):
        # DEFAULT: read-only (spec #33 — minimal privilege)
        self.granted: set[Permission] = granted or {Permission.READ}

    def grant(self, *perms: Permission) -> None:
        self.granted.update(perms)

    def has(self, required: Permission) -> bool:
        if Permission.ADMIN in self.granted:
            return True
        # A grant of a HIGHER tier implies lower ones (RESEARCH -> READ),
        # never the reverse: holding READ must not satisfy RESEARCH.
        implied_by_granted = set().union(
            *(IMPLIED[g] for g in self.granted)) if self.granted else set()
        return required in implied_by_granted

    def require(self, required: Permission, action: str) -> None:
        if not self.has(required):
            raise PermissionDeniedError(required.value, action)


class ToolSpec:
    """Declarative tool descriptor (spec #64): risk + side effects declared."""

    def __init__(self, name: str, risk: str, permission: Permission,
                 side_effects: list[str], resource_scope: str):
        self.name = name
        self.risk = risk                  # low|medium|high
        self.permission = permission
        self.side_effects = side_effects  # e.g. ["writes_project_db"]
        self.resource_scope = resource_scope

    def describe(self) -> dict:
        return {"name": self.name, "risk": self.risk,
                "required_permission": self.permission.value,
                "side_effects": self.side_effects,
                "resource_scope": self.resource_scope}


TOOL_REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec for spec in [
        ToolSpec("get_research_status", "low", Permission.READ, [], "read"),
        ToolSpec("search_research_memory", "low", Permission.READ, [], "read"),
        ToolSpec("ask_research_memory", "low", Permission.READ, [],
                 "read+llm"),
        ToolSpec("start_research", "medium", Permission.RESEARCH,
                 ["spawns_jobs", "network_fetch", "llm_calls"],
                 "project_write"),
        ToolSpec("pause_research", "low", Permission.RESEARCH,
                 ["mutates_job_state"], "job_control"),
        ToolSpec("cancel_research", "medium", Permission.RESEARCH,
                 ["mutates_job_state"], "job_control"),
        ToolSpec("add_experiment_result", "high", Permission.WRITE,
                 ["updates_hypotheses", "creates_evidence"],
                 "project_write"),
        ToolSpec("execute_experiment", "high",
                 Permission.EXECUTE_EXPERIMENT,
                 ["runs_subprocess", "cpu_usage"], "sandboxed_subprocess"),
        ToolSpec("delete_project", "high", Permission.ADMIN,
                 ["destroys_data"], "filesystem"),
    ]
}


class PathSandbox:
    """Filesystem restriction to allowed roots (spec #65).

    A project must never be able to touch ~/.ssh, system files, or sibling
    repositories. All file-touching platform code validates through here.
    """

    FORBIDDEN_COMPONENTS = {".ssh", ".gnupg", ".aws", ".kube"}

    def __init__(self, roots: list[str | Path]):
        self.roots = [Path(r).resolve() for r in roots]

    def validate_read(self, path: str | Path) -> Path:
        p = Path(path).resolve()
        if not any(_is_relative_to(p, r) for r in self.roots):
            raise PermissionError(f"path outside sandbox: {path}")
        if any(part in self.FORBIDDEN_COMPONENTS for part in p.parts):
            raise PermissionError(f"forbidden path component: {path}")
        return p

    def validate_write(self, path: str | Path) -> Path:
        p = self.validate_read(path)
        if not any(_is_relative_to(p, r) for r in self.roots):
            raise PermissionError(f"write outside sandbox: {path}")
        return p

    @classmethod
    def for_data_dir(cls, data_dir: str | Path) -> "PathSandbox":
        root = Path(data_dir).resolve()
        return cls([root])


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
