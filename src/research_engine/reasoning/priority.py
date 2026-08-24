"""Research priority model and branch coverage scoring.

Transparent, documented formulas - no opaque magic numbers.

Priority model (spec #9):
    priority = importance x uncertainty x expected_information_gain
               x evidence_deficit x downstream_dependency

Coverage model (spec #12): per branch,
    answered      = has >= min_strong accepted evidence items from tiers <= strong_tier
                    attached to claims
    weakly        = has evidence but none strong / low corroboration
    coverage_score = 0.4*answer_ratio + 0.3*strength + 0.2*diversity + 0.1*freshness
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from research_engine.models.enums import EvidenceStatus
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

TIER_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.55, 4: 0.35, 5: 0.2}


@dataclass
class PriorityItem:
    kind: str                     # gap | branch | contradiction | claim_challenge
    ref_id: str
    question: str = ""
    importance: float = 0.5       # how much it matters for conclusions
    uncertainty: float = 0.5      # how unknown it remains
    expected_information_gain: float = 0.5
    evidence_deficit: float = 1.0  # 1 = nothing, 0 = saturated
    downstream_dependency: float = 0.5

    @property
    def priority(self) -> float:
        return round(
            self.importance * self.uncertainty * self.expected_information_gain
            * self.evidence_deficit * self.downstream_dependency, 4)

    def explain(self) -> str:
        return (f"{self.kind}:{self.ref_id} p={self.priority:.3f} "
                f"(imp={self.importance:.2f} unc={self.uncertainty:.2f} "
                f"gain={self.expected_information_gain:.2f} "
                f"deficit={self.evidence_deficit:.2f} dep={self.downstream_dependency:.2f})")


def evidence_deficit(n_evidence: int, saturation: int = 6) -> float:
    """1.0 when empty, decays to ~0 once saturated."""
    return max(0.05, 1.0 - min(1.0, n_evidence / max(1, saturation)))


def uncertainty_from_evidence(ev_items, n_claims: int) -> float:
    """Uncertainty stays high while support is thin, weak-tier, or contested."""
    if not ev_items or n_claims == 0:
        return 1.0
    accepted = [e for e in ev_items if e.status != EvidenceStatus.REJECTED]
    if not accepted:
        return 1.0
    best_tier_w = max(TIER_WEIGHT.get(e.source_tier, 0.2) for e in accepted)
    independence_bonus = min(1.0, len({e.source_id for e in accepted}) / 3)
    base = (1.0 - 0.5 * best_tier_w) * (1.0 - 0.3 * independence_bonus)
    return round(min(1.0, max(0.1, base)), 3)


class BranchCoverageModel:
    """Computes per-branch coverage scores with an explicit formula."""

    def __init__(self, repos: Repositories):
        self.repos = repos

    def compute(self, project_id: str, branches: list) -> dict[str, dict]:
        evidence = [e for e in self.repos.evidence.all(project_id)
                    if e.status != EvidenceStatus.REJECTED]
        claims = {c.id: c for c in self.repos.claims.all(project_id)}
        gaps_open = [g for g in self.repos.gaps.all(project_id) if not g.resolved]

        by_branch: dict[str, list] = {}
        for ev in evidence:
            by_branch.setdefault(ev.branch, []).append(ev)

        result = {}
        for b in branches:
            evs = by_branch.get(b.id, [])
            branch_claims = [c for c in claims.values() if c.branch == b.id]
            if not evs and not branch_claims:
                # fall back to question-term matching for unattributed evidence
                terms = [w.lower() for w in b.question.split() if len(w) > 4][:5]
                for ev in evidence:
                    text = (ev.claim_text + " " + " ".join(ev.tags)).lower()
                    if sum(1 for t in terms if t in text) / max(1, len(terms)) >= 0.4:
                        evs.append(ev)

            answer_ratio = min(1.0, len(evs) / 6)
            strong = [e for e in evs if e.source_tier <= 2]
            strength = min(1.0, len(strong) / 3) if evs else 0.0
            domains = {e.source_url.split("/")[0] if "/" in e.source_url else e.source_url
                       for e in evs}
            diversity = min(1.0, len(domains) / 3) if evs else 0.0
            freshness = _freshness(evs)
            score = round(0.4 * answer_ratio + 0.3 * strength + 0.2 * diversity
                          + 0.1 * freshness, 3)
            open_gaps = [g for g in gaps_open if g.branch == b.id]
            result[b.id] = {
                "branch_id": b.id, "category": b.category,
                "question": b.question, "importance": b.importance,
                "coverage": score,
                "evidence_count": len(evs),
                "strong_evidence_count": len(strong),
                "claims_count": len(branch_claims),
                "gap_count": len(open_gaps),
                "answered": score >= 0.7,
                "weakly_answered": 0.25 <= score < 0.7,
                "unanswered": score < 0.25,
            }
        return result


def _freshness(evs: list) -> float:
    dates = []
    for e in evs:
        d = e.published_date
        if not d:
            continue
        try:
            year = int(str(d)[:4])
            age = max(0, datetime.now(timezone.utc).year - year)
            dates.append(max(0.0, 1.0 - age / 10))
        except ValueError:
            continue
    return sum(dates) / len(dates) if dates else 0.3


def rank_priorities(repos: Repositories, project_id: str, branches: list,
                    dependency_weight: float = 0.5) -> list[PriorityItem]:
    """Build the global priority queue over gaps, branches, contradictions."""
    coverage = BranchCoverageModel(repos).compute(project_id, branches)
    items: list[PriorityItem] = []

    for cov in coverage.values():
        items.append(PriorityItem(
            kind="branch", ref_id=cov["branch_id"], question=cov["question"],
            importance=cov["importance"],
            uncertainty=1.0 - cov["coverage"],
            expected_information_gain=round(cov["unanswered"] * 0.9 + cov["weakly_answered"] * 0.6, 3),
            evidence_deficit=evidence_deficit(cov["evidence_count"]),
            downstream_dependency=dependency_weight))

    for g in repos.gaps.all(project_id, "resolved=0", ()):
        items.append(PriorityItem(
            kind="gap", ref_id=g.id, question=g.description,
            importance=g.importance, uncertainty=1.0,
            expected_information_gain=min(1.0, 0.5 + g.importance / 2),
            evidence_deficit=1.0,
            downstream_dependency=dependency_weight if g.branch else 0.3))

    for c in repos.contradictions.all(project_id, "resolved=0", ()):
        items.append(PriorityItem(
            kind="contradiction", ref_id=c.id,
            question=f"Resolve/explain: {c.statement_a[:80]} vs {c.statement_b[:80]}",
            importance=0.85, uncertainty=0.9, expected_information_gain=0.85,
            evidence_deficit=0.9, downstream_dependency=0.7))

    items.sort(key=lambda i: -i.priority)
    return items
