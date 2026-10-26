"""Reasoning pipeline facade: research state -> hypotheses -> critique ->
methodologies/validation -> experiments -> human gate.

The orchestrator calls this after the analyze phase; nothing here bypasses the
harness — all persistence goes through repos, all LLM output is validated.
"""
from __future__ import annotations

import logging

from research_engine.providers.llm.base import LLMProvider
from research_engine.reasoning.hypothesis_engine import (HypothesisCritic,
                                                         HypothesisGenerator,
                                                         HypothesisLifecycle,
                                                         RefinementLoop,
                                                         rank_hypotheses,
                                                         score_hypothesis)
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class ReasoningPipeline:
    def __init__(self, repos: Repositories, rrepos: ReasoningRepos,
                 provider: LLMProvider | None, registry=None):
        self.repos = repos
        self.rrepos = rrepos
        self.provider = provider
        self.registry = registry
        self.generator = HypothesisGenerator(repos, rrepos, provider)
        self.critic = HypothesisCritic(repos, rrepos, provider)
        self.lifecycle = HypothesisLifecycle(rrepos)

    def run_for_project(self, project_id: str, mode: str = "academic",
                        max_gaps: int = 2) -> dict:
        """Generate + refine hypotheses from top open gaps/contradictions."""
        summary = {"generated": [], "critiques": [], "ranked": []}

        gaps = sorted([g for g in self.repos.gaps.all(project_id) if not g.resolved],
                      key=lambda g: -g.importance)[:max_gaps]
        for gap in gaps:
            try:
                fam = self.generator.generate_for_gap(project_id, gap)
                summary["generated"].extend(h.id for h in fam)
            except Exception as exc:
                log.warning("hypothesis generation failed for %s (isolated): %s",
                            gap.id, exc)

        cons = self.repos.contradictions.all(project_id, "resolved=0", ())[:1]
        for con in cons:
            try:
                fam = self.generator.generate_for_contradiction(project_id, con)
                summary["generated"].extend(h.id for h in fam)
            except Exception as exc:
                log.warning("contradiction hypotheses failed (isolated): %s", exc)

        # refine + score each generated hypothesis
        loop = RefinementLoop(self.repos, self.rrepos, self.provider,
                              self.lifecycle, self.critic)
        for hid in list(dict.fromkeys(summary["generated"])):
            h = self.rrepos.hypotheses.get(hid)
            if h is None:
                continue
            try:
                res = loop.run(project_id, h)
                summary["critiques"].append({"hypothesis_id": hid,
                                             "stopped": res["stopped_because"],
                                             "problems": len(res["final_critique"]["problems"])})
            except Exception as exc:
                log.warning("refinement failed for %s (isolated): %s", hid, exc)

        ranked = rank_hypotheses(self.repos, self.rrepos, project_id)
        summary["ranked"] = [{"id": r["hypothesis"].id,
                              "score": r["rank_score"],
                              "confidence": r["confidence"],
                              "title": r["hypothesis"].title[:70]} for r in ranked[:8]]
        return summary

    def run_business_hypotheses(self, project_id: str, opportunity) -> dict:
        """Startup path: opportunity -> business hypothesis chain (spec #34/#35)."""
        hyps = self.generator.generate_business_hypotheses(project_id, opportunity)
        for h in hyps:
            score_hypothesis(self.repos, self.rrepos, project_id, h)
        return {"opportunity_id": opportunity.id,
                "hypotheses": [{"id": h.id, "type": h.type, "title": h.title}
                               for h in hyps]}
