"""Contradiction detection.

LLM proposes semantic contradictions between claims; the harness persists them
WITHOUT resolving. Each contradiction records a possible explanation and a
follow-up query.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from research_engine.models.analysis import Contradiction
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class _ContradictionOut(BaseModel):
    claim_a: str = ""
    claim_b: str = ""
    explanation: str = ""
    follow_up_query: str = ""


class ContradictionsOutput(BaseModel):
    contradictions: list[_ContradictionOut] = Field(default_factory=list)


class ContradictionDetector:
    def __init__(self, provider: LLMProvider, repos: Repositories):
        self.provider = provider
        self.repos = repos

    def run(self, project_id: str) -> list[Contradiction]:
        claims = self.repos.claims.all(project_id)
        if len(claims) < 2:
            return []
        # only FACT-kind claims participate; inferences/assumptions can't "contradict"
        facts = [c for c in claims if c.kind.value == "FACT" and len(c.supported_by) >= 1]
        existing = {(c.claim_a_id, c.claim_b_id)
                    for c in self.repos.contradictions.all(project_id)}
        if len(facts) < 2:
            return []
        claims_summary = "\n".join(f"{c.id}: {c.text[:200]}" for c in facts[:50])
        spec = get_prompt("contradiction_detector")
        out, errors = self.provider.structured(spec.system,
                                               spec.render(claims_summary=claims_summary),
                                               ContradictionsOutput)
        created = []
        if out is None:
            log.warning("contradiction detection failed: %s", errors[-1:])
            return []
        by_id = {c.id: c for c in facts}
        for item in out.contradictions:
            a, b = by_id.get(item.claim_a), by_id.get(item.claim_b)
            if a is None or b is None or a.id == b.id:
                continue
            key = tuple(sorted((a.id, b.id)))
            if key in existing:
                continue
            con = Contradiction(
                project_id=project_id,
                claim_a_id=a.id, claim_b_id=b.id,
                statement_a=a.text[:300], statement_b=b.text[:300],
                explanation=item.explanation[:400],
                source_quality_note=self._quality_note(a, b),
                follow_up_query=item.follow_up_query[:250],
            )
            con.ensure_id()
            self.repos.contradictions.save(con)
            existing.add(key)
            created.append(con)
        return created

    def _quality_note(self, a, b) -> str:
        def tier_summary(claim) -> str:
            evs = [self.repos.evidence.get(e) for e in claim.supported_by]
            tiers = sorted(e.source_tier for e in evs if e)
            return f"tiers={tiers}"
        return f"A {tier_summary(a)} vs B {tier_summary(b)}"
