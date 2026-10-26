"""Gap detection: LLM-proposed gaps + deterministic rule-based gaps.

Rule-based detectors guarantee certain gap classes exist even with a weak model:
- UNVERIFIED_NUMERIC_CLAIM (numbers without period/context)
- WEAK_EVIDENCE (claims supported only by tier>=4 sources)
- MISSING_SOURCE_TYPE (plan demands a source class never retrieved)
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from research_engine.models.analysis import Gap, RecommendedQuery
from research_engine.models.enums import GapCategory, Severity
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class _QueryOut(BaseModel):
    text: str = ""
    reason: str = ""


class _GapOut(BaseModel):
    description: str = ""
    category: str = ""
    importance: float = 0.5
    severity: str = "medium"
    evidence_needed: str = ""
    branch: str = ""
    recommended_queries: list[_QueryOut] = Field(default_factory=list)


class GapsOutput(BaseModel):
    gaps: list[_GapOut] = Field(default_factory=list)


VALID_CATEGORIES = {c.value for c in GapCategory}


class GapDetector:
    def __init__(self, provider: LLMProvider, repos: Repositories):
        self.provider = provider
        self.repos = repos

    def run(self, project_id: str, plan, problem, iteration: int, mode: str = "academic") -> list[Gap]:
        existing_gaps = self.repos.gaps.all(project_id)
        from research_engine.reasoning.structural_gaps import StructuralGapDetector
        rule_gaps = self._rule_based_gaps(project_id, plan)
        rule_gaps += StructuralGapDetector(self.repos).detect(project_id, mode)
        llm_gaps = self._llm_gaps(project_id, plan, problem, iteration)

        existing_open = [g for g in existing_gaps if not g.resolved]
        candidates = rule_gaps + llm_gaps
        merged: list[Gap] = []
        seen_descs: list[str] = []
        for g in candidates:
            # reuse an already-open gap with the same substance (stable IDs across iterations)
            match = next((old for old in existing_open
                          if _overlap(old.description, g.description)), None)
            if match is not None:
                if match not in merged:
                    merged.append(match)
                continue
            if any(_overlap(g.description, d) for d in seen_descs):
                continue
            seen_descs.append(g.description.lower())
            merged.append(g)
        for old in existing_open:
            still_present = any(m.id == old.id or _overlap(old.description, m.description)
                                for m in merged)
            if not still_present:
                merged.append(old)
        for g in merged:
            g.project_id = project_id
            if not g.id or not self.repos.gaps.get(g.id):
                g.iteration_found = iteration
                g.ensure_id()
                self.repos.gaps.save(g)
        # mark resolved: previously open gaps now covered by an accepted claim
        self._update_resolved(project_id, existing_gaps, iteration)
        return merged

    def _llm_gaps(self, project_id, plan, problem, iteration) -> list[Gap]:
        claims = self.repos.claims.all(project_id)
        contradictions = self.repos.contradictions.all(project_id)
        claims_summary = "\n".join(
            f"{c.id}: {c.text[:140]} [{c.kind.value}] supported_by={len(c.supported_by)}"
            for c in claims[:60]) or "(none)"
        branches_summary = "\n".join(
            f"{b.id} {b.category}: {b.question[:100]} status={b.status}"
            for b in plan.branches) if plan else "(no plan)"
        contradictions_summary = "\n".join(
            f"{k.id}: {k.statement_a[:80]} VS {k.statement_b[:80]}"
            for k in contradictions[:15]) or "(none)"
        source_coverage = self._source_coverage(project_id)
        spec = get_prompt("gap_analyzer")
        user = spec.render(objective=problem.objective, branches_summary=branches_summary,
                           claims_summary=claims_summary,
                           contradictions_summary=contradictions_summary,
                           source_coverage=source_coverage)
        out, errors = self.provider.structured(spec.system, user, GapsOutput)
        gaps: list[Gap] = []
        if out is None:
            log.warning("LLM gap analysis failed: %s", errors[-1:])
            return []
        for g in out.gaps:
            cat = g.category.upper()
            sev = {"low": Severity.LOW, "high": Severity.HIGH}.get(g.severity.lower(), Severity.MEDIUM)
            branch = next((b.id for b in (plan.branches if plan else [])
                           if b.id == g.branch or g.branch in b.question), "")
            gaps.append(Gap(
                description=g.description[:400],
                category=GapCategory(cat) if cat in VALID_CATEGORIES else GapCategory.MISSING_INFORMATION,
                importance=min(max(g.importance, 0.0), 1.0),
                severity=sev, evidence_needed=g.evidence_needed[:300], branch=branch,
                recommended_queries=[RecommendedQuery(text=q.text, reason=q.reason)
                                     for q in g.recommended_queries if q.text][:3],
            ))
        return gaps

    def _rule_based_gaps(self, project_id, plan) -> list[Gap]:
        gaps: list[Gap] = []
        evidence = self.repos.evidence.all(project_id, "status!='REJECTED'")
        claims = self.repos.claims.all(project_id)
        ev_by_id = {e.id: e for e in evidence}

        # zero-evidence state: the most fundamental gap
        if not evidence and plan is not None:
            gaps.append(Gap(
                description="No accepted evidence has been collected yet for any branch.",
                category=GapCategory.MISSING_INFORMATION, importance=0.95, severity=Severity.HIGH,
                evidence_needed="Any credible source content addressing a plan branch.",
                recommended_queries=[RecommendedQuery(
                    text=b.question[:120], reason=f"branch {b.category}")
                    for b in plan.branches[:3]],
            ))

        # numeric claims missing period/context -> UNVERIFIED_NUMERIC_CLAIM
        numeric_weak = [e for e in evidence
                        if e.numbers and any((not n.period and not n.context) for n in e.numbers)]
        if numeric_weak:
            gaps.append(Gap(
                description=f"{len(numeric_weak)} numeric evidence items lack period/context "
                            "and cannot be interpreted safely.",
                category=GapCategory.UNVERIFIED_NUMERIC_CLAIM, importance=0.8, severity=Severity.HIGH,
                evidence_needed="Numbers with explicit metric, unit, currency, period and context.",
            ))
        # claims only supported by tier 4-5 -> WEAK_EVIDENCE
        weak_claims = [c for c in claims
                       if c.supported_by and all(ev_by_id[e].source_tier >= 4
                                                 for e in c.supported_by if e in ev_by_id)]
        if weak_claims:
            gaps.append(Gap(
                description=f"{len(weak_claims)} claims rest solely on low-tier sources (forums/blogs/unknown).",
                category=GapCategory.WEAK_EVIDENCE, importance=0.7, severity=Severity.MEDIUM,
                evidence_needed="Corroboration from tier 1-3 sources.",
            ))
        # plan branches with zero evidence -> UNDERREPRESENTED_SUBTOPIC / MISSING_INFORMATION
        if plan:
            covered_branches = {e.branch for e in evidence if e.branch}
            for b in plan.branches:
                if b.importance >= 0.5 and b.status != "answered":
                    has_ev = any(e.document_id for e in evidence)  # any evidence at all
                    branch_has = bool(covered_branches & {b.id}) or (
                        b.question.lower()[:40] and
                        any(b.question.lower()[:30] in e.claim_text.lower() for e in evidence))
                    if not branch_has and b.importance >= 0.6:
                        gaps.append(Gap(
                            description=f"No evidence collected yet for important branch: {b.question[:150]}",
                            category=GapCategory.UNDERREPRESENTED_SUBTOPIC,
                            importance=b.importance, severity=Severity.HIGH,
                            evidence_needed=b.required_evidence or "any credible supporting evidence",
                            branch=b.id,
                        ))
        return gaps

    def _source_coverage(self, project_id) -> str:
        sources = self.repos.sources.all(project_id, "status IN ('PARSED','FETCHED')")
        by_type: dict[str, int] = {}
        for s in sources:
            by_type[s.source_type.value] = by_type.get(s.source_type.value, 0) + 1
        tiers: dict[int, int] = {}
        for s in sources:
            tiers[s.source_tier] = tiers.get(s.source_tier, 0) + 1
        return f"types={by_type} tiers={dict(sorted(tiers.items()))}"

    def _update_resolved(self, project_id, existing_gaps, iteration) -> None:
        claims = self.repos.claims.all(project_id)
        claim_texts = " || ".join(c.text.lower() for c in claims)
        for g in existing_gaps:
            if g.resolved or not g.recommended_queries:
                continue
            # a gap is resolved when a claim now covers its core description keywords
            key_terms = [w for w in g.description.lower().split() if len(w) > 5][:6]
            hits = sum(1 for w in key_terms if w in claim_texts)
            if key_terms and hits / len(key_terms) >= 0.6 and len(claims) > 2:
                g.resolved = True
                g.iteration_resolved = iteration
                self.repos.gaps.save(g)


def _overlap(a: str, b: str) -> bool:
    aw = set(w for w in a.lower().split() if len(w) > 4)
    bw = set(w for w in b.lower().split() if len(w) > 4)
    if not aw or not bw:
        return False
    return len(aw & bw) / min(len(aw), len(bw)) >= 0.6
