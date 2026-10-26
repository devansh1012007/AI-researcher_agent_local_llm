"""Contradiction resolution ANALYSIS - never automatic resolution.

Given a contradiction, compare the supporting contexts:
  dates, geographies, metrics/definitions, methodologies, source quality.
Output: a structured assessment of whether the disagreement is
  REAL_CONTRADICTION | MEASUREMENT_DIFFERENCE | TEMPORAL_DIFFERENCE |
  SCOPE_DIFFERENCE | UNRESOLVED
with an explanation. The stored Contradiction stays unresolved=true either way;
this analysis informs humans and future research.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from research_engine.storage.repositories import Repositories


class ContradictionAssessment(BaseModel):
    verdict: str = "UNRESOLVED"
    # REAL_CONTRADICTION | MEASUREMENT_DIFFERENCE | TEMPORAL_DIFFERENCE |
    # SCOPE_DIFFERENCE | UNRESOLVED
    explanation: str = ""
    dimensions: dict = {}


class _LLMVerdict(BaseModel):
    verdict: str = "UNRESOLVED"
    explanation: str = ""


_DIMENSION_KEYWORDS = {
    "temporal": re.compile(r"\b(19|20)\d{2}\b|\b(january|q[1-4]|year|annual|monthly)\b", re.I),
    "geographic": re.compile(r"\b(global|usa?|india|europe|china|uk|emea|apac)\b", re.I),
    "metric": re.compile(r"\b(revenue|users|accuracy|success rate|market size|%|percent)\b", re.I),
}


class ContradictionAnalyzer:
    def __init__(self, repos: Repositories):
        self.repos = repos

    def assess(self, project_id: str, contradiction) -> ContradictionAssessment:
        # INVARIANT-009: fall back to evidence-side links when the conflict
        # carries no claim links (market-size conflicts store evidence ids).
        def _side(claim_id: str, own_evidence_ids: list) -> list:
            id_lists = [list(_claim_evidence(self.repos, project_id, claim_id))]
            if not any(id_lists[0]) and own_evidence_ids:
                id_lists = [list(own_evidence_ids)]
            out = []
            for ids in id_lists:
                for eid in ids:
                    ev = self.repos.evidence.get(eid)
                    if ev is not None:
                        out.append(ev)
            return out

        ev_a = _side(contradiction.claim_a_id,
                     getattr(contradiction, "evidence_a_ids", []) or [])
        ev_b = _side(contradiction.claim_b_id,
                     getattr(contradiction, "evidence_b_ids", []) or [])
        dims: dict = {}
        dims["temporal"] = self._compare_dimension(ev_a, ev_b, lambda e: str(e.published_date or "")[:4])
        dims["geographic"] = self._compare_dimension(
            ev_a, ev_b, lambda e: _geo(e.claim_text + " " + e.source_title))
        # metric/definition dimension (was read but never computed — latent bug)
        dims["metric"] = self._compare_dimension(
            ev_a, ev_b, lambda e: _metric(e.claim_text))
        dims["source_tier"] = {
            "a": min((e.source_tier for e in ev_a), default=5),
            "b": min((e.source_tier for e in ev_b), default=5)}

        # deterministic classification
        verdict, why = "UNRESOLVED", "insufficient context to classify"
        if any(d["differs"] for d in (dims["temporal"], dims["geographic"])):
            which = "publication periods" if dims["temporal"]["differs"] else "geographies"
            verdict = ("TEMPORAL_DIFFERENCE" if dims["temporal"]["differs"]
                       else "SCOPE_DIFFERENCE")
            why = f"Claims reference different {which}; both may be true in their own scope."
        elif dims["metric"]["differs"]:
            verdict = "MEASUREMENT_DIFFERENCE"
            why = "Claims appear to measure different metrics or populations."
        else:
            tiers = dims["source_tier"]
            if tiers["a"] != tiers["b"] and min(tiers.values()) <= 2:
                better = "A" if tiers["a"] < tiers["b"] else "B"
                verdict = "REAL_CONTRADICTION"
                why = (f"Genuine disagreement; side {better} rests on stronger sources "
                       f"(tier {min(tiers.values())} vs {max(tiers.values())}). Resolution "
                       "still requires human judgment.")

        # LLM refinement is advisory and may only refine the explanation text
        return ContradictionAssessment(verdict=verdict, explanation=why, dimensions=dims)

    @staticmethod
    def _compare_dimension(ev_a, ev_b, extract) -> dict:
        vals_a = {extract(e) for e in ev_a} - {""}
        vals_b = {extract(e) for e in ev_b} - {""}
        differs = bool(vals_a and vals_b and not (vals_a & vals_b))
        return {"a": sorted(vals_a), "b": sorted(vals_b), "differs": differs}

    def assess_all(self, project_id: str) -> list[tuple[str, ContradictionAssessment]]:
        out = []
        for c in self.repos.contradictions.all(project_id):
            out.append((c.id, self.assess(project_id, c)))
        return out


def _claim_evidence(repos, project_id, claim_id):
    claim = repos.claims.get(claim_id)
    return claim.supported_by if claim else []


def _geo(text: str) -> str:
    t = text.lower()
    for g in ("global", "usa", "united states", "us market", "india", "europe", "china",
              "united kingdom", " uk"):
        if g in t:
            return g
    return ""


def _metric(text: str) -> str:
    m = _DIMENSION_KEYWORDS["metric"].search(text or "")
    return m.group(0).lower() if m else ""
