"""Specialist API facade (Phase 5 §12–§14).

The ONLY object a specialist invocation receives. Every write is
permission-checked and routed through the canonical validation pipeline
(grounding gates for evidence, repos for persistence) so a specialist
cannot bypass identity, grounding, ownership or project boundaries.

# Decision: capability enforcement lives here (the runtime seam), not in
# scattered repo checks.
# Why: one choke point is auditable and testable; INV-014's static scan
# additionally forbids specialists importing storage directly.
# Constraint: methods stay coarse-grained; specialists never receive repos.
"""
from __future__ import annotations

from research_engine.specialists.runtime import (
    BudgetExceeded, InvocationBudget, SpecialistPermission)


class PermissionDenied(RuntimeError):
    """Specialist attempted an operation its contract does not grant."""


class SpecialistApi:
    def __init__(self, orch, permissions: set[SpecialistPermission],
                 budget: InvocationBudget, specialist_id: str,
                 version: str, task_id: str = "",
                 task_submitter=None):
        self._orch = orch
        self._perms = frozenset(permissions)
        self.budget = budget
        self.specialist_id = specialist_id
        self.version = version
        self.task_id = task_id
        self._task_submitter = task_submitter
        # provenance trail for handoffs/synthesis (§9/§41)
        self.created = {"evidence_ids": [], "claim_ids": [],
                        "gap_ids": []}

    # ------------------------------------------------------------- reads

    def _require(self, perm: SpecialistPermission) -> None:
        if perm not in self._perms:
            raise PermissionDenied(
                f"{self.specialist_id}@{self.version} lacks {perm.value}")

    def _scope(self, project_id: str | None) -> str:
        """§74 isolation: a specialist can NEVER address another project,
        regardless of what it passes."""
        if project_id is not None and project_id != self.project_id:
            raise PermissionDenied(
                "cross-project access denied (project isolation)")
        return self.project_id

    def read_evidence(self, project_id: str | None = None):
        self._require(SpecialistPermission.READ_EVIDENCE)
        return self._orch.repos.evidence.all(self._scope(project_id))

    def read_claims(self, project_id: str | None = None):
        self._require(SpecialistPermission.READ_EVIDENCE)
        return self._orch.repos.claims.all(self._scope(project_id))

    def read_gaps(self, project_id: str | None = None):
        self._require(SpecialistPermission.READ_PROJECT)
        return self._orch.repos.gaps.all(self._scope(project_id))

    def read_sources(self, project_id: str | None = None):
        self._require(SpecialistPermission.READ_PROJECT)
        return self._orch.repos.sources.all(self._scope(project_id))

    @property
    def project_id(self) -> str:
        return self._orch.project.id

    @property
    def question(self) -> str:
        return getattr(self._orch.project, "question_raw", "")

    def reasoning_llm(self):
        """Role-routed LLM handle; every call spends invocation budget."""
        router = getattr(self._orch, "router", None)
        llm = router.reasoning if router else None
        if llm is None:
            return None
        budget = self.budget

        class _Budgeted:
            def structured(_self, system, user, model):
                budget.spend_llm_call()
                budget.check_time()
                return llm.structured(system, user, model)

        return _Budgeted()

    # ------------------------------------------------------------ writes

    def create_evidence(self, *, claim_text: str, quote: str,
                        chunk_text: str, source_id: str, source_tier: int,
                        source_url: str = "", source_title: str = "") -> dict:
        """Grounded evidence creation: BOTH canonical gates run here.

        Quote-existence fails ⇒ nothing persisted (caller gets reason).
        Claim-support CONTRADICTS/UNRELATED ⇒ persisted as REJECTED audit
        row (INV-005), never as supporting evidence."""
        from research_engine.models.evidence import Evidence, EvidenceStatus
        from research_engine.pipeline.claim_support import verify_claim_support
        from research_engine.pipeline.evidence import verify_quote

        self._require(SpecialistPermission.CREATE_EVIDENCE)
        quote_ok, why = verify_quote(quote, chunk_text)
        if not quote_ok:
            return {"status": "REJECTED_QUOTE", "reason": why,
                    "evidence": None}
        verdict = verify_claim_support(claim_text, quote)
        status = (EvidenceStatus.REJECTED
                  if verdict.verdict in ("CONTRADICTS", "UNRELATED")
                  else EvidenceStatus.SUPPORTED)
        ev = Evidence(project_id=self.project_id, claim_text=claim_text,
                      quote=quote, source_id=source_id,
                      source_tier=source_tier, source_url=source_url,
                      source_title=source_title, status=status,
                      support_verdict=verdict.verdict,
                      validation_notes="; ".join(verdict.reasons)[:300])
        ev.ensure_id()
        self._orch.repos.evidence.save(ev)
        if status == EvidenceStatus.SUPPORTED:
            self.created["evidence_ids"].append(ev.id)
        return {"status": status.value, "verdict": verdict.verdict,
                "evidence": ev}

    def create_claim(self, text: str, supported_by: list[str],
                     kind: str = "FACT", topic: str = ""):
        from research_engine.models.evidence import Claim
        self._require(SpecialistPermission.CREATE_CLAIM)
        cl = Claim(project_id=self.project_id, text=text,
                   supported_by=list(supported_by), kind=kind, topic=topic)
        cl.ensure_id()
        self._orch.repos.claims.save(cl)
        self.created["claim_ids"].append(cl.id)
        return cl

    def create_gap(self, description: str, importance: int = 3,
                   evidence_needed: str = "", recommended_queries=None):
        from research_engine.models.analysis import Gap, RecommendedQuery
        self._require(SpecialistPermission.CREATE_GAP)
        rq = [RecommendedQuery(text=q) if isinstance(q, str) else q
              for q in (recommended_queries or [])]
        g = Gap(project_id=self.project_id, description=description,
                importance=importance, evidence_needed=evidence_needed,
                recommended_queries=rq)
        g.ensure_id()
        self._orch.repos.gaps.save(g)
        self.created["gap_ids"].append(g.id)
        return g

    def submit_research_task(self, spec: dict):
        """Request more research via the ORCHESTRATOR (never self-execute)."""
        self._require(SpecialistPermission.CREATE_RESEARCH_TASK)
        if self._task_submitter is None:
            raise PermissionDenied("no task submitter wired for this run")
        return self._task_submitter(spec)

    def create_report_section(self, name: str, content: str) -> str:
        """Derived report artifact — writes markdown only, never state."""
        from pathlib import Path
        self._require(SpecialistPermission.CREATE_REPORT)
        out = Path(self._orch.ws.reports) / f"specialist_{name}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        return str(out)
