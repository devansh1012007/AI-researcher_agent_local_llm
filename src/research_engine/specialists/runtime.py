"""Specialist runtime core (Phase 5 §3–§18).

A specialist contributes DOMAIN INTELLIGENCE; the platform owns state,
evidence, execution, security, provenance, scheduling and invariants.

# Decision: the registry is an in-process capability catalog, not
# orchestration state; lifecycle is metadata + the platform's normal task
# states (spec §43) — there is no second state machine.
# Why: orchestration belongs to the orchestrator/scheduler; a second one
# would recreate the BUG-01 class of ownership bugs at the specialist layer.
# Constraint: retirement keeps historical registrations visible (§51);
# nothing silently disappears.
"""
from __future__ import annotations

import enum
import threading
import time
from typing import Any, Callable

from pydantic import BaseModel, Field


# ------------------------------------------------------------- permissions

class SpecialistPermission(str, enum.Enum):
    READ_PROJECT = "READ_PROJECT"
    READ_EVIDENCE = "READ_EVIDENCE"
    CREATE_EVIDENCE = "CREATE_EVIDENCE"
    CREATE_CLAIM = "CREATE_CLAIM"
    CREATE_GAP = "CREATE_GAP"
    CREATE_HYPOTHESIS = "CREATE_HYPOTHESIS"
    CREATE_OPPORTUNITY = "CREATE_OPPORTUNITY"
    CREATE_RESEARCH_TASK = "CREATE_RESEARCH_TASK"
    CREATE_REPORT = "CREATE_REPORT"


DEFAULT_PERMISSIONS = frozenset({
    SpecialistPermission.READ_PROJECT,
    SpecialistPermission.READ_EVIDENCE,
})


# ---------------------------------------------------------------- health

