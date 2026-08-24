"""Hypothesis engine: generation, competing alternatives, critique, refinement,
ranking, versioning, and the lifecycle state machine.

Grounding rules enforced here (spec #99/#100):
- every hypothesis carries origin provenance (evidence|contradiction|gap|assumption|user)
- falsification conditions are required; without them quality is degraded
- generation always produces COMPETING alternatives including a null/baseline
  explanation before any "most likely" selection happens (spec #8/#9)
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from research_engine.models.enums import EVIDENCE_STANCES, HypothesisState
from research_engine.models.reasoning import (Assumption, Hypothesis,
                                              HypothesisVersion)
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

ALLOWED_HYPO_TRANSITIONS: dict[str, set[str]] = {
    "PROPOSED": {"UNDER_REVIEW", "NEEDS_EVIDENCE", "ABANDONED"},
    "UNDER_REVIEW": {"REFINED", "NEEDS_EVIDENCE", "READY_FOR_TEST", "ABANDONED",
                     "SUPERSEDED"},
    "NEEDS_EVIDENCE": {"UNDER_REVIEW", "REFINED", "ABANDONED", "SUPERSEDED"},
    "REFINED": {"READY_FOR_TEST", "UNDER_REVIEW", "NEEDS_EVIDENCE", "ABANDONED",
                "SUPERSEDED"},
    "READY_FOR_TEST": {"TESTING", "UNDER_REVIEW", "ABANDONED"},
    "TESTING": {"SUPPORTED", "WEAKLY_SUPPORTED", "CONTRADICTED", "FALSIFIED",
                "INCONCLUSIVE_REVIEW"},  # inconclusive loops back via review
    "INCONCLUSIVE_REVIEW": {"TESTING", "REFINED", "ABANDONED"},
    "SUPPORTED": {"SUPERSEDED"},
    "WEAKLY_SUPPORTED": {"TESTING", "REFINED", "SUPERSEDED", "ABANDONED"},
    "CONTRADICTED": {"FALSIFIED", "REFINED", "ABANDONED"},
    "FALSIFIED": {"ABANDONED"},
    "ABANDONED": set(),
    "SUPERSEDED": set(),
}


class HypothesisLifecycle:
    def __init__(self, repos: ReasoningRepos):
        self.repos = repos

    def transition(self, h: Hypothesis, target: str, reason: str = "") -> None:
        if h.status == target:
            return
        allowed = ALLOWED_HYPO_TRANSITIONS.get(h.status, set())
        if target not in allowed:
            raise ValueError(f"Illegal hypothesis transition {h.status} -> {target} "
                             f"({reason})")
        log.info("hypothesis %s: %s -> %s (%s)", h.id, h.status, target, reason)
        h.status = target
        self.repos.hypotheses.save(h)

    def revise(self, project_id: str, h: Hypothesis, changes: dict,
               reason: str, new_evidence_ids=None) -> Hypothesis:
        """Create an immutable version snapshot, then apply changes (spec #14)."""
        old_confidence = h.confidence
        snap = HypothesisVersion(
            project_id=project_id, hypothesis_id=h.id, version=h.version,
            snapshot=_strip(h), change_reason=reason[:400],
            new_evidence_ids=list(new_evidence_ids or []),
            confidence_before=old_confidence, confidence_after=changes.get("confidence", old_confidence))
        snap.ensure_id()
        self.repos.hypothesis_versions.save(snap)
        for k, v in changes.items():
            if hasattr(h, k):
                setattr(h, k, v)
        h.version += 1
        self.repos.hypotheses.save(h)
        return h


def _strip(model) -> dict:
    import json
    return json.loads(model.model_dump_json())


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

class _HypOut(BaseModel):
    title: str = ""
    statement: str = ""
    type: str = "CAUSAL"
    mechanism: str = ""
    assumptions: list[str] = Field(default_factory=list)
    predictions: list[str] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)


class _CompetingOut(BaseModel):
    hypotheses: list[_HypOut] = []


