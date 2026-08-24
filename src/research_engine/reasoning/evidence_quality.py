"""Evidence independence detection and aggregate claim strength.

Independence (spec #14): sources sharing a domain, organization, or citing the
same origin are NOT independent confirmations.

Classification: independent | possibly_dependent | clearly_dependent | unknown

Aggregate strength (spec #13): transparent weighted model -
    strength = max(single_best) boosted by independent corroboration,
    penalized by dependence, contradiction, and staleness.
Two blog posts can never outweigh one strong primary study.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from research_engine.models.enums import EvidenceStatus
from research_engine.models.evidence import Claim, Evidence
from research_engine.storage.repositories import Repositories

TIER_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.55, 4: 0.35, 5: 0.2}


@dataclass
class IndependenceVerdict:
    label: str                    # independent | possibly_dependent | clearly_dependent | unknown
    reason: str


def classify_independence(ev_a: Evidence, ev_b: Evidence) -> IndependenceVerdict:
    def _domain(e: Evidence) -> str:
        u = e.source_url or ""
        u = re.sub(r"^https?://", "", u)
        return u.split("/")[0]

    if not ev_a.source_url or not ev_b.source_url:
        return IndependenceVerdict("unknown", "missing source url")
    if ev_a.source_id == ev_b.source_id:
        return IndependenceVerdict("clearly_dependent", "same source")
    da, db_ = _domain(ev_a), _domain(ev_b)
    if da and da == db_:
        return IndependenceVerdict("clearly_dependent", f"same domain {da}")
    # same organization names in titles or shared DOI prefix hints
    ta, tb = ev_a.source_title.lower(), ev_b.source_title.lower()
    shared_org = any(org in tb for org in re.findall(
        r"\b([a-z]{4,})\b", ta) if org in {"reuters", "bloomberg", "statista", "gartner",
                                           "mckinsey", "forrester", "idc", "crunchbase"})
    if shared_org:
        return IndependenceVerdict("possibly_dependent", "shared originating organization")
    if ev_a.published_date and ev_a.published_date == ev_b.published_date \
            and _nearly_same_claim(ev_a.claim_text, ev_b.claim_text):
        return IndependenceVerdict("possibly_dependent", "same-date near-identical claims (syndication?)")
    return IndependenceVerdict("independent", "different domains/organizations")


def _nearly_same_claim(a: str, b: str) -> bool:
    wa, wb = set(re.findall(r"[a-z0-9]+", a.lower())), set(re.findall(r"[a-z0-9]+", b.lower()))
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa & wb | wb) >= 0.8 if (wa & wb) else False


@dataclass
class AggregateStrength:
    score: float                 # 0..1
    n_evidence: int
    n_independent: int
    best_tier: int
    components: dict             # transparent breakdown
    explanation: str


def aggregate_claim_strength(claim: Claim, evidence_items: list[Evidence]) -> AggregateStrength:
    """Transparent aggregation; documented formula."""
    accepted = [e for e in evidence_items if e.status != EvidenceStatus.REJECTED]
    if not accepted:
        return AggregateStrength(0.0, 0, 0, 5, {}, "no accepted evidence")

    tier_scores = [TIER_WEIGHT.get(e.source_tier, 0.2) * e.confidence for e in accepted]
    best_single = max(tier_scores)

    # independence-adjusted corroboration boost
    independent_count = 0
    for i, a in enumerate(accepted):
        deps = 0
        for j, b in enumerate(accepted):
            if i == j:
                continue
            v = classify_independence(a, b)
            if v.label in ("clearly_dependent",):
                deps += 1
                break
        if deps == 0:
            independent_count += 1
    corr_boost = min(0.35, 0.12 * max(0, independent_count - 1))

    contradicted = sum(1 for e in accepted if e.status == EvidenceStatus.CONTRADICTED)
    contra_penalty = min(0.5, 0.15 * contradicted)

    recency = _recency_factor(accepted)
    recency_penalty = (1 - recency) * 0.15

    extractor_avg = sum(e.confidence for e in accepted) / len(accepted)
    extractor_factor = 0.7 + 0.3 * extractor_avg

    score = min(1.0, max(0.0,
              (best_single * extractor_factor + corr_boost - contra_penalty - recency_penalty)))
    components = {
        "best_single": round(best_single, 3),
        "extractor_factor": round(extractor_factor, 3),
        "corroboration_boost": round(corr_boost, 3),
        "contradiction_penalty": round(contra_penalty, 3),
        "recency_penalty": round(recency_penalty, 3),
        "independent_sources": independent_count,
    }
    parts = [f"best={components['best_single']}", f"indep={independent_count}"]
    if corr_boost:
        parts.append(f"+boost={corr_boost:.2f}")
    if contra_penalty:
        parts.append(f"-contra={contra_penalty:.2f}")
    return AggregateStrength(round(score, 3), len(accepted), independent_count,
                             min(e.source_tier for e in accepted), components,
                             " ".join(parts))


def _recency_factor(items: list[Evidence]) -> float:
    years = []
    now_year = datetime.now(timezone.utc).year
    for e in items:
        try:
            years.append(int(str(e.published_date)[:4]))
        except (ValueError, TypeError):
            continue
    if not years:
        return 0.6
    age = max(0, now_year - max(years))
    return max(0.0, 1.0 - age / 12)


def update_claim_strengths(repos: Repositories, project_id: str) -> None:
    """Recompute claim confidence from aggregated strength + uncertainty labels."""
    all_ev = {e.id: e for e in repos.evidence.all(project_id)}
    for c in repos.claims.all(project_id):
        items = [all_ev[e] for e in c.supported_by if e in all_ev]
        agg = aggregate_claim_strength(c, items)
        c.confidence = agg.score
        c.notes = [f"strength: {agg.explanation}",
                   f"uncertainty: {_uncertainty_label(agg)}"]
        repos.claims.save(c)


def _uncertainty_label(agg: AggregateStrength) -> str:
    """Uncertainty is distinct from confidence: strong-but-thin stays uncertain."""
    if agg.n_independent >= 3 and agg.best_tier <= 2:
        return "low"
    if agg.n_independent >= 2:
        return "moderate"
    return "high"


class ClaimStrengthService:
    def __init__(self, repos: Repositories):
        self.repos = repos

    def refresh(self, project_id: str) -> None:
        update_claim_strengths(self.repos, project_id)
