"""Scientific methodology designer + critic.

Generates MULTIPLE candidate methodologies per hypothesis across effort tiers
(cheap_fast / balanced / high_rigor), with explicit variables, baselines,
hypothesis-tied metrics, ablations, success/failure/inconclusive criteria,
and a comparison table that flags what each design can and cannot distinguish.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from research_engine.models.reasoning import Experiment, Hypothesis, Methodology
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class _MethOut(BaseModel):
    experiment_kind: str = "experiment"
    objective: str = ""
    independent_vars: list[str] = []
    dependent_vars: list[str] = []
    control_vars: list[str] = []
    dataset: str = ""
    method_summary: str = ""
    metrics: list[str] = []
    procedure: list[str] = []


TIERS = ["cheap_fast", "balanced", "high_rigor"]

_TIER_PROFILES = {
    "cheap_fast": {"n_baselines": 2, "ablations": 1, "runs": "single run + report variance if repeated"},
    "balanced": {"n_baselines": 3, "ablations": 2, "runs": "3 seeds, mean±std"},
    "high_rigor": {"n_baselines": 4, "ablations": 3, "runs": "5 seeds, significance tests, CIs"},
}

_NAIVE_BASELINE = {"name": "naive/heuristic baseline", "tier": "naive",
                   "why": "sanity floor every result must beat"}
_EXISTING_BASELINE = {"name": "best existing method from literature",
                      "tier": "existing",
                      "why": "the comparison reviewers and readers will ask for"}


class MethodologyDesigner:
    def __init__(self, repos: Repositories, rrepos: ReasoningRepos,
                 provider: LLMProvider | None):
        self.repos = repos
        self.rrepos = rrepos
        self.provider = provider

    def design(self, project_id: str, h: Hypothesis,
               constraints: dict | None = None) -> list[Methodology]:
        """Generate one methodology per tier; never just one (spec #22)."""
        constraints = constraints or {}
        out = []
        ctx = self._hypothesis_context(project_id, h)
        llm_by_tier = self._llm_design(h, ctx)
        for tier in TIERS:
            profile = _TIER_PROFILES[tier]
            base = llm_by_tier.get(tier) or {}
            m = Methodology(
                project_id=project_id, hypothesis_id=h.id, tier=tier,
                experiment_kind=(base.get("experiment_kind")
                                 if base.get("experiment_kind") in (
                                     "experiment", "ablation", "benchmark",
                                     "observational", "user_study", "simulation")
                                 else ("benchmark" if h.type == "COMPARATIVE" else "experiment")),
                objective=base.get("objective") or
                          f"Test: {h.statement[:160]}",
                independent_vars=base.get("independent_vars") or
                                 [f"presence/absence of the mechanism proposed by {h.id}"],
                dependent_vars=base.get("dependent_vars") or
                                ["primary outcome measure defined by the hypothesis predictions"],
                control_vars=base.get("control_vars") or
                             ["evaluation dataset/version", "random seeds", "compute budget"],
                confounders=self._candidate_confounders(h),
                dataset=base.get("dataset") or constraints.get("dataset", ""),
                method_summary=base.get("method_summary") or
                               f"{'Small-scale' if tier == 'cheap_fast' else 'Standard' if tier == 'balanced' else 'Rigorous'} "
                               "controlled evaluation of the hypothesized mechanism.",
                baselines=self._baselines(profile["n_baselines"]),
                metrics=[{"name": m_, "why": "tied to a stated prediction of the hypothesis"}
                         for m_ in (base.get("metrics") or
                                    [p[:60] for p in h.predictions] or ["primary outcome metric"])][:4],
                ablation_plan=self._ablation_plan(h, profile["ablations"]),
                procedure=base.get("procedure") or [
                    "prepare data and baseline implementations",
                    "run baseline under identical settings",
                    f"apply intervention ({h.type.lower()} manipulation)",
                    f"repeat: {profile['runs']}",
                    "compare against predefined success/failure conditions",
                ],
                success_condition="", failure_condition="", inconclusive_condition="",
            )
            m.success_condition, m.failure_condition, m.inconclusive_condition = \
                self._criteria(m, h)
            m.statistical_notes = self._statistical_notes(tier)
            m.reproducibility = {
                "seeds": "fixed list recorded before runs" if tier != "cheap_fast" else "single seed noted",
                "environment": "record deps + hardware at run time",
                "dataset_version": m.dataset or "record exact version/hash",
            }
            m.expected_result = (f"If {h.id} is supported: {h.predictions[0][:100]}"
                                 if h.predictions else "Per hypothesis prediction")
            m.ensure_id()
            self.rrepos.methodologies.save(m)
            out.append(m)
        return out

    # -- internals -------------------------------------------------------------
    def _baselines(self, n: int) -> list[dict]:
        bases = [dict(_NAIVE_BASELINE), dict(_EXISTING_BASELINE),
                 {"name": "strong contemporary baseline (SOTA variant)",
                  "tier": "strong", "why": "guards against weak-baseline wins"},
                 {"name": "ablated variant of proposed method", "tier": "internal",
                  "why": "isolates the claimed mechanism"}]
        return bases[:max(2, n)]

    def _ablation_plan(self, h: Hypothesis, n: int) -> list[str]:
        plan = []
        if any(k in h.type for k in ("MECHANISTIC", "CAUSAL")):
            plan.append("component ablation: remove the hypothesized mechanism, keep all else fixed")
        plan += [
            "data ablation: reduce/shuffle training/eval slice to test data dependence",
            "prompt/retrieval ablation: vary the LLM-facing component while holding model fixed",
            "model ablation: swap model size to test capability dependence",
        ]
        return plan[:max(1, n)]

    @staticmethod
    def _candidate_confounders(h: Hypothesis) -> list[str]:
        c = ["dataset contamination / leakage between splits",
             "selection bias in collected evidence"]
        if h.domain == "startup":
            c = ["self-selection of vocal customers", "seasonality of demand signals",
                 "survivorship bias in visible reviews"]
        return c

    @staticmethod
    def _criteria(m: Methodology, h: Hypothesis) -> tuple[str, str, str]:
        primary = (m.metrics[0]["name"] if m.metrics else "primary metric").strip()
        return (
            f"Success: {primary} improves over the strongest baseline by a margin "
            "predefined BEFORE running, consistent across repeats.",
            "Failure: no meaningful improvement over baselines under identical settings.",
            "Inconclusive: results unstable across seeds/runs (variance swamps effect).")

    @staticmethod
    def _statistical_notes(tier: str) -> str:
        if tier == "cheap_fast":
            return ("Single-run results are indicative only; no significance claims. "
                    "State variance requirements for follow-up.")
        if tier == "balanced":
            return ("Multiple seeds: report mean±std; paired test where applicable; "
                    "state effect size. Do not claim significance without n>=3.")
        return ("Pre-register metric+threshold; report CIs, effect size, multiple-"
                "comparison correction; check data leakage explicitly.")

    def _hypothesis_context(self, project_id: str, h: Hypothesis) -> str:
        claims = sorted(self.repos.claims.all(project_id), key=lambda c: -c.confidence)[:6]
        return "\n".join(f"- {c.text[:130]}" for c in claims) or "(no claims)"

    def _llm_design(self, h: Hypothesis, context: str) -> dict[str, dict]:
        if self.provider is None:
            return {}
        spec = get_prompt("query_generator")  # generic JSON-discipline system prompt
        user = (f"Hypothesis [{h.type}]: {h.statement}\n"
                f"Predictions: {h.predictions}\nFalsifiers: {h.falsification_conditions}\n"
                f"Related claims:\n{context}\n\n"
                'Design THREE methodologies (tiers cheap_fast, balanced, high_rigor). '
                'For each: concrete dataset, variables, metrics tied to predictions, '
                'procedure steps. Respond ONLY with JSON: '
                '{"cheap_fast": {...}, "balanced": {...}, "high_rigor": {...}} where each '
                'value matches {"experiment_kind","objective","independent_vars",'
                '"dependent_vars","control_vars","dataset","method_summary","metrics",'
                '"procedure"}')
        class MultiOut(BaseModel):
            cheap_fast: dict = {}
            balanced: dict = {}
            high_rigor: dict = {}
        try:
            out, errors = self.provider.structured(spec.system, user, MultiOut, max_attempts=2)
        except Exception:
            return {}
        if out is None:
            return {}
        clean = {}
        for tier in TIERS:
            d = getattr(out, tier) or {}
            if isinstance(d, dict) and d.get("method_summary"):
                d.setdefault("metrics", [])
                clean[tier] = d
        return clean

    # -- comparison ------------------------------------------------------------
    def compare(self, project_id: str, hypothesis_id: str) -> list[dict]:
        meths = self.rrepos.methodologies.for_hypothesis(project_id, hypothesis_id)
        rows = []
        for m in meths:
            rows.append({
                "methodology_id": m.id, "tier": m.tier, "kind": m.experiment_kind,
                "scientific_validity": {"cheap_fast": 0.5, "balanced": 0.75,
                                        "high_rigor": 0.95}.get(m.tier, 0.7),
                "cost_time": {"cheap_fast": "hours-days", "balanced": "days",
                              "high_rigor": "days-weeks"}[m.tier],
                "distinguishing_power":
                    ("can discriminate rivals" if len(m.ablation_plan) >= 2 and
                     len(m.baselines) >= 3 else "limited discrimination"),
                "confound_risk": ", ".join(m.confounders[:2]) or "not analyzed",
                "reproducibility": "documented" if m.reproducibility else "MISSING",
                "success_criterion_defined": bool(m.success_condition),
            })
        rows.sort(key=lambda r: ["cheap_fast", "balanced", "high_rigor"].index(r["tier"]))
        return rows


# ---------------------------------------------------------------------------
# Methodology critic (spec #64)
# ---------------------------------------------------------------------------

class MethodologyCritic:
    def inspect(self, project_id: str, m: Methodology, h: Hypothesis | None = None) -> dict:
        problems: list[dict] = []

        def add(kind: str, severity: str, description: str):
            problems.append({"type": kind, "severity": severity, "description": description})

        if not m.success_condition or not m.failure_condition:
            add("POST_HOC_RISK", "high",
                "Success/failure criteria undefined; criteria must be fixed before running.")
        tiers = {b.get("tier") for b in m.baselines}
        if "naive" not in tiers:
            add("WEAK_BASELINE_COVERAGE", "medium", "No naive baseline included.")
        if not m.dependent_vars or not m.independent_vars:
            add("VARIABLES_UNDEFINED", "high", "Independent/dependent variables not specified.")
        if not m.ablation_plan and m.experiment_kind in ("experiment", "ablation"):
            add("NO_ABLATION_PLAN", "medium",
                "Complex-system claims without an ablation plan cannot localize causes.")
        if "leakage" not in " ".join(m.confounders).lower():
            add("CONFOUNDER_UNANALYZED", "medium",
                "Data leakage not listed among considered confounders.")
        if not m.reproducibility:
            add("REPRODUCIBILITY_MISSING", "medium",
                "No reproducibility block (seeds/env/dataset version).")
        if h is not None and m.metrics and h.predictions:
            linked = any(any(p[:25].lower() in str(mt).lower() for p in h.predictions)
                         for mt in m.metrics)
            if not linked:
                add("METRIC_MISMATCH", "medium",
                    "Metrics may not map onto the hypothesis's stated predictions.")
        uncertain = not problems or all(p["severity"] == "medium" for p in problems)
        return {"methodology_id": m.id, "problems": problems,
                "verdict": "acceptable_with_notes" if uncertain and problems else
                           ("sound" if not problems else "needs_revision")}