class HypothesisGenerator:
    """Generates competing hypothesis SETS anchored to evidence artifacts."""

    def __init__(self, repos: Repositories, reasoning_repos: ReasoningRepos,
                 provider: LLMProvider | None):
        self.repos = repos
        self.rrepos = reasoning_repos
        self.provider = provider

    # -- public API ----------------------------------------------------------
    def generate_for_gap(self, project_id: str, gap, iteration: int = 0) -> list[Hypothesis]:
        """Gap -> 2+ competing candidate explanations (+null)."""
        ctx_claims, ctx_ev_ids = self._gap_evidence(project_id, gap)
        ctx = self._gap_context(project_id, gap)
        llm_set = self._llm_competing(gap.description, ctx)
        if len(llm_set) >= 2:
            hyps = llm_set
        else:
            hyps = self._template_competing(gap)
        out = []
        for i, item in enumerate(hyps):
            h = Hypothesis(
                project_id=project_id, title=item["title"][:200],
                statement=item["statement"][:800],
                domain="scientific", type=item.get("type", "CAUSAL"),
                origin="gap", origin_refs=[gap.id],
                supporting_evidence=list(ctx_ev_ids)[:8],
                assumptions=[], predictions=item.get("predictions", []),
                falsification_conditions=item.get("falsification_conditions", []),
                alternative_of="", iteration=iteration,
            )
            h.ensure_id()
            # link the family so hypotheses know they compete
            h.alternative_of = out[0].id if out else f"family_{gap.id}"
            # assumptions become first-class Assumption entities (traceability)
            asm_ids = []
            for a_text in item.get("assumptions", [])[:4]:
                a = Assumption(project_id=project_id, statement=a_text[:300],
                               kind="important", hypothesis_id=h.id)
                a.ensure_id()
                self.rrepos.assumptions.save(a)
                asm_ids.append(a.id)
            h.assumptions = asm_ids
            if not h.falsification_conditions:
                h.falsification_conditions = [
                    f"If targeted research finds {gap.evidence_needed[:80] or 'contrary evidence'}, abandon this hypothesis"]
            self.rrepos.hypotheses.save(h)
            out.append(h)
        return out

    def generate_for_contradiction(self, project_id: str, con, iteration: int = 0) -> list[Hypothesis]:
        """Contradiction -> competing explanations for WHY sources disagree."""
        hyps = [
            Hypothesis(project_id=project_id,
                       title="Measurement/definition difference explains the disagreement",
                       statement=(f"The disagreement between \"{con.statement_a[:100]}\" and "
                                  f"\"{con.statement_b[:100]}\" is due to different metrics, "
                                  "populations, or definitions rather than a genuine factual conflict."),
                       domain="scientific", type="MECHANISTIC", origin="contradiction",
                       origin_refs=[con.id],
                       falsification_conditions=[
                           "If both sources used identical measurement setups and still disagree, this explanation fails"],
                       iteration=iteration),
            Hypothesis(project_id=project_id,
                       title="One source is outdated or wrong",
                       statement=("One side of the disagreement reflects superseded or "
                                  "erroneous information; newer/stronger evidence should be sought."),
                       domain="scientific", type="COMPARATIVE", origin="contradiction",
                       origin_refs=[con.id],
                       falsification_conditions=[
                           "If both sides remain equally credible after source-quality analysis, this explanation fails"],
                       iteration=iteration),
        ]
        for h in hyps:
            h.ensure_id()
            self.rrepo_save(h)
        return hyps

    def generate_business_hypotheses(self, project_id: str, opportunity) -> list[Hypothesis]:
        """Opportunity -> testable business hypothesis chain (spec #34/#35)."""
        seg = opportunity.customer_segment or "target customers"
        prob = opportunity.problem[:120]
        specs = [
            ("CUSTOMER", f"{seg} experience the problem frequently enough to prioritize it",
             ["frequency of complaints/behavior in collected evidence"],
             "If customer-level evidence shows only isolated/one-off occurrences, fail"),
            ("MARKET", f"Current alternatives ({opportunity.current_alternative}) leave "
             f"{seg} substantially underserved",
             ["gap between what alternatives do and what customers need"],
             "If alternatives already solve the core problem, fail"),
            ("WILLINGNESS_TO_PAY", f"{seg} will pay for a solution that removes this problem",
             ["pricing evidence, existing spending on workarounds"],
             "If no spending signal exists at any price point, fail"),
            ("DISTRIBUTION", f"{seg} can be reached economically through identifiable channels",
             ["channel evidence, community/industry concentration"],
             "If no economical channel exists, fail"),
        ]
        out = []
        for htype, stmt, preds, falsifier in specs:
            h = Hypothesis(project_id=project_id,
                           title=f"H[{htype}]: {stmt[:90]}",
                           statement=stmt, domain="startup", type=htype,
                           origin="evidence", origin_refs=list(opportunity.evidence_ids[:6]),
                           supporting_evidence=list(opportunity.evidence_ids[:6]),
                           predictions=preds, falsification_conditions=[falsifier],
                           iteration=0)
            h.ensure_id()
            self.rrepo_save(h)
            out.append(h)
        return out

    def rrepo_save(self, h):
        self.rrepos.hypotheses.save(h)

    # -- internals -------------------------------------------------------------
    def _gap_evidence(self, project_id: str, gap):
        claims = self.repos.claims.all(project_id)
        rel = [c for c in claims if not gap.branch or c.branch == gap.branch]
        rel.sort(key=lambda c: -c.confidence)
        ev_ids: list[str] = []
        for c in rel:
            ev_ids.extend(c.supported_by)
        return rel[:8], list(dict.fromkeys(ev_ids))[:8]

    def _gap_context(self, project_id: str, gap) -> str:
        claims, ev_ids = self._gap_evidence(project_id, gap)
        all_ev = {e.id: e for e in self.repos.evidence.all(project_id)}
        lines = [f"- {c.text[:140]} (confidence {c.confidence:.2f})" for c in claims]
        for eid in ev_ids:
            e = all_ev.get(eid)
            if e:
                lines.append(f"- [{e.id}] {e.claim_text[:130]}")
        return "\n".join(lines) or "(no related evidence yet)"

    def _llm_competing(self, gap_description: str, context: str) -> list[dict]:
        if self.provider is None:
            return []
        system = (
            "You generate COMPETING scientific hypotheses from a research gap.\n"
            "Rules:\n"
            "- Produce 2-3 DISTINCT mechanistic explanations plus one null/artifact\n"
            "  explanation (e.g. dataset bias, measurement artifact).\n"
            "- Each must state its mechanism, key assumptions, predictions that differ\n"
            "  from rivals, and concrete falsification conditions.\n"
            "- Only use information present in the context; label speculation as assumption.\n"
            '- Respond ONLY with JSON: {"hypotheses": [{"title","statement","type",'
            '"mechanism","assumptions":[...],"predictions":[...],"falsification_conditions":[...]}]}')
        user = (f"Research gap: {gap_description}\n\nRelated evidence:\n{context}")
        out, errors = self.provider.structured(system, user, _CompetingOut, max_attempts=2)
        if out is None:
            return []
        result = []
        for h in out.hypotheses[:4]:
            if not h.statement.strip():
                continue
            result.append({
                "title": h.title or h.statement[:60], "statement": h.statement,
                "type": h.type if h.type in (
                    "DESCRIPTIVE", "CORRELATIONAL", "CAUSAL", "MECHANISTIC",
                    "PREDICTIVE", "COMPARATIVE") else "CAUSAL",
                "assumptions": h.assumptions[:4], "predictions": h.predictions[:3],
                "falsification_conditions": h.falsification_conditions[:3],
            })
        return result

    @staticmethod
    def _template_competing(gap) -> list[dict]:
        d = gap.description[:160]
        need = gap.evidence_needed[:100]
        base = f"regarding: {d}"
        return [
            {"title": f"Causal explanation for gap ({d[:50]})",
             "statement": f"A causal mechanism underlies the observed gap {base}. "
                          "The phenomenon occurs because of a specific, identifiable cause.",
             "type": "CAUSAL",
             "assumptions": ["The pattern is real rather than sampling noise"],
             "predictions": ["Intervening on the cause changes the outcome"],
             "falsification_conditions": [f"If {need or 'contrary evidence'} shows no mechanism, abandon"]},
            {"title": f"Alternative explanation ({d[:50]})",
             "statement": f"An alternative factor explains the same observations {base}: "
                          "a confounder or different process produces similar surface results.",
             "type": "MECHANISTIC",
             "assumptions": ["Observations underdetermine the mechanism"],
             "predictions": ["Controlling for the confounder eliminates the effect"],
             "falsification_conditions": ["If controls do not eliminate the effect, abandon"]},
            {"title": "Null / artifact explanation",
             "statement": "The apparent pattern is an artifact of measurement, dataset "
                          "bias, or publication bias rather than a real phenomenon.",
             "type": "DESCRIPTIVE",
             "assumptions": ["Collected evidence may be unrepresentative"],
             "predictions": ["Independent data will not reproduce the pattern"],
             "fascination_fallback": None,
             "falsification_conditions": ["If independent data reproduces the pattern, this null fails"]},
        ]


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------

