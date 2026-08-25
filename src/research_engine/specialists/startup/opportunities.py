"""Opportunity engine: evidence patterns -> opportunity candidates -> scored,
gated, counterevidence-checked opportunities.

Rules enforced:
- Opportunities emerge ONLY from evidence patterns (spec #32); an
  opportunity without evidence is labeled SPECULATIVE (spec #65).
- Rubric keeps individual dimension scores AND reasons visible; qualitative
  labels instead of fake precision (spec #34/#35).
- Quality gate downgrades opportunities missing required coverage (spec #98).
- Every promising opportunity gets a strongest-for / strongest-against pair
  (spec #48), a why-not-built analysis (spec #46), and evidence-gated moat
  hypotheses (spec #44).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from research_engine.models.enums import EvidenceStatus
from research_engine.models.opportunity import Opportunity
from research_engine.specialists.startup.policies import (
    QUALITY_GATE_REQUIREMENTS, RUBRIC_DIMENSIONS, opportunity_type, qualitative)
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories


class OpportunityEngine:
    def __init__(self, repos: Repositories, rrepos: ReasoningRepos,
                 provider=None, srepos=None):
        self.repos = repos
        self.rrepos = rrepos
        self.provider = provider
        self.srepos = srepos

    # ------------------------------------------------------------- patterns
    def detect_patterns(self, project_id: str, market_ctx: dict) -> list[dict]:
        """Evidence -> Pattern -> Unmet Need -> Opportunity Candidate (spec #32).

        Recognized patterns:
          P1 repeated pain + expensive workaround
          P2 new enabling technology + underserved workflow
          P3 regulatory change + fragmented manual process
          P4 funding/attention signal + unserved segment
        """
        pains = market_ctx.get("pains", [])
        shifts = market_ctx.get("tech_shifts", [])
        signals = market_ctx.get("signals", [])
        segments = market_ctx.get("segments", [])
        alternatives = {a.name.lower(): a for a in market_ctx.get("alternatives", [])}
        patterns = []

        expensive_workaround = [p for p in pains if p["evidence_class"] in
                                ("existing_spending", "actual_payment",
                                 "switching_behavior")]
        repeated = [p for p in pains if p["frequency_signal"]]
        used_spends = set()
        for p in repeated:
            # strongest link: same pain category; weaker link: any spending
            # signal (category linkage unverified — flagged in strength)
            match, weak_link = next(
                ((w, False) for w in expensive_workaround
                 if id(w) not in used_spends and
                 set(p["categories"]) & set(w["categories"])),
                next(((w, True) for w in expensive_workaround
                      if id(w) not in used_spends), (None, False)))
            if match:
                used_spends.add(id(match))
                strength = min(1.0, p["hierarchy_weight"] * 0.6 +
                               match["hierarchy_weight"] * 0.4)
                if weak_link:
                    strength *= 0.5   # unverified that the spending is for THIS pain
                patterns.append({
                    "pattern": "P1_repeated_pain_expensive_workaround",
                    "pain": p["statement"][:220],
                    "support": [p["evidence_id"], match["evidence_id"]],
                    "unmet_need": (f"customers repeatedly hit '{', '.join(p['categories'])}' "
                                   f"and already spend on workarounds"),
                    "strength": strength,
                    "link": ("category-matched" if not weak_link
                             else "spending present; category link UNVERIFIED"),
                })

        for t in shifts:
            related_pain = next((p for p in pains
                                 if _token_overlap(t.description, p["statement"]) >= 2), None)
            if related_pain:
                patterns.append({
                    "pattern": "P2_new_tech_underserved_workflow",
                    "pain": related_pain["statement"][:220],
                    "support": [related_pain["evidence_id"]] + t.evidence_ids[:2],
                    "unmet_need": (f"recent change ({t.kind}) now makes it practical to "
                                   f"remove a workflow pain that persists today"),
                    "strength": min(1.0, 0.5 + related_pain["hierarchy_weight"] * 0.4),
                })

        reg_signals = [s for s in signals if s.get("kind") == "regulation"
                       or s.get("kind") == "regulatory_change"]
        manual_pains = [p for p in pains if "manual_labor" in p["categories"]
                        or "compliance" in p["categories"]]
        for s in reg_signals:
            for p in manual_pains[:2]:
                patterns.append({
                    "pattern": "P3_regulatory_change_manual_process",
                    "pain": p["statement"][:220],
                    "support": [p["evidence_id"]] + s.get("evidence_ids", [])[:2],
                    "unmet_need": ("new regulation forces action on a currently "
                                   "manual, fragmented process"),
                    "strength": min(1.0, 0.55 + p["hierarchy_weight"] * 0.35),
                })

        strong_funding = [s for s in signals if s.get("kind") == "funding"
                          and s.get("strength") in ("STRONG", "MEDIUM")]
        unserved = [seg for seg in segments
                    if not any(seg["name"] in (a.used_by_segments or [])
                               for a in alternatives.values())]
        if strong_funding and unserved and len(pains) >= 2:
            patterns.append({
                "pattern": "P4_attention_signal_unserved_segment",
                "pain": pains[0]["statement"][:220],
                "support": (strong_funding[0].get("evidence_ids", [])[:2]
                            + unserved[0]["evidence_ids"][:2]),
                "unmet_need": (f"capital/attention flowing into the space while segment "
                               f"'{unserved[0]['name']}' remains visibly unserved"),
                "strength": 0.45,
            })
        patterns.sort(key=lambda x: -x["strength"])
        return patterns

    # ------------------------------------------------------------- candidates
    def materialize(self, project_id: str, pattern: dict,
                    market_ctx: dict, existing_problems: set[str]) -> Opportunity | None:
        alts = market_ctx.get("alternatives") or []
        alt_name = alts[0].name if isinstance(alts, list) and alts else \
            (next(iter(alts)).name if isinstance(alts, dict) and alts else "unknown")
        all_pains = market_ctx.get("pains", []) or [{}]
        opp = Opportunity(
            project_id=project_id,
            problem=pattern["pain"],
            customer_segment=((market_ctx.get("segments") or [{}])[0].get("name",
                                                                          "unclassified")),
            job_to_be_done=pattern["unmet_need"][:200],
            current_alternative=alt_name,
            evidence_ids=pattern["support"][:12],
            severity=min(1.0, pattern["strength"]),
            frequency=(sum(1 for p in all_pains if p.get("frequency_signal")) /
                       float(len(all_pains))),
            notes=f"derived via pattern {pattern['pattern']}",
        )
        opp.opportunity_type = opportunity_type(opp.problem + " " + opp.job_to_be_done)
        if opp.problem in existing_problems:
            return None
        return opp

    # ------------------------------------------------------------- rubric
    def score_rubric(self, project_id: str, opp: Opportunity,
                     market_ctx: dict) -> dict:
        """Transparent rubric: every dimension gets score + reason + label."""
        dims = {}
        pains = market_ctx.get("pains", [])

        sev = [p["severity_hint"] for p in pains
               if p["evidence_id"] in set(opp.evidence_ids)] or [opp.severity]
        dims["pain_severity"] = (sum(sev) / len(sev),
                                 f"{len(sev)} linked pain evidences")

        freq_ev = [p for p in pains if p["evidence_id"] in set(opp.evidence_ids)]
        freq_score = (sum(1 for p in freq_ev if p["frequency_signal"]) /
                      len(freq_ev)) if freq_ev else opp.frequency
        dims["pain_frequency"] = (freq_score,
                                  f"{sum(1 for p in freq_ev if p['frequency_signal'])}"
                                  f"/{len(freq_ev)} linked pains show recurring language")

        spend = [p for p in freq_ev if p["evidence_class"] in
                 ("existing_spending", "actual_payment", "switching_behavior")]
        dims["economic_value"] = (
            min(1.0, len(spend) / 2),
            f"{len(spend)} spending/switching signals" if spend else
            "no spending evidence yet")

        prices = market_ctx.get("pricing_plans", [])
        linked = [pl for pl in prices if pl.evidence_id in set(opp.evidence_ids)]
        if linked:
            wtp = min(1.0, len(linked) * 0.5)
            wtp_note = f"{len(linked)} pricing observations linked to this opportunity"
        elif prices:
            # pricing exists in the market but NOT tied to this pain — weak
            # signal only; must never read as demand for THIS opportunity
            wtp = min(0.3, len(prices) * 0.1)
            wtp_note = (f"{len(prices)} market prices observed but none linked "
                        "to this opportunity's evidence")
        else:
            wtp = 0.0
            wtp_note = "no pricing observations collected"
        dims["wtp_evidence"] = (min(1.0, float(wtp)), wtp_note)

        sizes = market_ctx.get("size_report", {})
        conflict = bool(sizes.get("conflicts"))
        dims["market_size"] = (
            0.3 if not sizes.get("comparable_groups") else
            (0.5 if conflict else 0.7),
            "market size conflicted — needs definition work" if conflict else
            "no attributed size figures yet" if not sizes.get("comparable_groups")
            else "attributed size figures present without unresolved conflicts")

        comps = market_ctx.get("competitor_profiles", [])
        direct = [c for c in comps if c.classification == "direct"]
        weak_competition = 1.0 - min(1.0, (len(direct) * 0.5 + len(comps) * 0.15))
        dims["competition_weakness"] = (
            max(0.0, weak_competition),
            f"{len(direct)} direct / {len(comps)} total researched competitors "
            "(high score == room in the market)")

        dist = market_ctx.get("distribution_difficulty", {})
        dverdict = dist.get("verdict", "unknown")
        dims["distribution"] = (
            {"plausible_channels_observed": 0.7, "distribution_uncertain": 0.4,
             "distribution_difficult": 0.15}.get(dverdict, 0.3),
            f"distribution verdict: {dverdict}")

        tech = market_ctx.get("tech_shifts", [])
        dims["technical_feasibility"] = (
            0.7 if tech else 0.4,
            "enabling technology shift observed" if tech else
            "no feasibility evidence either way — unknown")

        whynow = market_ctx.get("whynow", {})
        dims["timing"] = (
            0.75 if whynow.get("verdict") == "supported" else 0.25,
            f"why-now verdict: {whynow.get('verdict', 'not assessed')}")

        retention_ev = [e for e in market_ctx.get("retention_signals", [])]
        dims["retention_potential"] = (
            min(1.0, 0.3 + 0.2 * len(retention_ev)),
            f"{len(retention_ev)} retention-relevant signals" if retention_ev
            else "no retention evidence yet")

        moats = market_ctx.get("moat_candidates", [])
        dims["defensibility_potential"] = (
            min(1.0, 0.2 + 0.25 * len([m for m in moats if m.get("evidence_ids")])),
            f"{len(moats)} moat hypotheses ({len([m for m in moats if m.get('evidence_ids')])} "
            "evidence-linked)")

        tiers = []
        for eid in opp.evidence_ids:
            ev = self.repos.evidence.get(eid)
            if ev:
                tiers.append({1: 1.0, 2: 0.8, 3: 0.55, 4: 0.35, 5: 0.2}.get(ev.source_tier, 0.2))
        dims["evidence_strength"] = (
            sum(tiers) / len(tiers) if tiers else 0.0,
            f"avg tier weight across {len(tiers)} evidences")

        breakdown = {"factors": {}, "reasons": {}, "labels": {},
                     "weights": dict(RUBRIC_DIMENSIONS),
                     "schema_version": 2}
        total = 0.0
        for name, weight in RUBRIC_DIMENSIONS.items():
            score, reason = dims.get(name, (0.0, "not assessed"))
            score = round(max(0.0, min(1.0, score)), 3)
            breakdown["factors"][name] = score
            breakdown["reasons"][name] = reason
            breakdown["labels"][name] = qualitative(score)
            total += weight * score
        breakdown["total"] = round(total, 3)
        breakdown["note"] = ("transparent composite; individual dimensions and "
                             "reasons are authoritative, the total is only a ranking aid")
        return breakdown

    # ------------------------------------------------------------- gate
    def quality_gate(self, project_id: str, opp: Opportunity,
                     market_ctx: dict, factors: dict | None = None) -> dict:
        """Spec #98 checklist + demand sanity. Missing items downgrade the
        opportunity; zero evidence => SPECULATIVE label (spec #65).
        High priority additionally requires non-weak demand signals:
        hype (funding/attention) without pain/WTP evidence stays low (#81)."""
        checks = {
            "market_defined": bool(market_ctx.get("market")) and
            not (getattr(market_ctx.get("market"), "definition_gaps", None)),
            "customer_identified": bool(market_ctx.get("segments")),
            "pain_evidence": any(p["evidence_id"] in set(opp.evidence_ids)
                                 for p in market_ctx.get("pains", [])),
            "alternative_identified": bool(market_ctx.get("alternatives")) or
            opp.current_alternative not in ("", "unknown"),
            "competition_researched": bool(market_ctx.get("competitor_profiles")),
            "pricing_researched": bool(market_ctx.get("pricing_plans")),
            "whynow_investigated": bool(market_ctx.get("whynow")),
            "counterevidence_searched": bool(market_ctx.get("counterevidence_searched")),
            "critical_assumptions_identified": bool(market_ctx.get("assumptions_built")),
            "validation_path_exists": bool(market_ctx.get("validation_designed")),
        }
        missing = [k for k in QUALITY_GATE_REQUIREMENTS if not checks.get(k)]
        speculative = not opp.evidence_ids
        demand_ok = True
        if factors:
            # skeptical-by-default: weak pain AND weak willingness-to-pay
            # evidence caps priority regardless of coverage checks (#81)
            demand_ok = (factors.get("pain_severity", 0) >= 0.4 or
                         factors.get("wtp_evidence", 0) >= 0.4 or
                         factors.get("economic_value", 0) >= 0.4)
        priority = ("high" if len(missing) <= 2 and not speculative and demand_ok
                    else "medium" if len(missing) <= 4 or demand_ok
                    else "low")
        if speculative:
            opp.notes = ((opp.notes + "; ") if opp.notes else "") + "SPECULATIVE: no supporting evidence"
        return {"checks": checks, "missing": missing,
                "priority": priority, "speculative": speculative}

    # ------------------------------------------------------------- counter-evidence
    def counter_evidence_pair(self, project_id: str, opp: Opportunity) -> dict:
        """Strongest argument FOR vs AGAINST, each evidence-backed when possible."""
        evs = []
        for eid in opp.evidence_ids:
            ev = self.repos.evidence.get(eid)
            if ev:
                evs.append(ev)
        contra = []
        for ev in self.accepted_all(project_id):
            low = (ev.claim_text or "").lower()
            if re.search(r"\b(shut ?down|discontinu\w+|failed|pivoted|churn\w*|"
                         r"abandon\w+|struggl\w+ to (?:gain|retain)|poor adoption)\b", low):
                contra.append({"evidence_id": ev.id, "text": ev.claim_text[:200]})
        strongest_for = (max(evs, key=lambda e: e.source_tier * -1).claim_text[:220]
                         if evs else "no supporting evidence collected yet")
        strongest_against = contra[0]["text"] if contra else \
            "no direct negative evidence found — absence of failure data is NOT safety"
        return {"strongest_argument_for": strongest_for,
                "strongest_argument_against": strongest_against,
                "negative_evidence": contra[:4]}

    # ------------------------------------------------------------- why not built
    def why_not_built(self, project_id: str, opp: Opportunity,
                      market_ctx: dict) -> dict:
        """Mandatory question for serious opportunities (spec #46).
        Candidate explanations ranked by supporting evidence found."""
        explanations = [
            ("market_too_small", r"\b(niche|small market|limited (?:tam|demand))\b"),
            ("technology_impossible_or_hard", r"\b(hard to build|technic\w+ (?:challenge|limitation)|accuracy (?:is|remains) (?:low|insufficient))\b"),
            ("distribution_difficult", r"\b(long sales cycle|procurement|hard to reach|high cac)\b"),
            ("customers_unwilling_to_pay", r"\b(unwilling to pay|price sensitivity|free alternative)\b"),
            ("regulatory_constraints", r"\b(regulat\w+ barrier|compliance burden)\b"),
            ("incumbent_advantage", r"\b(incumbent\w*|locked in|switching cost\w*)\b"),
            ("workflow_complexity", r"\b(complex integration|deep workflow|fragmented systems)\b"),
            ("low_frequency_problem", r"\b(once a year|rare\w*|infrequent)\b"),
        ]
        findings = []
        corpus = [(ev.id, (ev.claim_text or "").lower())
                  for ev in self.accepted_all(project_id)]
        for name, rx in explanations:
            hits = [eid for eid, text in corpus if re.search(rx, text)]
            findings.append({"explanation": name, "supporting_evidence": hits[:3],
                             "plausible": bool(hits)})
        comps = market_ctx.get("competitor_profiles", [])
        no_competitors = not comps
        return {
            "explanations": findings,
            "no_visible_competitors_note": (
                "absence of competitors may mean the problem is unattractive — "
                "treated as a warning, not validation" if no_competitors else ""),
            "most_likely": next((f["explanation"] for f in findings
                                 if f["plausible"]), "unknown — needs founder interviews"),
        }

    # ------------------------------------------------------------- moats
    def moat_analysis(self, project_id: str, opp: Opportunity) -> list[dict]:
        """Potential defensibility mechanisms, each requiring evidence (spec #44).
        NEVER auto-claims 'AI/data = moat'."""
        candidates = [
            ("network_effects", r"\b(network effect\w*|two-sided|more users? (?:improve|attract))\b"),
            ("data_advantage", r"\b(proprietary data|unique dataset|data flywheel)\b"),
            ("workflow_lock_in", r"\b(embedded in (?:the )?workflow|migrat\w+ (?:cost|away)|switching cost\w*)\b"),
            ("distribution_advantage", r"\b(exclusive partner\w*|channel lock|installed base)\b"),
            ("regulatory_advantage", r"\b(licens\w+|approval\w*|certified)\b"),
            ("technical_difficulty", r"\b(hard to replicat\w+|deep tech|patent\w*)\b"),
        ]
        out = []
        corpus = [(ev.id, (ev.claim_text or "")) for ev in self.accepted_all(project_id)]
        for name, rx in candidates:
            hits = [eid for eid, text in corpus if re.search(rx, text, re.I)]
            out.append({
                "moat_type": name,
                "evidence_ids": hits[:3],
                "status": "evidence_supported" if hits else
                          "unsupported_hypothesis — do not claim as advantage",
            })
        return out

    # ------------------------------------------------------------- comparison
    def compare_opportunities(self, project_id: str, opp_a: Opportunity,
                              opp_b: Opportunity, *rest: Opportunity) -> dict:
        """Side-by-side comparison matrix (spec #49)."""
        all_opp = [opp_a, opp_b, *rest]
        rows = {}
        for o in all_opp:
            sb = o.score_breakdown or {}
            factors = sb.get("factors", {})
            rows[o.id] = {
                "name": (o.problem[:60] or o.id),
                "pain_severity": factors.get("pain_severity", 0.0),
                "market_size": factors.get("market_size", 0.0),
                "competition_weakness": factors.get("competition_weakness", 0.0),
                "distribution": factors.get("distribution", 0.0),
                "timing": factors.get("timing", 0.0),
                "evidence_strength": factors.get("evidence_strength", 0.0),
                "total": sb.get("total", 0.0),
                "priority_label": (sb.get("gate", {}).get("priority", "")
                                   if isinstance(sb.get("gate"), dict) else ""),
            }
        best_total = max((r["total"] for r in rows.values()), default=0.0)
        return {"matrix": rows,
                "tradeoffs_note": ("higher total is NOT automatically better — compare "
                                   "dimension-by-dimension against founder constraints"),
                "leader_by_rubric": next((oid for oid, r in rows.items()
                                          if r["total"] == best_total), "")}

    # ------------------------------------------------------------- evolution
    def version_opportunity(self, opp: Opportunity, changes: dict,
                            reason: str, new_evidence_ids=None) -> OpportunityVersion:
        from research_engine.specialists.startup.models import OpportunityVersion
        v = OpportunityVersion(
            project_id=opp.project_id, opportunity_id=opp.id,
            version=(len(self._versions_of(opp.project_id, opp.id)) + 1),
            snapshot=changes, change_reason=reason,
            new_evidence_ids=list(new_evidence_ids or []),
            confidence_before=opp.confidence)
        v.ensure_id()
        if self.srepos is not None:
            self.srepos.opportunity_versions.save(v)
        return v

    def record_decision(self, opp: Opportunity, decision: str, reason: str,
                        evidence_ids=None, readiness: str = "",
                        assumptions_snapshot=None) -> OpportunityDecision:
        from research_engine.specialists.startup.models import OpportunityDecision
        # append-only history with content-level collapse: an identical
        # (opportunity, decision, reason) recorded today adds nothing
        today = datetime.now(timezone.utc).isoformat()[:10]
        for prior in self._decisions_of(opp.project_id, opp.id):
            if (prior.decision == decision
                    and (prior.reason or "")[:180] == (reason or "")[:180]
                    and prior.created_at.isoformat()[:10] == today):
                return prior
        d = OpportunityDecision(
            project_id=opp.project_id, opportunity_id=opp.id,
            decision=decision, reason=reason,
            evidence_ids=list(evidence_ids or []),
            readiness=readiness,
            assumptions_snapshot=[a[:120] for a in (assumptions_snapshot or [])])
        d.ensure_id()
        if self.srepos is not None:
            self.srepos.opportunity_decisions.save(d)
        return d

    # ------------------------------------------------------------- helpers
    def accepted_all(self, project_id: str) -> list:
        return [e for e in self.repos.evidence.all(project_id)
                if getattr(e, "status", None) != EvidenceStatus.REJECTED]

    def _versions_of(self, project_id: str, opp_id: str) -> list:
        if self.srepos is None:
            return []
        return self.srepos.opportunity_versions.history(project_id, opp_id)

    def _decisions_of(self, project_id: str, opp_id: str) -> list:
        if self.srepos is None:
            return []
        return self.srepos.opportunity_decisions.for_opportunity(project_id, opp_id)


def _token_overlap(a: str, b: str) -> int:
    stop = {"that", "with", "this", "they", "have", "from"}
    ta = set(re.findall(r"[a-z]{4,}", (a or "").lower()))
    tb = set(re.findall(r"[a-z]{4,}", (b or "").lower()))
    return len((ta & tb) - stop)
