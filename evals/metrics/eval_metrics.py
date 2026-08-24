"""Evaluation metrics for retrieval, evidence, research process, and system health.

All metrics are computed from persisted project state, so any benchmark run can
be scored identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from research_engine.storage.repositories import Repositories


@dataclass
class EvalScores:
    # retrieval
    primary_source_ratio: float = 0.0
    source_diversity_domains: int = 0
    sources_accepted: int = 0
    sources_rejected: int = 0
    # evidence
    quote_correctness: float = 1.0     # fraction of stored evidence whose quotes verify
    rejected_evidence_ratio: float = 0.0
    citation_coverage: float = 0.0     # claims with >=1 supporting evidence
    duplicate_rate: float = 0.0
    # research
    subquestion_coverage: float = 0.0
    gaps_discovered: int = 0
    gaps_resolved: int = 0
    contradictions_found: int = 0
    new_information_rate: float = 0.0
    # system
    llm_calls: int = 0
    queries_executed: int = 0
    wall_clock_seconds: float = 0.0
    errors: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"retrieval:   primary_ratio={self.primary_source_ratio:.2f} "
            f"domains={self.source_diversity_domains} accepted={self.sources_accepted} "
            f"rejected={self.sources_rejected}",
            f"evidence:    quote_ok={self.quote_correctness:.2f} dup_rate={self.duplicate_rate:.2f} "
            f"citation_coverage={self.citation_coverage:.2f}",
            f"research:    subq_cov={self.subquestion_coverage:.2f} gaps={self.gaps_discovered} "
            f"(resolved {self.gaps_resolved}) contradictions={self.contradictions_found}",
            f"system:      llm_calls={self.llm_calls} queries={self.queries_executed} "
            f"errors={self.errors} secs={self.wall_clock_seconds:.0f}",
        ]
        return "\n".join(lines)


def score_project(repos: Repositories, project_id: str,
                  expected_subquestions: list[str] | None = None) -> EvalScores:
    s = EvalScores()
    srcs = repos.sources.all(project_id)
    accepted = [x for x in srcs if x.content_status == "PARSED"]
    s.sources_accepted = len(accepted)
    s.sources_rejected = len([x for x in srcs if x.content_status in ("FAILED", "BLOCKED")])
    if accepted:
        s.primary_source_ratio = (len([x for x in accepted if x.source_tier <= 2])
                                  / len(accepted))
        s.source_diversity_domains = len({x.domain for x in accepted})

    evidence = repos.evidence.all(project_id)
    ok_ev = [e for e in evidence if e.status.value != "REJECTED"]
    s.rejected_evidence_ratio = (len(evidence) - len(ok_ev)) / len(evidence) if evidence else 0.0
    s.duplicate_rate = repos.evidence.rejected_ratio(project_id)

    from research_engine.pipeline.evidence import verify_quote
    checked = failed = 0
    chunks = {c.id: c.text for c in repos.chunks.all(project_id)}
    for e in ok_ev:
        ct = chunks.get(e.chunk_id)
        if ct is None:
            continue
        checked += 1
        if not verify_quote(e.quote, ct)[0]:
            failed += 1
    s.quote_correctness = (checked - failed) / checked if checked else 1.0
    if not checked:
        s.notes.append("no chunk text available for quote re-verification")

    claims = repos.claims.all(project_id)
    if claims:
        s.citation_coverage = (len([c for c in claims if c.supported_by]) / len(claims))

    if expected_subquestions:
        covered = 0
        claim_text = " ".join(c.text.lower() for c in claims)
        ev_text = " ".join((e.claim_text + " " + e.quote).lower() for e in ok_ev)
        corpus = claim_text + " " + ev_text
        for sq in expected_subquestions:
            words = [w for w in sq.lower().split() if len(w) > 4]
            if words and sum(1 for w in words if w in corpus) / len(words) >= 0.5:
                covered += 1
        s.subquestion_coverage = covered / len(expected_subquestions)

    s.gaps_discovered = repos.gaps.count(project_id)
    s.gaps_resolved = repos.gaps.count(project_id, "resolved=1")
    s.contradictions_found = repos.contradictions.count(project_id)
    metrics = sorted(repos.metrics.all(project_id), key=lambda m: m.iteration)
    if metrics:
        last = metrics[-1]
        total_ev = max(1, repos.evidence.count(project_id, "status!='REJECTED'"))
        s.new_information_rate = last.new_evidence_this_iter / total_ev
        s.llm_calls = last.llm_calls
    s.queries_executed = repos.queries.count(project_id, "executed=1")
    s.errors = repos.tasks.count(project_id, "status IN ('FAILED','DEAD')")
    return s