class CriticDefect(BaseModel):
    type: str          # UNSUPPORTED_ASSUMPTION | RESTATES_EVIDENCE | UNFALSIFIABLE |
                       # NO_DISCRIMINATING_TEST | CIRCULAR | OVERBROAD | CONFLATED_CORRELATION
    description: str
    severity: str = "medium"


class CriticOutput(BaseModel):
    problems: list[CriticDefect] = []
    required_research: list[str] = []
    revision_needed: bool = False


class HypothesisCritic:
    """Structured critique: is it supported, testable, falsifiable, distinct?"""

    def __init__(self, repos: Repositories, reasoning_repos: ReasoningRepos,
                 provider: LLMProvider | None):
        self.repos = repos
        self.rrepos = reasoning_repos
        self.provider = provider

    def critique(self, project_id: str, h: Hypothesis) -> dict:
        defects: list[dict] = []
        all_ev = {e.id: e for e in self.repos.evidence.all(project_id)}

        sup = [all_ev[e] for e in h.supporting_evidence if e in all_ev]
        con = [all_ev[e] for e in h.contradicting_evidence if e in all_ev]

        if not h.falsification_conditions:
            defects.append({"type": "UNFALSIFIABLE", "severity": "high",
                            "description": "No falsification condition specified."})
        if not any(len(c) > 20 for c in h.falsification_conditions):
            defects.append({"type": "INSUFFICIENTLY_SPECIFIED", "severity": "medium",
                            "description": "Falsification conditions too vague to act on."})
        if not sup:
            defects.append({"type": "UNSUPPORTED", "severity": "high",
                            "description": "No supporting evidence attached; purely speculative so far."})
        # restatement check: hypothesis text nearly equals one quote
        for e in sup:
            overlap = _token_overlap(h.statement, e.quote)
            if overlap > 0.85:
                defects.append({"type": "RESTATES_EVIDENCE", "severity": "medium",
                                "description": f"Largely restates evidence {e.id} instead of explaining it."})
                break
        # correlation/causation guardrail
        lowered = h.statement.lower()
        if any(k in lowered for k in ("causes", "leads to", "results in")) and \
           not any(k in lowered for k in ("mechanism", "because", "intervention")):
            defects.append({"type": "CONFLATED_CORRELATION", "severity": "medium",
                            "description": "Causal language without stated mechanism."})
        # discriminating power vs alternatives
        siblings = [x for x in self.rrepos.hypotheses.all(project_id)
                    if x.alternative_of == h.alternative_of and x.id != h.id
                    and h.alternative_of]
        if siblings and not h.discriminating_tests:
            defects.append({"type": "NO_DISCRIMINATING_TEST", "severity": "high",
                            "description": f"Competes with {len(siblings)} rival hypotheses "
                                           "but no discriminating test specified."})

        # LLM advisory critique (may add defects + research asks)
        llm_problems, llm_research = self._llm_critique(project_id, h)
        seen_types = {d["type"] for d in defects}
        for p in llm_problems:
            if p.get("type") not in seen_types:
                defects.append(p)
        revision = any(d["severity"] == "high" for d in defects) or bool(llm_research)

        result = {
            "hypothesis_id": h.id,
            "problems": defects + llm_problems[len(defects):],
            "required_research": llm_research,
            "revision_needed": revision,
            "stance_summary": self._stance_summary(sup, con),
        }
        # persist critique onto hypothesis scores block for traceability
        h.scores["critique"] = {"problems": defects, "required_research": llm_research[:5]}
        self.rrepos.hypotheses.save(h)
        return result

    def _llm_critique(self, project_id: str, h: Hypothesis) -> tuple[list[dict], list[str]]:
        if self.provider is None:
            return [], []
        system = (
            "You are a hostile but fair hypothesis reviewer.\n"
            "Ask: Is it actually supported? Does it merely restate evidence? Unsupported\n"
            "assumptions? Contradicting evidence? Rival explanations? Testable? What would\n"
            "falsify it? Would the proposed test distinguish it from alternatives?\n"
            'Respond ONLY with JSON: {"problems": [{"type","description","severity"}], '
            '"required_research": ["...", ...], "revision_needed": true|false}')
        user = (f"Hypothesis [{h.type}] {h.statement}\n"
                f"Assumptions: {h.assumptions}\n"
                f"Falsifiers: {h.falsification_conditions}\n")
        out, errors = self.provider.structured(system, user, CriticOutput, max_attempts=2)
        if out is None:
            return [], []
        return ([p.model_dump() for p in out.problems][:5],
                [r[:200] for r in out.required_research][:4])

    @staticmethod
    def _stance_summary(sup, con) -> dict:
        return {"supporting": len(sup), "contradicting": len(con)}


