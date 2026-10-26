"""Adversarial research engine + claim challenge protocol.

For high-importance conclusions the engine deliberately searches for
counter-evidence, alternative explanations, and failure cases - preventing
the research loop from becoming an evidence-confirmation machine.

The challenge protocol (spec #16) stores structured answers:
supports / contradicts / assumptions / directness / alternative explanations /
independence / recency / falsifiers.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from research_engine.models.analysis import Gap, RecommendedQuery
from research_engine.models.enums import EvidenceStatus, GapCategory, Severity
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class Challenge(BaseModel):
    claim_id: str = ""
    supports: list[str] = []
    contradicts: list[str] = []
    required_assumptions: list[str] = []
    directness: str = "unknown"          # direct | indirect | unknown
    alternative_explanations: list[str] = []
    sources_independent: bool = False
    evidence_current: bool = True
    falsifiers: list[str] = []


def adversarial_queries(claim_text: str) -> list[tuple[str, str]]:
    """Deterministic counter-evidence query families for a claim."""
    core = " ".join(claim_text.split()[:10])
    return [
        (f"{core} limitations problems", "contradiction"),
        (f"{core} failure cases criticism", "contradiction"),
        (f"evidence against {core}", "contradiction"),
        (f"{core} alternative explanation", "primary"),
    ]


class AdversarialEngine:
    def __init__(self, repos: Repositories):
        self.repos = repos

    def claims_needing_challenge(self, project_id: str,
                                 min_confidence: float = 0.55,
                                 top_n: int = 3) -> list:
        """High-visibility claims that would shape conclusions."""
        claims = [c for c in self.repos.claims.all(project_id)
                  if c.supported_by and c.confidence >= min_confidence]
        claims.sort(key=lambda c: -c.confidence)
        return claims[:top_n]

    def build_challenges(self, project_id: str) -> tuple[list[Challenge], list[Gap]]:
        """Analyze important claims structurally; emit challenges + follow-up gaps."""
        challenges: list[Challenge] = []
        gaps: list[Gap] = []
        all_ev = {e.id: e for e in self.repos.evidence.all(project_id)}
        from research_engine.reasoning.evidence_quality import classify_independence
        for c in self.challenges_needed(project_id=project_id):
            sup_ids = [e for e in c.supported_by if e in all_ev]
            ch = Challenge(claim_id=c.id,
                           supports=[e for e in sup_ids],
                           contradicts=[e.id for e in all_ev.values()
                                        if e.status == EvidenceStatus.CONTRADICTED
                                        and c.id in (e.contradicts or [])])
            # independence of support
            independent = 0
            for i, ea in enumerate([all_ev[x] for x in sup_ids]):
                dep = any(classify_independence(ea, all_ev[y]).label != "independent"
                          for y in sup_ids[i + 1:])
                if not dep:
                    independent += 1
            ch.sources_independent = independent >= 2
            # directness heuristic: quote contains numbers/named result -> direct
            ch.directness = ("direct" if any(
                any(ch.isdigit() for ch in all_ev[x].quote) for x in sup_ids) else "indirect")
            ch.evidence_current = any(
                str(all_ev[x].published_date or "")[:4] >= "2023" for x in sup_ids)
            challenges.append(ch)

            if not ch.sources_independent:
                gaps.append(Gap(
                    project_id=project_id,
                    description=f"High-confidence claim '{c.text[:90]}' lacks independent "
                                "multi-source support.",
                    category=GapCategory.INDEPENDENT_REPLICATION_GAP,
                    importance=0.8, severity=Severity.HIGH,
                    evidence_needed="Independent replication from another organization.",
                    recommended_queries=[RecommendedQuery(text=q, reason="challenge")
                                         for q, _ in adversarial_queries(c.text)[:2]]))
            if not ch.evidence_current:
                gaps.append(Gap(
                    project_id=project_id,
                    description=f"Claim '{c.text[:80]}' rests on dated evidence; "
                                "current status unverified.",
                    category=GapCategory.TIME_GAP,
                    importance=0.6, severity=Severity.MEDIUM,
                    evidence_needed="Recent (<=2y) evidence confirming the claim still holds.",
                    branch=c.branch))
        return challenges, gaps

    def challenges_needed(self, project_id: str, **kw) -> list:
        return self.claims_needing_challenge(project_id, **kw)


def adversarial_followup_gaps(repos: Repositories, project_id: str) -> list[Gap]:
    eng = AdversarialEngine(repos)
    _, gaps = eng.build_challenges(project_id)
    return gaps
