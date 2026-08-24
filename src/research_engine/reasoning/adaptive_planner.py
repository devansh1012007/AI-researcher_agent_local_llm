"""Adaptive research planner - the "What next?" engine.

Analyzes the CURRENT structured state (branches, coverage, gaps, contradictions,
weak claims, query history) and decides what to research next using:
  1. deterministic priority rules (always available)
  2. strategy selection based on state
  3. LLM-proposed refinements (advisory, validated)

Strategies (spec #55): BROAD_SWEEP, FOCUSED_DEEP_DIVE, CONTRADICTION_SEARCH,
PRIMARY_SOURCE_SEARCH, RECENT_WORK_SEARCH, FAILURE_CASE_SEARCH.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel

from research_engine.models.enums import EvidenceStatus
from research_engine.models.research import SearchQuery
from research_engine.pipeline.planning import (QueriesOutput, QueryPlannerWorker,
                                               queries_similar)
from research_engine.reasoning.priority import BranchCoverageModel, rank_priorities
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class ResearchStrategy:
    BROAD_SWEEP = "BROAD_SWEEP"
    FOCUSED_DEEP_DIVE = "FOCUSED_DEEP_DIVE"
    CONTRADICTION_SEARCH = "CONTRADICTION_SEARCH"
    PRIMARY_SOURCE_SEARCH = "PRIMARY_SOURCE_SEARCH"
    RECENT_WORK_SEARCH = "RECENT_WORK_SEARCH"
    FAILURE_CASE_SEARCH = "FAILURE_CASE_SEARCH"


STRATEGY_QUERY_HINTS = {
    ResearchStrategy.CONTRADICTION_SEARCH: ("methodology differences comparison", "contradiction"),
    ResearchStrategy.PRIMARY_SOURCE_SEARCH: ("official primary source report", "source_specific"),
    ResearchStrategy.RECENT_WORK_SEARCH: ("2025 OR 2026 latest", "date_filtered"),
    ResearchStrategy.FAILURE_CASE_SEARCH: ("failure cases criticism limitations", "contradiction"),
}


@dataclass
class NextStep:
    strategy: str
    reason: str
    queries: list[SearchQuery] = field(default_factory=list)
    priority_explanations: list[str] = field(default_factory=list)


class _TaskOut(BaseModel):
    question: str = ""
    reason: str = ""
    recommended_queries: list[str] = []


class WhatNextOutput(BaseModel):
    priority_tasks: list[_TaskOut] = []


def select_strategy(repos: Repositories, project_id: str,
                    coverage: dict, iteration: int) -> tuple[str, str]:
    """Deterministic strategy choice from current state."""
    unresolved_con = repos.contradictions.count(project_id, "resolved=0")
    weak_claims = [c for c in repos.claims.all(project_id)
                   if c.supported_by and all(
                       (repos.evidence.get(e) or _FakeEv()).source_tier >= 4
                       for e in c.supported_by)]
    if unresolved_con > 0 and iteration >= 2:
        return (ResearchStrategy.CONTRADICTION_SEARCH,
                f"{unresolved_con} unresolved contradictions need methodology-level search")
    if weak_claims:
        return (ResearchStrategy.PRIMARY_SOURCE_SEARCH,
                f"{len(weak_claims)} claims rest only on tier>=4 sources")
    unanswered = [c for c in coverage.values() if c["unanswered"] and c["importance"] >= 0.5]
    if unanswered:
        return (ResearchStrategy.BROAD_SWEEP,
                f"{len(unanswered)} important branches have no evidence yet")
    weakly = [c for c in coverage.values() if c["weakly_answered"] and c["importance"] >= 0.6]
    if weakly:
        best = max(weakly, key=lambda c: c["importance"])
        return (ResearchStrategy.FOCUSED_DEEP_DIVE,
                f"deep-dive '{best['question'][:60]}' (coverage {best['coverage']:.2f})")
    # everything decently covered -> probe for negative evidence / recency
    if iteration % 2 == 0:
        return (ResearchStrategy.FAILURE_CASE_SEARCH,
                "coverage adequate; probing failure cases and counter-evidence")
    return (ResearchStrategy.RECENT_WORK_SEARCH,
            "coverage adequate; checking for recent developments")


class _FakeEv:
    source_tier = 5


class AdaptivePlanner(QueryPlannerWorker):
    """Extends the Phase 1 QueryPlannerWorker with state-driven adaptation."""

    def plan_next(self, project_id: str, problem, plan, iteration: int,
                  budget_queries: int) -> NextStep:
        branches = [b for b in plan.branches]
        coverage = BranchCoverageModel(self.repos).compute(project_id, branches)
        strategy, why = select_strategy(self.repos, project_id, coverage, iteration)
        priorities = rank_priorities(self.repos, project_id, branches)
        explanations = [p.explain() for p in priorities[:5]]

        created: list[SearchQuery] = []
        existing = self.repos.queries.all(project_id)

        # 1. targeted queries for top-priority gaps/contradictions (deterministic)
        for item in priorities[:3]:
            hint_q, kind = STRATEGY_QUERY_HINTS.get(strategy, ("", "primary"))
            branch = next((b for b in branches if b.id == item.ref_id), None)
            if item.kind == "gap":
                gap = self.repos.gaps.get(item.ref_id)
                cand_texts = [rq.text for rq in (gap.recommended_queries if gap else [])][:2]
            elif item.kind == "contradiction":
                con = self.repos.contradictions.get(item.ref_id)
                cand_texts = [con.follow_up_query] if con and con.follow_up_query else []
            else:
                base_q = (branch.question if branch else item.question)[:80]
                cand_texts = [base_q + (" " + hint_q if hint_q else "")]
                kind = kind if hint_q else "primary"
            for text in cand_texts:
                text = (text or "").strip()
                if not text or len(text) < 8:
                    continue
                if any(queries_similar(text, e.text) for e in existing + created):
                    continue
                q = SearchQuery(project_id=project_id, text=text,
                                branch=branch.id if branch is not None else "",
                                reason=f"{strategy}: {item.kind} {item.ref_id} "
                                       f"(priority {item.priority:.2f})",
                                kind=kind, priority=item.priority,
                                expected_information_gain=item.expected_information_gain,
                                iteration=iteration)
                q.ensure_id()
                created.append(q)

        # 2. LLM refinement within the chosen strategy (advisory)
        spec_questions = "\n".join(f"- {p.question[:120]}" for p in priorities[:4])
        out, errors = self.provider.structured(
            get_system("query_generator"),
            f"Current research strategy: {strategy}\nReason: {why}\n\n"
            f"Top-priority open questions:\n{spec_questions or '(none)'}\n\n"
            f"Generate up to 3 additional DISTINCT queries serving this strategy.\n"
            + 'Respond ONLY with JSON: {"queries": [{"text": "...", "kind": "primary", '
              '"reason": "..."}]}',
            QueriesOutput)
        if out is not None:
            for cand in out.queries:
                text = cand.text.strip()
                if len(text) < 8 or any(queries_similar(text, e.text)
                                        for e in existing + created):
                    continue
                q = SearchQuery(project_id=project_id, text=text,
                                reason=f"adaptive({strategy}): {cand.reason}",
                                kind=cand.kind if cand.kind in {
                                    "primary", "synonym", "technical", "contradiction",
                                    "date_filtered", "source_specific"} else "primary",
                                priority=priorities[0].priority if priorities else 0.5,
                                iteration=iteration)
                q.ensure_id()
                created.append(q)

        created.sort(key=lambda q: -(q.expected_information_gain or q.priority))
        step = NextStep(strategy=strategy, reason=why, queries=created[:budget_queries],
                        priority_explanations=explanations)
        for q in step.queries:
            self.repos.queries.save(q)
        return step


def get_system(name: str) -> str:
    from research_engine.prompts.registry import get_prompt
    return get_prompt(name).system