def _token_overlap(a: str, b: str) -> float:
    wa = set(w for w in a.lower().split() if len(w) > 3)
    wb = set(w for w in b.lower().split() if len(w) > 3)
    if not wb:
        return 0.0
    return len(wa & wb) / max(1, len(wb))


# ---------------------------------------------------------------------------
# Scoring & ranking
# ---------------------------------------------------------------------------

def score_hypothesis(repos: Repositories, rrepos: ReasoningRepos,
                     project_id: str, h: Hypothesis) -> dict:
    """Multi-dimensional transparent scoring (spec #10). No single opaque number;
    confidence is derived and shown WITH its components."""
    all_ev = {e.id: e for e in repos.evidence.all(project_id)}
    tier_w = {1: 1.0, 2: 0.8, 3: 0.55, 4: 0.35, 5: 0.2}
    sup = [all_ev[e] for e in h.supporting_evidence if e in all_ev]
    con = [all_ev[e] for e in h.contradicting_evidence if e in all_ev]

    support = min(1.0, sum(tier_w.get(e.source_tier, 0.2) * e.confidence for e in sup) / 3)
    opposition = min(1.0, sum(tier_w.get(e.source_tier, 0.2) for e in con) / 2)
    testability = 1.0 if h.predictions and h.falsification_conditions else \
        (0.5 if h.falsification_conditions else 0.15)
    falsifiability = min(1.0, len(h.falsification_conditions) * 0.4)
    n_assumptions = len(h.assumptions)
    parsimony = max(0.1, 1.0 - 0.2 * max(0, n_assumptions - 1))
    explanatory_power = min(1.0, 0.4 + 0.15 * len(h.predictions))
    feasibility = 0.7 if h.type in ("CORRELATIONAL", "DESCRIPTIVE", "MARKET",
                                    "CUSTOMER") else 0.55
    novelty = {"likely_novel": 1.0, "possibly_novel": 0.75, "uncertain": 0.5,
               "incremental": 0.35, "already_explored": 0.1}.get(h.novelty_status, 0.5)
    importance = 0.6 if h.origin in ("gap", "contradiction") else 0.5

    scores = {
        "support": round(support, 3), "opposition": round(opposition, 3),
        "testability": testability, "falsifiability": round(falsifiability, 3),
        "parsimony": round(parsimony, 3),
        "explanatory_power": round(explanatory_power, 3),
        "feasibility": feasibility, "novelty": novelty, "importance": importance,
    }
    critique_problems = (h.scores.get("critique") or {}).get("problems", [])
    high_defects = sum(1 for d in critique_problems if d.get("severity") == "high")
    scores["critic_penalty"] = high_defects

    # confidence derives from support minus opposition minus defects (spec #61/#62 qualitative)
    confidence = max(0.0, min(1.0, support - 0.5 * opposition - 0.1 * high_defects))
    if not sup:
        confidence = min(confidence, 0.25)  # speculation stays visibly weak
    h.scores.update(scores)
    h.confidence = round(confidence, 3)
    rrepos.hypotheses.save(h)
    return scores