class HealthState(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    RETIRED = "RETIRED"


class SpecialistHealth(BaseModel):
    state: HealthState = HealthState.AVAILABLE
    reason: str = ""


# ------------------------------------------------------------- lifecycle

class LifecycleState(str, enum.Enum):
    REGISTERED = "REGISTERED"
    AVAILABLE = "AVAILABLE"
    SELECTED = "SELECTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------- budget

class BudgetExceeded(RuntimeError):
    """Raised when a specialist invocation exceeds its declared budget."""


class SpecialistBudget(BaseModel):
    max_queries: int = 10
    max_documents: int = 30
    max_llm_calls: int = 15
    max_seconds: float = 900.0
    parallelism: int = 1


class InvocationBudget:
    """Live counters for ONE specialist invocation. Hard limits — budgets
    are not advisory (core principle inherited from core/budget.py)."""

    def __init__(self, spec: SpecialistBudget | None = None):
        self.spec = spec or SpecialistBudget()
        self.queries_used = 0
        self.documents_used = 0
        self.llm_calls_used = 0
        self._t0 = time.monotonic()

    def seconds_left(self) -> float:
        return max(0.0, self.spec.max_seconds - (time.monotonic() - self._t0))

    def _spend(self, used: int, cap: int, what: str) -> None:
        if used >= cap:
            raise BudgetExceeded(
                f"{what} budget exhausted ({used}/{cap})")

    def spend_query(self, n: int = 1) -> None:
        self._spend(self.queries_used, self.spec.max_queries, "queries")
        self.queries_used += n

    def spend_document(self, n: int = 1) -> None:
        self._spend(self.documents_used, self.spec.max_documents, "documents")
        self.documents_used += n

    def spend_llm_call(self, n: int = 1) -> None:
        self._spend(self.llm_calls_used, self.spec.max_llm_calls, "llm")
        self.llm_calls_used += n

    def check_time(self) -> None:
        if self.seconds_left() <= 0:
            raise BudgetExceeded(
                f"time budget exhausted ({self.spec.max_seconds}s)")

    def snapshot(self) -> dict:
        return {"queries": self.queries_used, "documents": self.documents_used,
                "llm_calls": self.llm_calls_used,
                "seconds_left": round(self.seconds_left(), 2)}


# ------------------------------------------------------------ descriptor

class SpecialistDescriptor(BaseModel):
    """The formal specialist contract (spec §3)."""
    specialist_id: str
    name: str
    version: str = "1.0"
    description: str = ""
    supported_modes: list[str] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    source_preferences: list[str] = Field(default_factory=list)
    research_policies: dict = Field(default_factory=dict)
    evidence_requirements: dict = Field(default_factory=dict)
    entity_types: list[str] = Field(default_factory=list)
    scoring_models: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    report_templates: list[str] = Field(default_factory=list)
    evaluation_suite: str = ""
    permissions: set[SpecialistPermission] = Field(
        default_factory=lambda: set(DEFAULT_PERMISSIONS))
    budgets: SpecialistBudget = Field(default_factory=SpecialistBudget)
    model_routing: dict = Field(default_factory=dict)  # role -> size hint

    @property
    def key(self) -> str:
        return f"{self.specialist_id}@{self.version}"


class SpecialistOutput(BaseModel):
    """Structured specialist result (spec §11). Everything flows through
    normal validation downstream — outputs never touch storage directly."""
    specialist_id: str
    version: str = ""
    task_id: str = ""
    project_id: str = ""
    findings: list[dict] = Field(default_factory=list)
    claims: list[dict] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    recommendations: list[dict] = Field(default_factory=list)
    confidence: dict = Field(default_factory=dict)
    next_research: list[dict] = Field(default_factory=list)
    artifacts: dict = Field(default_factory=dict)
    notes: str = ""


class Handoff(BaseModel):
    """Structured inter-specialist handoff (spec §9). Never transcripts."""
    source_specialist: str = ""
    target_specialist: str = ""
    branch: str = ""
    objective: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    required_output: str = ""


class RunContext:
    """Everything ONE specialist invocation may touch. Specialists receive
    this (plus nothing else) from the runner."""

    def __init__(self, orch, api, descriptor, mode: str, params: dict,
                 handoff: "Handoff | None", context_pack: dict,
                 budget: InvocationBudget, selection_reason: str = ""):
        self.orch = orch
        self.api = api
        self.descriptor = descriptor
        self.mode = mode
        self.params = params or {}
        self.handoff = handoff
        self.context_pack = context_pack or {}
        self.budget = budget
        self.selection_reason = selection_reason


# --------------------------------------------------------------- registry

class Registration:
    def __init__(self, descriptor: SpecialistDescriptor,
                 invoke: Callable[[Any], SpecialistOutput]):
        self.descriptor = descriptor
        self.invoke = invoke
        self.lifecycle = LifecycleState.REGISTERED
        self.health = SpecialistHealth()
        self.history: list[tuple[str, str, str]] = []  # (state, reason, iso)
        self.registered_at = _utcnow()

    def transition(self, state: LifecycleState, reason: str = "") -> None:
        self.lifecycle = state
        self.history.append((state.value, reason, _utcnow()))


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class SpecialistRegistry:
    """Capability catalog. NOT an orchestrator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[str, Registration] = {}
        self._latest: dict[str, str] = {}

    def register(self, descriptor: SpecialistDescriptor,
                 invoke: Callable[[Any], SpecialistOutput]) -> Registration:
        with self._lock:
            if descriptor.key in self._by_key:
                raise ValueError(
                    f"specialist already registered: {descriptor.key}")
            reg = Registration(descriptor, invoke)
            self._by_key[descriptor.key] = reg
            prev = self._latest.get(descriptor.specialist_id)
            if prev is None or _ver_gt(descriptor.version,
                                       self._by_key[prev].descriptor.version):
                self._latest[descriptor.specialist_id] = descriptor.key
            return reg

    def retire(self, specialist_id: str, version: str | None = None,
               reason: str = "") -> bool:
        """Retire — never delete (§51): history stays interpretable."""
        keys = [self._resolve(specialist_id, version)]
        with self._lock:
            for k in filter(None, keys):
                reg = self._by_key.get(k)
                if reg is None:
                    continue
                reg.health = SpecialistHealth(state=HealthState.RETIRED,
                                              reason=reason)
                reg.transition(LifecycleState.COMPLETED,
                               reason or "retired")
                return True
            return False

    def lookup(self, specialist_id: str,
               version: str | None = None) -> Registration | None:
        with self._lock:
            k = self._resolve(specialist_id, version)
            return self._by_key.get(k) if k else None

    def list_active(self) -> list[Registration]:
        with self._lock:
            return [r for r in self._by_key.values()
                    if r.health.state != HealthState.RETIRED]

    def versions(self, specialist_id: str) -> list[str]:
        with self._lock:
            return sorted(k.split("@", 1)[1] for k in self._by_key
                          if k.startswith(specialist_id + "@"))

    def capability_query(self, modes: list[str] | None = None,
                         entity_types: list[str] | None = None,
                         permission: SpecialistPermission | None = None,
                         ) -> list[SpecialistDescriptor]:
        out = []
        for reg in self.list_active():
            d = reg.descriptor
            if modes and not set(modes) & set(d.supported_modes):
                continue
            if entity_types and not set(entity_types) & set(d.entity_types):
                continue
            if permission and permission not in d.permissions:
                continue
            if reg.health.state == HealthState.UNAVAILABLE:
                continue
            out.append(d)
        return out

    # internals
    def _resolve(self, specialist_id: str,
                 version: str | None) -> str | None:
        if version:
            k = f"{specialist_id}@{version}"
            return k if k in self._by_key else None
        return self._latest.get(specialist_id)


def _ver_gt(a: str, b: str) -> bool:
    def parts(v: str):
        return [int(p) if p.isdigit() else 0 for p in v.split(".")]
    return parts(a) > parts(b)


_registry: SpecialistRegistry | None = None
_reg_lock = threading.Lock()


def get_registry() -> SpecialistRegistry:
    global _registry
    with _reg_lock:
        if _registry is None:
            _registry = SpecialistRegistry()
        return _registry


def reset_registry() -> None:
    global _registry
    with _reg_lock:
        _registry = None
