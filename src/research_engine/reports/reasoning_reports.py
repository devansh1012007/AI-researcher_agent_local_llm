"""Phase 3 reasoning reports: hypotheses, assumptions, methodology,
experiment plan, evaluation plan, validation plan, decision analysis.

Every item cites IDs; recommendations carry their full traceability chain.
"""
from __future__ import annotations

from research_engine.reasoning.decision_layer import DecisionLayer
from research_engine.reasoning.methodology_designer import MethodologyDesigner
from research_engine.reasoning.validation_designer import ValidationCritic


class ReasoningReports:
    def __init__(self, repos, ws, rrepos):
        self.repos = repos
        self.ws = ws
        self.rrepos = rrepos

    def _write(self, name: str, content: str) -> bool:
        self.ws.report_path(name).write_text(content, encoding="utf-8")
        return True

    def write_hypotheses(self, project_id: str) -> bool:
        from research_engine.reasoning.hypothesis_engine import rank_hypotheses
        ranked = rank_hypotheses(self.repos, self.rrepos, project_id)
        lines = ["# Hypothesis Portfolio", "",
                 "_Ranked under a balanced objective; scores are multi-dimensional and "
                 "shown in full. Confidence is derived from support/opposition/critic "
                 "defects — never an opaque number._", ""]
        if not ranked:
            lines.append("_No hypotheses generated yet. Run research or use the CLI._")
            return self._write("hypotheses.md", "\n".join(lines))
        for i, r in enumerate(ranked, 1):
            h = r["hypothesis"]
            lines.append(f"## #{i} {h.id} — rank {r['rank_score']:.3f}, "
                         f"confidence {r['confidence']:.2f} [{h.status}]")
            lines.append(f"- **{h.title}**")
            lines.append(f"- type: {h.type}; origin: {h.origin} ({', '.join(h.origin_refs)})")
            lines.append(f"- statement: {h.statement}")
            if h.scores:
                lines.append(f"- scores: {_fmt_scores(h.scores)}")
            if h.supporting_evidence:
                lines.append(f"- supporting evidence: {', '.join(h.supporting_evidence[:8])}")
            if h.contradicting_evidence:
                lines.append(f"- contradicting evidence: {', '.join(h.contradicting_evidence[:6])}")
            if h.falsification_conditions:
                lines.append("- falsification:")
                lines += [f"    - {f}" for f in h.falsification_conditions[:3]]
            if h.predictions:
                lines.append(f"- predictions: {'; '.join(p[:80] for p in h.predictions[:3])}")
            lines.append("")
        return self._write("hypotheses.md", "\n".join(lines))

    def write_assumptions(self, project_id: str) -> bool:
        asm = sorted(self.rrepos.assumptions.all(project_id),
                     key=lambda a: -a.priority)
        lines = ["# Assumption Register", "",
                 "_Priority = importance x impact x uncertainty x testability-ease; "
                 "test consequential-and-cheap first._", ""]
        for a in asm[:25]:
            lines.append(f"- [{a.kind}/{a.status}] *{a.statement[:150]}* "
                         f"(priority {a.priority:.2f}, hyp={a.hypothesis_id or '-'})")
        if not asm:
            lines.append("_No tracked assumptions._")
        return self._write("assumptions.md", "\n".join(lines))

    def write_methodology(self, project_id: str) -> bool:
        designer = MethodologyDesigner(self.repos, self.rrepos, None)
        from research_engine.reasoning.methodology_designer import MethodologyCritic
        critic = MethodologyCritic()
        lines = ["# Methodology Candidates", ""]
        hyps = [h for h in self.rrepos.hypotheses.all(project_id)]
        wrote_any = False
        for h in hyps[:4]:
            meths = self.rrepos.methodologies.for_hypothesis(project_id, h.id)
            if not meths:
                continue
            wrote_any = True
            lines.append(f"## For hypothesis {h.id}: {h.title[:90]}")
            rows = designer.compare(project_id, h.id)
            lines += ["| tier | kind | validity | cost | discrimination | verdict |",
                      "|---|---|---|---|---|---|"]
            verdicts = {}
            for m in meths:
                v = critic.inspect(project_id, m, h)
                verdicts[m.id] = v["verdict"]
            for row in rows:
                lines.append(f"| {row['tier']} | {row['kind']} | "
                             f"{row['scientific_validity']} | {row['cost_time']} | "
                             f"{row['distinguishing_power']} | "
                             f"{verdicts.get(row['methodology_id'], '-')} |")
            best = meths[0]
            lines += ["", f"### Recommended ({best.tier}): {best.objective[:140]}",
                      f"- variables: indep={best.independent_vars[:2]} dep={best.dependent_vars[:2]}",
                      f"- baselines: {[b.get('name') for b in best.baselines]}",
                      f"- success: {best.success_condition[:160]}",
                      f"- failure: {best.failure_condition[:120]}",
                      f"- statistics: {best.statistical_notes[:180]}", ""]
        if not wrote_any:
            lines.append("_No methodologies designed yet._")
        return self._write("methodology.md", "\n".join(lines))

    def write_experiment_plan(self, project_id: str) -> bool:
        exps = self.rrepos.experiments.all(project_id)
        lines = ["# Experiment Plan", "",
                 "_The system designs experiments; humans approve and execute "
                 "consequential ones (READY_FOR_HUMAN_APPROVAL gates)._", ""]
        order = {"DESIGNED": 0, "READY_FOR_HUMAN_APPROVAL": 1,
                 "READY_FOR_EXECUTION": 2, "TESTING": 3,
                 "RESULT_INGESTED": 4, "EVALUATED": 5}
        for x in sorted(exps, key=lambda e: order.get(e.status, 9)):
            gate = " **[AWAITING YOUR APPROVAL]**" if x.awaiting_approval else ""
            lines.append(f"## {x.id} [{x.status}]{gate}")
            lines.append(f"- {x.title}")
            lines.append(f"- risk: {x.risk_level}; hypothesis: {x.hypothesis_id}")
            if x.awaiting_approval:
                lines.append(f"- approve via: `research approve {project_id} {x.id}`")
            if x.decision_note:
                lines.append(f"- notes: {x.decision_note[:200]}")
            lines.append("")
        if not exps:
            lines.append("_No experiments designed yet._")
        return self._write("experiment_plan.md", "\n".join(lines))

    def write_evaluation_plan(self, project_id: str) -> bool:
        meths = self.rrepos.methodologies.all(project_id)
        lines = ["# Evaluation Plan", "",
                 "_Criteria are defined BEFORE running; post-hoc criteria are flagged "
                 "by the critic._", ""]
        for m in meths:
            lines.append(f"## {m.id} ({m.tier}) → hypothesis {m.hypothesis_id}")
            lines.append(f"- metrics: {[mt.get('name') for mt in m.metrics]}")
            lines.append(f"- success: {m.success_condition[:170]}")
            lines.append(f"- failure: {m.failure_condition[:130]}")
            lines.append(f"- inconclusive: {m.inconclusive_condition[:130]}")
            lines.append(f"- statistical considerations: {m.statistical_notes[:200]}")
            lines.append(f"- ablations: {m.ablation_plan[:3]}")
            lines.append("")
        if not meths:
            lines.append("_No evaluation plans yet._")
        return self._write("evaluation_plan.md", "\n".join(lines))

    def write_validation_plan(self, project_id: str) -> bool:
        exps = self.rrepos.experiments.all(project_id)
        critic = ValidationCritic()
        lines = ["# Validation Plan (startup)", "",
                 "_Behavioral evidence > stated intent; payment is the strongest signal. "
                 "Sequenced so cheap falsifiable tests come first._", ""]
        for x in exps:
            v = critic.inspect(x)
            lines.append(f"- [{x.risk_level}] {x.title[:110]} — status {x.status} — "
                         f"critic: {v['verdict']}")
        if not exps:
            lines.append("_No validation tests designed yet._")
        return self._write("validation_plan.md", "\n".join(lines))

    def write_decision_analysis(self, project_id: str) -> bool:
        dl = DecisionLayer(self.repos, self.rrepos)
        nxt = dl.recommend_next(project_id)
        readiness = dl.decision_readiness(project_id)
        lines = ["# Decision Analysis", ""]
        lines.append(f"**Decision readiness: {readiness['level']}** "
                     f"(score {readiness['score']})")
        lines.append("")
        lines.append("Factors:")
        for k, v in readiness["factors"].items():
            lines.append(f"- {k}: {v:.2f}")
        if readiness["research_debt"]:
            lines.append("")
            lines.append("**Research debt:**")
            lines += [f"- {d}" for d in readiness["research_debt"]]
        lines += ["", "## Recommended next actions", ""]
        for a in nxt["actions"][:8]:
            lines.append(f"- **{a['action']}** → {a['target_id']} "
                         f"(gain {a['expected_information_gain']:.2f}, cost {a['cost']})")
            lines.append(f"    - {a['reason'][:160]}")
        lines += ["",
                  "_Recommendations expose tradeoffs; they are not objective truths. "
                  "Each traces to hypothesis/gap IDs above._"]
        return self._write("decision_analysis.md", "\n".join(lines))


def _fmt_scores(scores: dict) -> str:
    parts = []
    for k, v in scores.items():
        if isinstance(v, (int, float)):
            parts.append(f"{k}={v:.2f}")
    return " ".join(parts)