def rank_hypotheses(repos: Repositories, rrepos: ReasoningRepos, project_id: str,
                    objective: str = "balanced") -> list[dict]:
    """Portfolio ranking under a configurable objective (spec #70/#71).

    objective: balanced | novelty | feasibility | impact
    Returns ranked list with full score breakdowns + portfolio tradeoff notes.
    """
    weights = {
        "balanced": {"support": .25, "testability": .2, "novelty": .15,
                     "importance": .2, "feasibility": .2},
        "novelty": {"novelty": .45, "support": .15, "testability": .2, "importance": .2},
        "feasibility": {"feasibility": .45, "support": .2, "testability": .2, "importance": .15},
        "impact": {"importance": .4, "explanatory_power": .25, "support": .2, "novelty": .15},
    }.get(objective, {})

    hyps = [h for h in rrepos.hypotheses.all(project_id)
            if h.status not in ("ABANDONED", "SUPERSEDED")]
    ranked = []
    for h in hyps:
        if "support" not in (h.scores or {}):
            score_hypothesis(repos, rrepos, project_id, h)
        s = h.scores or {}
        rank_score = round(sum(s.get(k, 0) * w for k, w in weights.items()), 4) if weights else 0
        ranked.append({
            "hypothesis": h, "rank_score": rank_score,
            "objective": objective,
            "tradeoffs": {
                "novelty_vs_feasibility":
                    f"novelty={s.get('novelty', 0):.2f} / feasibility={s.get('feasibility', 0):.2f}",
                "support_vs_uncertainty":
                    f"support={s.get('support', 0):.2f} / open_assumptions={len(h.assumptions)}",
            },
            "confidence": h.confidence,
        })
    ranked.sort(key=lambda r: -r["rank_score"])
    return ranked


