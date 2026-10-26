"""Research planning + query generation + information-gain scoring.

The planner produces a research graph (branches), the query generator produces
per-branch query families, and a deterministic heuristic scores queries so local
compute is spent on high-expected-value searches first.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from research_engine.engines.loader import get_engine
from research_engine.models.enums import (
    ACADEMIC_CATEGORIES, STARTUP_CATEGORIES, BranchCategory,
)
from research_engine.models.research import ResearchBranch, ResearchPlan, SearchQuery
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

MODE_HINTS = {
    "academic": "scientific/technical literature research (methods, benchmarks, limitations, open problems)",
    "startup": "startup & market research (customers, pain, competitors, pricing, funding, regulation)",
}

CATEGORY_HINTS = "\n".join(f"- {c.value}" for c in ACADEMIC_CATEGORIES + STARTUP_CATEGORIES)


class _BranchOut(BaseModel):
    category: str = ""
    question: str = ""
    importance: float = 0.5
    required_evidence: str = ""
    source_preferences: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    branches: list[_BranchOut] = Field(default_factory=list)


class PlannerWorker:
    def __init__(self, provider: LLMProvider, repos: Repositories, mode: str):
        self.provider = provider
        self.repos = repos
        self.mode = mode

    def run(self, project_id: str, problem) -> ResearchPlan:
        try:
            manifest = get_engine(self.mode)
            allowed_cats = manifest.branch_categories()
            mode_hint = MODE_HINTS.get(self.mode, manifest.clarifier.hint or self.mode)
            spec = get_prompt("research_planner", engine=manifest.name)
        except Exception:
            manifest = get_engine("academic")
            allowed_cats = [c.value for c in ACADEMIC_CATEGORIES]
            mode_hint = MODE_HINTS.get(self.mode, self.mode)
            spec = get_prompt("research_planner")

        user = spec.render(
            objective=problem.objective,
            mode=self.mode,
            mode_hint=mode_hint,
            categories_hint=", ".join(allowed_cats),
        )
        out, errors = self.provider.structured(spec.system, user, PlanOutput)
        plan = ResearchPlan(project_id=project_id, objective=problem.objective)
        valid_cats = set(allowed_cats)
        any_valid = False
        for b in (out.branches if out else []):
            cat = b.category.upper() if b.category else ""
            if cat not in valid_cats:
                cat = BranchCategory.GENERIC.value if BranchCategory.GENERIC.value in valid_cats else allowed_cats[0]
            else:
                any_valid = True
            branch = ResearchBranch(
                project_id=project_id,
                category=str(cat),
                question=b.question or b.category,
                importance=min(max(b.importance, 0.0), 1.0),
                required_evidence=b.required_evidence,
                source_preferences=[p.lower() for p in b.source_preferences],
            )
            branch.ensure_id()
            plan.branches.append(branch)
        if not any_valid:
            # every proposed category was invalid for this mode -> use engine skeleton
            plan.branches = []
        if not plan.branches and manifest.planning.fallback_to_branches:
            # deterministic fallback driven by EngineManifest.planning.branches
            q = problem.research_question or problem.objective
            default_prefs = (
                list(manifest.planning.source_preferences[:2])
                if manifest.planning.source_preferences
                else ["web"]
            )
            for b_spec in manifest.fallback_branches():
                question_text = b_spec.default_question.replace("{question}", q)
                br = ResearchBranch(
                    project_id=project_id,
                    category=b_spec.category,
                    question=question_text,
                    importance=b_spec.importance,
                    required_evidence=b_spec.required_evidence,
                    source_preferences=list(default_prefs),
                )
                br.ensure_id()
                plan.branches.append(br)
        for br in plan.branches:
            self.repos.branches.save(br)
        plan.ensure_id()
        self.repos.plans.save(plan)
        return plan


class _QueryOut(BaseModel):
    text: str = ""
    kind: str = "primary"
    reason: str = ""


class QueriesOutput(BaseModel):
    queries: list[_QueryOut] = Field(default_factory=list)


def normalize_query_text(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


def queries_similar(a: str, b: str, threshold: float = 0.82) -> bool:
    na, nb = normalize_query_text(a), normalize_query_text(b)
    if not na or not nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / max(1, len(ta | tb))
    return jac >= threshold or SequenceMatcher(None, na, nb).ratio() >= threshold


class QueryPlannerWorker:
    """Generates per-branch queries and scores them with an information-gain heuristic."""

    def __init__(self, provider: LLMProvider, repos: Repositories):
        self.provider = provider
        self.repos = repos

    def run(self, project_id: str, plan: ResearchPlan, iteration: int,
            per_branch: int = 3, existing_queries: list[SearchQuery] | None = None) -> list[SearchQuery]:
        existing = existing_queries or self.repos.queries.all(project_id)
        created: list[SearchQuery] = []
        open_branches = sorted(plan.branches, key=lambda b: -b.importance)
        for branch in open_branches:
            context = self._branch_context(project_id, branch)
            spec = get_prompt("query_generator")
            user = spec.render(branch_question=branch.question,
                               required_evidence=branch.required_evidence or "any credible evidence",
                               context=context or "(none yet)", n_queries=per_branch)
            out, errors = self.provider.structured(spec.system, user, QueriesOutput)
            candidates = out.queries if out else []
            if not candidates:
                kws = " ".join(branch.question.split()[:8])
                candidates = [_QueryOut(text=kws, kind="primary", reason="fallback keyword query"),
                              _QueryOut(text=f"{kws} limitations criticism", kind="contradiction",
                                        reason="adversarial probe")]
            for cand in candidates:
                text = cand.text.strip()
                if not text or len(text) < 8:
                    continue
                if any(queries_similar(text, e.text) for e in existing + created):
                    continue
                q = SearchQuery(
                    project_id=project_id, text=text, branch=branch.id,
                    reason=cand.reason or f"branch {branch.category}",
                    kind=cand.kind if cand.kind in {
                        "primary", "synonym", "technical", "contradiction",
                        "date_filtered", "source_specific"} else "primary",
                    priority=branch.importance, iteration=iteration,
                )
                q.expected_information_gain = score_information_gain(q, branch, len(existing))
                q.ensure_id()
                created.append(q)
        for q in created:
            self.repos.queries.save(q)
        return created

    def _branch_context(self, project_id: str, branch: ResearchBranch) -> str:
        claims = self.repos.claims.all(project_id, "branch=?", (branch.id,))
        return "; ".join(c.text[:120] for c in claims[:8])


def score_information_gain(q: SearchQuery, branch: ResearchBranch, n_existing_queries: int) -> float:
    importance = branch.importance
    expected_relevance = {"primary": 1.0, "technical": 0.95, "contradiction": 0.85,
                          "date_filtered": 0.8, "source_specific": 0.75,
                          "synonym": 0.7}.get(q.kind, 0.9)
    expected_source_quality = 1.0
    uncertainty = 1.0
    novelty = max(0.3, 1.0 - 0.02 * n_existing_queries)
    return round(importance * expected_relevance * expected_source_quality * uncertainty * novelty, 4)


def select_queries(all_queries: list[SearchQuery], budget: int) -> list[SearchQuery]:
    pending = [q for q in all_queries if not q.executed]
    pending.sort(key=lambda q: -q.expected_information_gain)
    return pending[:budget]
