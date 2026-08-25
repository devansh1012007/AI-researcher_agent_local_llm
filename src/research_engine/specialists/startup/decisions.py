"""Decision engine: readiness levels, research-vs-validation transition,
efficiency tracking, final recommendations, founder fit, portfolio.

Discipline:
- Readiness depends on EVIDENCE COVERAGE + critical assumptions, never on
  iteration counts (spec #69).
- When the biggest uncertainty is customer behavior, the system must
  recommend real-world validation instead of more web searches (spec #70).
- Market attractiveness and founder-specific feasibility are reported
  SEPARATELY and never mixed silently (spec #51/#84).
- Recommendations follow the fixed decision-oriented format and always state
  what evidence would change them (spec #75).
"""
from __future__ import annotations

import re

from research_engine.specialists.startup.policies import (
    CUSTOMER_BEHAVIOR_UNCERTAINTIES, QUALITY_GATE_REQUIREMENTS, READINESS_LEVELS)
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories


class DecisionEngine:
    def __init__(self, repos: Repositories, rrepos: ReasoningRepos, srepos=None):
        self.repos = repos
        self.rrepos = rrepos
        self.srepos = srepos

    # ------------------------------------------------------------- readiness
    def readiness(self, project_id: str, opportunity_id: str = "",
                  gate: dict | None = None) -> dict:
        """NOT_READY -> DECISION_READY from coverage dimensions (spec #69)."""
        checks = dict(gate.get("checks", {})) if gate else \
            {req: False for req in QUALITY_GATE_REQUIREMENTS}
        covered = sum(1 for v in checks.values() if v)
        ratio = covered / max(1, len(QUALITY_GATE_REQUIREMENTS))

        # critical assumptions with results?
        asm = [a for a in self.rrepos.assumptions.all(project_id)
               if not opportunity_id or a.opportunity_id == opportunity_id]
        tested = [a for a in asm if a.status in ("verified", "falsified")]
        critical_untested = [a for a in asm
                             if a.kind == "critical" and a.status == "unverified"]

        experiments = self.rrepos.experiments.all(project_id)
        has_tests = bool(experiments)

        if len(tested) >= 2 and all(a.status != "falsified" for a in tested) \
                and not critical_untested:
            level = "DECISION_READY"
        elif tested and any(a.status == "verified" for a in tested):
            level = "PILOT_READY"
        elif has_tests and covered >= 0.7:
            level = "VALIDATION_READY"
        elif covered >= 0.4:
            level = "RESEARCH_READY"
        else:
            level = "NOT_READY"
        return {
            "level": level,
            "levels": READINESS_LEVELS,
            "coverage": {"covered": covered,
                         "total": len(QUALITY_GATE_REQUIREMENTS),
                         "ratio": round(ratio, 2)},
            "missing_dimensions": [k for k, v in checks.items() if not v],
            "critical_assumptions_untested": len(critical_untested),
            "assumptions_tested": {"verified":
                                   sum(1 for a in tested if a.status == "verified"),
                                   "falsified":
                                   sum(1 for a in tested if a.status == "falsified")},
        }

    # ------------------------------------------------------- transition rule
    def next_action(self, project_id: str, opportunity_id: str = "",
                    assumptions: list | None = None) -> dict:
        """More internet research vs real-world validation vs experiment
        (spec #68/#70). Deterministic."""
        from research_engine.reasoning.decision_layer import classify_uncertainty

        unc = None
        try:
            unc = classify_uncertainty(self.repos, project_id)
        except Exception:
            unc = {}
        behavioral = None
        if assumptions:
            ranked = sorted(assumptions, key=lambda a: -getattr(a, "priority", 0.5))
            for a in ranked[:3]:
                cat = getattr(a, "category", "") or ""
                if cat in CUSTOMER_BEHAVIOR_UNCERTAINTIES:
                    behavioral = {"assumption_id": a.id, "category": cat,
                                  "statement": a.statement[:160]}
                    break

        open_gaps = self.repos.gaps.count(project_id, "resolved=0")
        ev_count = self.repos.evidence.count(project_id, "status!='REJECTED'")

        if behavioral is not None:
            action = "customer_validation"
            why = (f"biggest uncertainty is '{behavioral['category']}' — a customer "
                   "behavior question no amount of web search can resolve")
            concrete = {
                "willingness_to_pay": "run a pricing test: refundable preorders or "
                                      "signed LOIs from 10+ budget holders",
                "frequency": "observe 10-15 target users' actual workflow unmodified",
                "severity": "problem interviews about the LAST occurrence",
                "switching": "prototype test with current-vendor users for >=1 week",
                "retention": "usage measurement across >=4 weeks with design partners",
            }.get(behavioral["category"], "design the cheapest behavioral test")
        elif open_gaps > 3:
            action = "continue_research"
            why = f"{open_gaps} open research gaps remain; targeted retrieval still cheap"
            concrete = "resolve highest-priority gaps via recommended queries"
        elif ev_count < 10:
            action = "continue_research"
            why = f"only {ev_count} accepted evidences — corpus too thin to reason over"
            concrete = "broaden retrieval across source categories"
        else:
            action = "synthesize_decision"
            why = ("coverage sufficient and no dominant behavioral uncertainty — "
                   "time to compare opportunities and decide")
            concrete = "run startup compare on top candidates"
        return {"action": action, "why": why, "concrete_next_step": concrete,
                "behavioral_uncertainty": behavioral,
                "open_gaps": open_gaps, "evidence_count": ev_count}

    # ------------------------------------------------------- efficiency
    def research_efficiency(self, project_id: str) -> dict:
        """New useful evidence per query / per model call (spec #71)."""
        m_rows = self.repos.metrics.all(project_id)
        if not m_rows:
            return {"new_evidence_per_query": None, "note": "no metrics yet"}
        last = m_rows[-1]
        queries = sum(getattr(m, "queries_executed", 0) or 0 for m in m_rows)
        new_ev = sum(getattr(m, "new_evidence_this_iter", 0) or 0 for m in m_rows)
        llm_calls = sum(getattr(m, "llm_calls", 0) or 0 for m in m_rows)
        per_query = round(new_ev / queries, 3) if queries else None
        out = {"new_evidence_total": new_ev, "queries_executed": queries,
               "llm_calls": llm_calls,
               "new_evidence_per_query": per_query}
        out["verdict"] = ("low_yield_research" if
                          (per_query is not None and per_query < 0.5 and new_ev > 20)
                          else "productive")
        return out

    # ------------------------------------------------------- recommendation
    def recommend(self, project_id: str, opp, gate: dict, readiness: dict,
                  assumptions: list, counter_pair: dict | None = None) -> dict:
        """Fixed decision-oriented recommendation format (spec #75)."""
        priority = gate.get("priority", "low") if gate else "low"
        missing = gate.get("missing", []) if gate else QUALITY_GATE_REQUIREMENTS
        next_a = self.next_action(project_id, opp.id if opp else "", assumptions)

        if gate and gate.get("speculative"):
            decision = "continue_researching"
        elif priority == "high" and readiness["level"] in ("VALIDATION_READY",
                                                           "PILOT_READY",
                                                           "DECISION_READY"):
            decision = "start_validating"
        elif priority == "medium" or readiness["level"] == "RESEARCH_READY":
            decision = "continue_researching"
        elif counter_pair and re.search(
                r"dominant incumbent|distribution_difficult|unwilling to pay",
                counter_pair.get("strongest_argument_against", ""), re.I):
            decision = "modify"
        else:
            decision = "compare"

        most_important = ""
        if assumptions:
            top = sorted(assumptions, key=lambda a: -getattr(a, "priority", 0.5))[0]
            most_important = top.statement[:180]

        what_would_change = (
            f"if {' / '.join(missing[:3]) or 'no dimensions'} get resolved with "
            "strong evidence, the recommendation upgrades; if the most important "
            "assumption fails its cheapest test, abandon")
        return {
            "decision": decision,
            "recommendation_text": {
                "continue_researching":
                    "keep researching — coverage gaps block a validation bet",
                "start_validating":
                    "move to staged real-world validation starting with the cheapest decisive test",
                "modify": "re-shape the opportunity around the counterevidence before investing",
                "compare": "put this side-by-side with alternatives before committing effort",
                "abandon": "core assumption falsified — stop investing here",
            }[decision],
            "evidence_supporting": (counter_pair or {}).get("strongest_argument_for", ""),
            "evidence_against": (counter_pair or {}).get("strongest_argument_against", ""),
            "critical_uncertainty": (next_a.get("behavioral_uncertainty") or
                                     {}).get("category", "coverage gaps"),
            "most_important_assumption": most_important,
            "best_next_action": next_a["concrete_next_step"],
            "what_would_change_this_recommendation": what_would_change,
        }

    # ------------------------------------------------------- founder fit
    def founder_fit(self, opportunity_score: dict, profile) -> dict:
        """Separate market attractiveness from founder feasibility (spec #84)."""
        attractiveness = (opportunity_score.get("total", 0.0)
                          if isinstance(opportunity_score, dict) else 0.0)
        feasibility = 0.5
        notes = []
        if profile is not None:
            skills = {s.lower() for s in (profile.skills or [])}
            tech_caps = {s.lower() for s in (profile.technical_capabilities or [])}
            access = {s.lower() for s in (profile.industry_access or [])}
            network = {s.lower() for s in (profile.network or [])}
            seg = (opportunity_score.get("segment", "") or "").lower()

            if skills or tech_caps:
                feasibility += 0.15
                notes.append("technical/skill base present")
            else:
                feasibility -= 0.2
                notes.append("no relevant technical capability declared")
            if access and any(a in seg for a in access):
                feasibility += 0.2
                notes.append(f"industry access overlaps target segment '{seg}'")
            elif access:
                feasibility += 0.05
                notes.append("industry access exists but does not overlap segment")
            if network:
                feasibility += 0.1
                notes.append("network may ease distribution")
            cap = (profile.capital or "").lower()
            if cap in ("bootstrap", "limited", "low"):
                feasibility -= 0.1
                notes.append("limited capital constrains capital-heavy motions")
            risk = (profile.risk_preference or "").lower()
            if risk == "conservative":
                feasibility -= 0.05
                notes.append("conservative risk preference penalizes high-uncertainty bets")
        feasibility = max(0.0, min(1.0, feasibility))
        verdict = ("founder_suitable" if feasibility >= 0.6 else
                   "feasible_with_gaps" if feasibility >= 0.4 else
                   "poor_founder_fit")
        return {"market_attractiveness": round(attractiveness, 3),
                "founder_feasibility": round(feasibility, 3),
                "verdict": verdict, "notes": notes,
                "warning": ("attractiveness and feasibility are separate axes — "
                            "a large market can still be wrong FOR THIS FOUNDER")}
