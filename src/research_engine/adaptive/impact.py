"""Change impact analysis + research alerts (Phase 6 §81-§84).

When new evidence arrives (research run, watcher, experiment), traverse the
existing dependency graph evidence → claims → hypotheses → opportunities and
raise ranked alerts. Traversal uses ONLY persisted links — no inference.
"""
from __future__ import annotations

import json


# Alert kinds (§83) — deliberately few; noise is the enemy.
HIGH_IMPACT_NEW_EVIDENCE = "HIGH_IMPACT_NEW_EVIDENCE"
CLAIM_CONTRADICTION = "CLAIM_CONTRADICTION"
OPPORTUNITY_WEAKENED = "OPPORTUNITY_WEAKENED"
HYPOTHESIS_FALSIFIED = "HYPOTHESIS_FALSIFIED"


def analyze_new_evidence(orch, pid: str, new_evidence_ids: list[str]) -> dict:
    """Downstream impact of specific new evidence rows. Pure traversal."""
    claims_hit, hyps_hit, opps_hit = [], [], []
    ev_set = set(new_evidence_ids)
    for c in orch.repos.claims.all(pid):
        if ev_set & set(c.contradicted_by):
            claims_hit.append({"claim_id": c.id, "relation": "contradicted"})
        elif ev_set & set(c.supported_by):
            claims_hit.append({"claim_id": c.id, "relation": "supported"})
    claim_ids = {h["claim_id"] for h in claims_hit}
    try:
        hypotheses = [h for h in orch.repos.hypotheses.all(pid)]
    except Exception:
        hypotheses = []
    for h in hypotheses:
        touched = ev_set & (set(h.supporting_evidence) |
                            set(h.contradicting_evidence))
        if not touched:
            continue
        falsified = bool(ev_set & set(h.contradicting_evidence))
        hyps_hit.append({"hypothesis_id": h.id,
                         "relation": "contradicted" if falsified
                         else "supported"})
    try:
        opportunities = orch.repos.opportunities.all(pid)
    except Exception:
        opportunities = []
    for o in opportunities:
        linked = ev_set & (set(o.evidence_ids) |
                           set(o.market_signal_evidence_ids))
        if linked:
            # severity drop vs peers marks weakening; absence of market
            # signal evidence marks fragility — both are honest signals.
            weak = float(o.severity or 0) < 0.4 or \
                not o.market_signal_evidence_ids
            opps_hit.append({"opportunity_id": o.id,
                             "weakened": weak})
    return {"claims": claims_hit, "hypotheses": hyps_hit,
            "opportunities": opps_hit}


def raise_impact_alerts(db, orch, pid: str, new_evidence_ids: list[str],
                        source: str = "") -> list[dict]:
    """Compute impact and persist ranked alerts (§84 score =
    impact × confidence × recency × decision_relevance)."""
    impact = analyze_new_evidence(orch, pid, new_evidence_ids)
    raised: list[dict] = []
    n_ev = max(1, len(new_evidence_ids))

    def _emit(kind, severity, imp, conf, rel, payload):
        seed = json.dumps([pid, kind, sorted(payload.items())],
                          default=str, sort_keys=True)
        alert_id = f"al_{abs(hash(seed)) % 10**10}"
        score = db.raise_alert(alert_id, pid, kind, severity, impact=imp,
                               confidence=conf, decision_relevance=rel,
                               payload={**payload, "source": source},
                               recency=1.0)
        raised.append({"alert_id": alert_id, "kind": kind,
                       "severity": severity, "score": score})

    contradicted = [c for c in impact["claims"]
                    if c["relation"] == "contradicted"]
    if contradicted:
        _emit(CLAIM_CONTRADICTION, "high",
              min(1.0, len(contradicted) / 3), 0.9, 0.9,
              {"claims": contradicted[:10]})
    falsified = [h for h in impact["hypotheses"]
                 if h["relation"] == "contradicted"]
    if falsified:
        _emit(HYPOTHESIS_FALSIFIED, "high", 0.8, 0.85, 0.95,
              {"hypotheses": falsified[:10]})
    weakened = [o for o in impact["opportunities"] if o["weakened"]]
    if weakened:
        _emit(OPPORTUNITY_WEAKENED, "medium", 0.6, 0.7, 0.9,
              {"opportunities": weakened[:10]})
    if len(new_evidence_ids) >= 5:
        _emit(HIGH_IMPACT_NEW_EVIDENCE, "info",
              min(1.0, n_ev / 20), 0.6, 0.5, {"new_evidence": n_ev})
    return raised


def rank_alerts(alerts: list[dict]) -> list[dict]:
    """DB already stores composite score; this re-sorts defensively."""
    return sorted(alerts, key=lambda a: -float(a.get("score") or 0.0))