# ---------------------------------------------------------------------------
# Refinement loop
# ---------------------------------------------------------------------------

class RefinementLoop:
    """Generate -> critique -> (research missing evidence externally) -> revise ->
    critique -> compare -> rank. Stopping conditions explicit (spec #13)."""

    MAX_ITERATIONS = 2

    def __init__(self, repos: Repositories, rrepos: ReasoningRepos,
                 provider: LLMProvider | None, lifecycle: HypothesisLifecycle,
                 critic: HypothesisCritic):
        self.repos = repos
        self.rrepos = rrepos
        self.provider = provider
        self.lifecycle = lifecycle
        self.critic = critic

    def run(self, project_id: str, h: Hypothesis) -> dict:
        history = []
        for it in range(self.MAX_ITERATIONS):
            self.lifecycle.transition(h, "UNDER_REVIEW", "critique pass")
            critique = self.critic.critique(project_id, h)
            history.append({"iteration": it + 1, "problems": len(critique["problems"]),
                            "revision_needed": critique["revision_needed"]})
            high = [p for p in critique["problems"] if p.get("severity") == "high"]
            if not high or it == self.MAX_ITERATIONS - 1:
                break
            # refinement: attach contradicting evidence found by adversarial pass
            contra = [e.id for e in self.repos.evidence.all(project_id, "status='REJECTED'", ())
                      ][:0]  # rejected stay excluded; refine instead via assumption tightening
            changes = {}
            if any(p["type"] == "UNFALSIFIABLE" for p in high):
                changes["falsification_conditions"] = list(set(
                    h.falsification_conditions + [
                        "Targeted search finding evidence that contradicts the stated mechanism"]))
            if any(p["type"] == "UNSUPPORTED" for p in high):
                changes["status_note"] = "flagged as speculative until evidence attached"
            new_status = "NEEDS_EVIDENCE" if any(
                p["type"] in ("UNSUPPORTED", "UNFALSIFIABLE") for p in high) else "REFINED"
            changes["status"] = new_status
            self.lifecycle.revise(project_id, h, changes,
                                  reason="critique refinement pass",
                                  new_evidence_ids=[])
            # re-load status transitions properly
            h.status = new_status
            self.rrepos.hypotheses.save(h)
        score_hypothesis(self.repos, self.rrepos, project_id, h)
        final = self.critic.critique(project_id, h)
        return {"iterations": history, "final_critique": final,
                "stopped_because": ("no high-severity defects" if not high else "max iterations")}
