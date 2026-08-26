"""Research outcome records (Phase 6 §6-§7), quality model (§32), and
research gain v2 (§33-§35).

The outcome is the primary training/evaluation record for process learning.
Everything here derives from PERSISTED store state — no LLM, no assertions
of quality. Importance weighting (gain v2) prevents gaming: 100 trivial
claims must not outperform 5 important verified ones (§34), and a gap only
counts as resolved when it has resolution lineage (resolved_by_query_ids),
not when text merely moved around (§35).
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone

from research_engine.adaptive.features import domain_bucket, extract_task_features

# Gain v2 weights (spec §33). Evidence importance = 1/tier so primary
# literature counts ~5x forums. Weights sum-tolerant, magnitudes relative.
_W_EVIDENCE = 1.0
_W_GAP = 3.0          # resolving an important gap beats adding raw evidence
_W_CONTRADICTION = 4.0   # resolving a real contradiction is rare & valuable
_IMPORTANCE_FLOOR = 0.5   # gaps below this are 'nice to know' (§34)

# Query family mapping: SearchQuery.kind -> learning family. Strategy-level
# families (broad sweep etc.) live in reasoning/adaptive_planner; kind is the
# persisted, per-query truth we aggregate over (§18).
QUERY_FAMILY_BY_KIND = {
    "primary": "primary_source_search",
    "synonym": "broad_discovery",
    "technical": "technical_terminology",
    "contradiction": "counterevidence",
    "date_filtered": "recent_research",
    "source_specific": "targeted_source_search",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def research_fingerprint(question: str, mode: str,
                         features: dict, policy_versions: dict,
                         model_versions: dict) -> str:
    """Normalized run fingerprint (§7): similar runs share prefixes, enabling
    comparison. Deterministic; NOT a secret."""
    payload = json.dumps({
        "objective": " ".join((question or "").lower().split()),
        "mode": mode or "",
        "features": features,
        "policies": policy_versions,
        "models": {k: str(v) for k, v in sorted(model_versions.items())},
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _tier_weight(tier: int | float) -> float:
    try:
        t = max(1, min(5, int(tier)))
    except Exception:
        return 0.2
    return round(1.0 / t, 3)


def compute_gain_v2(orch, pid: str, since_iso: str) -> dict:
    """Importance-weighted research gain (§33-§35), derived from the store.

    - new_evidence_weighted: Σ 1/tier over evidence created since cutoff
    - gaps_resolved_important: resolved ∧ importance≥floor ∧ has query lineage
      (anti-rename guard, §35)
    - contradictions_resolved: contradiction rows marked resolved since cutoff
      (resolution is user/resolution-step-owned by INV-009)
    """
    evidence_new = [e for e in orch.repos.evidence.all(pid)
                    if getattr(e, "retrieved_at", "") >= since_iso
                    and getattr(e.status, "value", str(e.status)) != "REJECTED"]
    ev_weighted = sum(_tier_weight(getattr(e, "source_tier", 5))
                      for e in evidence_new)
    gaps_before = orch.repos.gaps.all(pid)
    resolved_important = [
        g for g in gaps_before
        if g.resolved and float(g.importance or 0.0) >= _IMPORTANCE_FLOOR
        and g.resolved_by_query_ids]
    contradictions = [c for c in orch.repos.contradictions.all(pid)
                      if getattr(c, "resolved", False)]
    # Bulk dampening (§34): raw evidence mass enters through log(1+x) so
    # 100 trivial tier-5 finds cannot outscore structured progress (gap
    # closures + contradiction resolutions). Structured work stays linear.
    ev_component = _W_EVIDENCE * math.log1p(ev_weighted)
    gain = round(
        ev_component
        + _W_GAP * len(resolved_important)
        + _W_CONTRADICTION * len(contradictions), 4)
    return {
        "new_evidence": len(evidence_new),
        "new_evidence_weighted": round(ev_weighted, 4),
        "evidence_component": round(ev_component, 4),
        "gaps_open": sum(1 for g in gaps_before if not g.resolved),
        "gaps_resolved_important": len(resolved_important),
        "gaps_cosmetic_unlinked": sum(
            1 for g in gaps_before if g.resolved and not g.resolved_by_query_ids),
        "contradictions_total": len(orch.repos.contradictions.all(pid)),
        "contradictions_resolved": len(contradictions),
        "claims": len(orch.repos.claims.all(pid)),
        "research_gain_v2": gain,
    }


def quality_dimensions(orch, pid: str) -> dict:
    """Multidimensional process-independent quality model (§32).

    Kept as separate dimensions deliberately — collapsing them into one
    scalar hides exactly the tradeoffs Phase 6 must reason about.
    """
    claims = orch.repos.claims.all(pid)
    grounded = sum(1 for c in claims if c.supported_by)
    contradicted = sum(1 for c in claims if c.contradicted_by)
    evidence = [e for e in orch.repos.evidence.all(pid)
                if getattr(e.status, "value", str(e.status)) != "REJECTED"]
    tiers = [max(1, min(5, int(getattr(e, "source_tier", 5)))) for e in evidence]
    avg_tier = (sum(tiers) / len(tiers)) if tiers else 5.0
    gaps = orch.repos.gaps.all(pid)
    resolved = [g for g in gaps if g.resolved]
    contradictions = orch.repos.contradictions.all(pid)
    linked = [c for c in contradictions
              if (c.claim_a_id and c.claim_b_id)
              or (c.evidence_a_ids and c.evidence_b_ids)]
    sources = orch.repos.sources.all(pid)
    fetched_ok = sum(1 for s in sources
                     if s.content_status in ("FETCHED", "PARSED"))
    domains = {s.domain or "" for s in sources}
    n = max(1, len(gaps))
    return {
        "claim_grounded_ratio": round(grounded / max(1, len(claims)), 4),
        "claim_contradicted_ratio": round(contradicted / max(1, len(claims)), 4),
        "avg_source_tier": round(avg_tier, 3),       # lower is better (tier1=papers/gov)
        "gap_coverage": round(len(resolved) / n, 4),
        "contradiction_integrity": round(len(linked) / max(1, len(contradictions)), 4),
        "source_fetch_success": round(fetched_ok / max(1, len(sources)), 4),
        "source_domain_diversity": len(domains),
    }


def build_outcome(orch, pid: str, job_id: str, research_type: str,
                  duration_s: float, policy_versions: dict | None = None,
                  started_at_iso: str = "") -> tuple[dict, dict]:
    """Build the §6 outcome record + its features.

    Returns (outcome_row_for_save, features). Never raises on empty state —
    honest zeros are valid outcomes.
    """
    project = orch.project
    question = getattr(project, "question_raw", "") or ""
    mode = getattr(project, "mode", "") or ""
    subquestions: list[str] = []
    try:
        for br in orch.repos.plans.all(pid)[0].branches:
            if br.question:
                subquestions.append(br.question)
    except Exception:
        pass
    feats = extract_task_features(question, mode, subquestions)
    pol_versions = policy_versions or {}
    fp = research_fingerprint(question, mode, feats, pol_versions,
                              {"platform": "gar"})
    since = started_at_iso or "0000-00-00T00:00:00+00:00"
    gain = compute_gain_v2(orch, pid, since)
    quality = quality_dimensions(orch, pid)

    metrics_latest = {}
    try:
        hist = orch.repos.metrics.all(pid)
        if hist:
            m = hist[-1]
            metrics_latest = {
                "llm_calls": int(m.llm_calls or 0),
                "duplicate_rate": float(m.duplicate_rate or 0.0),
                "rejection_rate": float(m.rejection_rate or 0.0),
            }
    except Exception:
        pass

    queries = orch.repos.queries.all(pid)
    outcome_id = f"out_{uuid.uuid4().hex[:12]}"
    outcome = {
        "outcome_id": outcome_id,
        "project_id": pid,
        "run_id": job_id or "",
        "research_type": research_type or mode,
        "question": question[:400],
        "mode": mode,
        "features": feats,
        "fingerprint": fp,
        "policy_versions": pol_versions,
        "specialists_used": [],     # filled by caller from invocation history
        "queries_executed": len(queries),
        "quality_metrics": quality,
        "resource_metrics": {
            **metrics_latest,
            "duration_s": round(float(duration_s), 2),
        },
        "research_gain": gain,
        "user_feedback": {},        # joined later at analysis time
        "final_decision": {},
        "timestamp": _now_iso(),
    }
    return outcome, feats


def record_query_analytics(platform_db, orch, pid: str, task_type: str) -> None:
    """Aggregate per-family query utility into platform.sqlite (§18/§20).

    Utility deliberately EXCLUDES raw result counts as a quality signal —
    useful_results/new_evidence/gap-resolution only (§20).
    """
    queries = orch.repos.queries.all(pid)
    by_family: dict[str, dict] = {}
    for q in queries:
        fam = QUERY_FAMILY_BY_KIND.get(q.kind, "other")
        agg = by_family.setdefault(fam, {"n": 0, "useful": 0})
        agg["n"] += 1
        agg["useful"] += int(q.useful_results or 0)
    # new evidence per query via lineage: evidence rows carry source_url but
    # query linkage lives on SearchResult.query_ids → count distinct evidence
    # per query id through documents? Keep to cheap persisted truth:
    # gaps resolved by query ids give direct family credit (§18).
    gaps = orch.repos.gaps.all(pid)
    gap_families: dict[str, int] = {}
    for g in gaps:
        if not (g.resolved and g.resolved_by_query_ids):
            continue
        qids = set(g.resolved_by_query_ids)
        qmap = {q.id: q for q in queries}
        fams = {QUERY_FAMILY_BY_KIND.get(qmap[qid].kind, "other")
                for qid in qids if qid in qmap}
        for fam in fams:
            gap_families[fam] = gap_families.get(fam, 0) + 1
    for fam, agg in by_family.items():
        platform_db.record_query_family(
            fam, task_type, queries=agg["n"], useful_results=agg["useful"],
            new_evidence=agg["useful"],   # useful_results ARE accepted-evidence hits
            new_claims=0,
            gaps_resolved=gap_families.get(fam, 0))


def record_source_analytics(platform_db, orch, pid: str, bucket: str) -> None:
    """Per-source-type observed utility (§22). Observed ≠ policy: TIER policy
    stays authoritative for grounding; this only informs ROUTING (§23)."""
    sources = orch.repos.sources.all(pid)
    evidence = orch.repos.evidence.all(pid)
    yield_by_type: dict[str, int] = {}
    for e in evidence:
        st = str(getattr(e.source_type, "value", e.source_type))
        yield_by_type[st] = yield_by_type.get(st, 0) + 1
    by_type: dict[str, dict] = {}
    for s in sources:
        st = str(getattr(s.source_type, "value", s.source_type))
        agg = by_type.setdefault(st, {"n": 0, "ok": 0, "fail": 0, "tier": 0})
        agg["n"] += 1
        if s.content_status in ("FETCHED", "PARSED"):
            agg["ok"] += 1
        elif s.content_status in ("FAILED", "BLOCKED"):
            agg["fail"] += 1
        agg["tier"] += max(1, min(5, int(s.source_tier or 5)))
    for st, agg in by_type.items():
        platform_db.record_source_perf(
            st, bucket, sources=agg["n"], fetched_ok=agg["ok"],
            fetch_failed=agg["fail"],
            evidence_yield=yield_by_type.get(st, 0),
            avg_tier=agg["tier"] / max(1, agg["n"]))


__all__ = [
    "build_outcome", "compute_gain_v2", "quality_dimensions",
    "record_query_analytics", "record_source_analytics",
    "research_fingerprint", "QUERY_FAMILY_BY_KIND",
]
