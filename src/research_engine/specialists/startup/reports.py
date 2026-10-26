"""Startup report writers.

startup_research.md follows the fixed 25-section structure (spec #73).
opportunity_report_<id>.md follows the per-opportunity structure (#74) and
ends in the decision-oriented recommendation format (#75).

All sections are assembled deterministically from structured analyzer output
so reports work fully offline; an optional synthesis provider may add a
narrative preamble but facts always come from stored entities.

Mandatory epistemic separation (spec #85): every report carries explicit
WHAT WE KNOW / WHAT WE THINK / WHAT WE ASSUME / WHAT WE DON'T KNOW /
WHAT WE SHOULD TEST blocks derived from evidence kinds, statuses and gaps.
"""
from __future__ import annotations

from research_engine.specialists.startup.policies import qualitative


def _md_list(items, bullet="- ") -> str:
    return "\n".join(f"{bullet}{i}" for i in items) if items else "_none recorded_"


class StartupReportWriter:
    def __init__(self, reports_dir, provider=None):
        self.reports_dir = reports_dir   # workspace reports path (pathlib.Path)
        self.provider = provider

    # ------------------------------------------------------------- main report
    def write_startup_research(self, ctx: dict, discovery: dict,
                               validation: dict, diligence: dict) -> str:
        m = ctx["market"]
        L: list[str] = []
        add = L.append

        add("# Startup Research\n")
        add("## 1. Executive Summary\n")
        top = [t for t in discovery.get("opportunities", []) if t.get("problem")][:3]
        add(f"Market examined: **{m.name}**"
            + (f" ({m.geography})" if m.geography else "") + ".")
        if top:
            names = "; ".join(f"{t['problem'][:80]}… "
                              f"(score {t.get('total_score', 0)}, "
                              f"{t.get('priority', '?')} priority)" for t in top)
            add(f"Leading opportunity candidates: {names}")
        else:
            add("_No opportunity candidates passed the evidence gate yet._")
        if m.definition_gaps:
            add(f"\n**Caveat:** market definition incomplete "
                f"({', '.join(m.definition_gaps)}) — size figures are not "
                "comparable until this is resolved.")
        add("")

        add("## 2. Research Objective\n")
        add(ctx.get("mode_question") or m.name)
        add("")
        add("## 3. Scope\n")
        add(f"- Geography considered: {m.geography or 'unspecified'}")
        add(f"- Time period: {m.time_period or 'current'}")
        add(f"- In scope: {_md_list(m.boundaries)}")
        add(f"- Explicitly excluded: {_md_list(m.exclusions)}")
        add("")

        add("## 4. Market Definition\n")
        add(m.definition or f"_derived from question: {m.name}_")
        if m.definition_gaps:
            add(f"\nUnresolved definition dimensions (open gaps): "
                f"{', '.join(m.definition_gaps)}")
        sr = ctx["size_report"]
        if sr["conflicts"]:
            add("\n### MARKET_SIZE_CONFLICT\n")
            add("Figures disagree beyond tolerance. **Not averaged.** "
                "Differences may be definitions, years, geographies or methodology:")
            for c in sr["conflicts"]:
                vals = ", ".join(f"`{v['raw']}` ({v.get('year') or 'no year'})"
                                 for v in c["values"])
                add(f"- {c['bucket']['currency']} / {c['bucket']['geography']} / "
                    f"{c['bucket']['method_class']}: spread "
                    f"{c['spread_ratio']}x — {vals}")
        add("")

        add("## 5. Market Landscape\n")
        for c in ctx["competitor_profiles"][:8]:
            add(f"- **{c.name}** ({c.classification}): {c.product[:100]}"
                + (f" | model: {c.business_model}" if c.business_model else ""))
        if not ctx["competitor_profiles"]:
            add("- _No competitors identified from evidence "
                "(absence of competitors is a warning, not validation)._")
        ax = ctx["landscape"]
        add(f"\nLandscape axes: `{ax['x_axis']}` × `{ax['y_axis']}` — {ax['justification']}.")
        add("")

        add("## 6. Customer Segments\n")
        for s in ctx["segments"]:
            add(f"- **{s['name']}** — {len(s['evidence_ids'])} supporting evidences; "
                f"buyer: {s.get('buyer') or 'UNKNOWN (user/buyer split unresolved)'}")
        if not ctx["segments"]:
            add("_No segments evidenced._")
        add("")

        add("## 7. Jobs-To-Be-Done\n")
        for j in ctx["jtbd"]:
            add(f"- **{j.segment_id}**: {j.functional_job[:180]}")
            if j.current_alternative:
                add(f"  - current alternative: {j.current_alternative}")
        add("")

        add("## 8. Pain Points\n")
        for p in ctx["pains"][:10]:
            add(f"- [{p['evidence_class'].replace('_', ' ')}] "
                f"[{', '.join(p['categories'])}] {p['statement'][:160]}")
        if not ctx["pains"]:
            add("_No pain evidence classified._")
        add("")

        add("## 9. Current Alternatives\n")
        for a in ctx["alternatives"]:
            add(f"- **{a.name}** ({a.kind}) — {len(a.evidence_ids)} evidences")
        add("\n_'Doing nothing' is a legitimate competitor and appears above when evidenced._\n")

        add("## 10. Competitor Landscape\n")
        profs = ctx["competitor_profiles"]
        for c in profs[:8]:
            strengths = f"; strengths: {'; '.join(c.strengths[:2])}" if c.strengths else ""
            weak = f"; weaknesses: {'; '.join(c.weaknesses[:2])}" if c.weaknesses else ""
            traction = f" | traction: {c.traction_note}" if c.traction_note else ""
            add(f"- **{c.name}** — {c.positioning[:120] or c.product[:120]}"
                f"{strengths}{weak}{traction}")
        add("")

        add("## 11. Pricing\n")
        for p in ctx["pricing_plans"][:10]:
            norm = (f" (≈{p.annualized_normalized}/mo normalized: {p.normalization_note})"
                    if p.annualized_normalized else "")
            add(f"- {p.competitor_name or 'unknown company'}: `{p.price_raw}` "
                f"[{p.billing_period}] model={p.pricing_model or 'unclassified'}{norm}")
        if not ctx["pricing_plans"]:
            add("_No pricing observations collected — pricing research incomplete._")
        add("")

        add("## 12. Distribution\n")
        dd = ctx["distribution_difficulty"]
        add(f"Verdict: **{dd['verdict']}**")
        for ch in ctx["channels"][:8]:
            add(f"- {ch.name}: {ch.evidence_class} (used by {', '.join(ch.used_by[:3])})")
        for b in dd.get("evidence_barriers", [])[:4]:
            add(f"- barrier: {b['note']}")
        add("")

        add("## 13. Technology Shifts\n")
        for t in ctx["tech_shifts"][:6]:
            add(f"- [{t.kind}] {t.description[:170]}")
        if not ctx["tech_shifts"]:
            add("_None detected._")
        add("")

        add("## 14. Regulatory Factors\n")
        add(m.regulatory_environment or
            "_No regulatory evidence collected (regulation refreshes aggressively "
            "when present)._")
        reg_signals = [s for s in ctx["signals"] if s.get("kind") == "regulation"]
        for s in reg_signals[:4]:
            add(f"- [{s['strength']}] {s['description'][:150]}")
        add("")

        add("## 15. Market Signals\n")
        for s in ctx["signals"][:8]:
            add(f"- [{s['strength']}|{s.get('underlying_sources', 1)} underlying] "
                f"({s['kind']}) {s['description'][:140]}")
        if not ctx["signals"]:
            add("_No signals observed._")
        add("")

        add("## 16. Why Now\n")
        wn = ctx["whynow"]
        verdict = wn.get("verdict", "not assessed")
        add(f"Verdict: **{verdict}**" +
            (" — timing is unproven" if verdict == "WHY_NOW_WEAK" else ""))
        for i in wn.get("items", [])[:5]:
            add(f"- [{i.get('source')}/{i.get('strength', i.get('kind', ''))}] "
                f"{i.get('text', '')[:160]}")
        add("")

        add("## 17. Opportunities\n")
        for t in discovery.get("opportunities", []):
            if not t.get("problem"):
                continue
            add(f"- **{t['problem'][:120]}** — score {t.get('total_score', 0)}, "
                f"{t.get('priority', '?')} priority ({t.get('portfolio_slot', '')})")
        if not discovery.get("opportunities"):
            add("_None passed the gate — see Unknowns below._")
        add("")

        add("## 18. Evidence For\n")
        dil = diligence.get("verification", {}).get("failure_cases", {})
        add(dil.get("strongest_argument_for", "_see opportunity reports_"))
        add("")
        add("## 19. Evidence Against\n")
        add(dil.get("strongest_argument_against",
                    "_counterevidence search found no direct negatives; absence of "
                    "failure data is NOT safety_"))
        negs = dil.get("negative_evidence", [])
        for n in negs:
            add(f"- {n['text'][:150]}")
        add("")

        add("## 20. Critical Assumptions\n")
        plans = validation.get("plans", [])
        asm_count = sum(p.get("assumptions_created", 0) for p in plans)
        if asm_count:
            add(f"{asm_count} assumptions registered as first-class entities "
                "(ranked by importance × uncertainty × impact × testability). "
                "See `assumptions` CLI/API for the ranked register.")
        else:
            add("_No business assumptions registered yet — run validation planning._")
        add("")

        add("## 21. Validation Strategy\n")
        for p in plans:
            tests = p.get("tests_designed", [])
            add(f"_Opportunity {p['opportunity_id']}: {len(tests)} tests designed, "
                "cheapest-decisive first:_")
            for t in tests[:5]:
                add(f"  - [{t['test_type']}|cost {t['cost']}|gain {t['expected_information_gain']}] "
                    f"{t['title'][:110]} — critic: {t['critic_verdict']}")
            stages = p.get("staged_sequence", [])
            for st in stages:
                add(f"  - stage gate: {st['stage']}")
        if not plans:
            add("_No validation plan built yet._")
        add("")

        add("## 22. Major Risks\n")
        risks = set()
        for t in discovery.get("opportunities", []):
            risks.add(t.get("priority", "") + "-priority candidate uncertainty")
        if dd["verdict"] == "distribution_difficult":
            risks.add("distribution difficulty evidenced")
        if sr["conflicts"]:
            risks.add("market-size figures conflict — sizing unreliable until resolved")
        if wn.get("verdict") == "WHY_NOW_WEAK":
            risks.add("timing unproven (WHY_NOW_WEAK)")
        add(_md_list(sorted(risks)))
        add("")

        kn, th, as_, unk, tst = self._epistemic_blocks(ctx, discovery,
                                                       validation, diligence)
        add("## 23. Unknowns\n")
        add(_md_list(unk))
        add("")

        add("## 24. Recommended Next Actions\n")
        recs = diligence.get("recommendation")
        if recs:
            add(f"Decision: **{recs['decision'].upper()}** — {recs['recommendation_text']}")
            add(f"- Best next action: {recs['best_next_action']}")
            add(f"- Most important assumption: {recs['most_important_assumption'] or 'TBD'}")
            add(f"- What would change this: {recs['what_would_change_this_recommendation']}")
        else:
            add("- Run OPPORTUNITY_DISCOVERY then VALIDATION_PLANNING.")
        add("")

        add("## 25. Sources\n")
        src_ids = sorted({eid for s in ctx["pains"] for eid in [s["evidence_id"]]}
                         | {eid for c in ctx["competitor_profiles"]
                            for eid in c.evidence_ids})
        add(f"{len(src_ids)} evidence items cited across sections "
            "(full provenance via trace endpoints; rejected rows retained in DB).")
        add("")

        add("---\n")
        add("## Epistemic Status (mandatory)\n")
        add("**WHAT WE KNOW** (evidence-backed)\n" + _md_list(kn))
        add("\n**WHAT WE THINK** (inference from evidence)\n" + _md_list(th))
        add("\n**WHAT WE ASSUME** (unverified)\n" + _md_list(as_))
        add("\n**WHAT WE DON'T KNOW**\n" + _md_list(unk))
        add("\n**WHAT WE SHOULD TEST**\n" + _md_list(tst))

        text = "\n".join(L) + "\n"
        path = self.reports_dir / "startup_research.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    # ------------------------------------------------------------- opp report
    def write_opportunity_report(self, opp, rubric: dict, pair: dict,
                                 wnb: dict, moats: list, readiness: dict,
                                 recommendation: dict) -> str:
        sb = rubric
        L = []
        add = L.append
        add(f"# Opportunity Report: {opp.problem[:100]}\n")
        add(f"- Customer segment: {opp.customer_segment}")
        add(f"- Job to be done: {opp.job_to_be_done or 'TBD'}")
        add(f"- Current alternative: {opp.current_alternative}")
        add(f"- Pattern/derivation: {opp.notes}\n")
        add("## Rubric (visible dimensions, no fake precision)\n")
        for dim, w in sb.get("weights", {}).items():
            label = sb.get("labels", {}).get(dim, "?")
            reason = sb.get("reasons", {}).get(dim, "")
            add(f"- {dim}: **{label}** ({sb['factors'].get(dim, 0)}) — {reason}")
        add(f"- Composite total: {sb.get('total')} _(ranking aid only)_\n")
        add("## Evidence For\n" + pair.get("strongest_argument_for", "_none_") + "\n")
        add("## Evidence Against\n" + pair.get("strongest_argument_against", "_none_"))
        for n in pair.get("negative_evidence", []):
            add(f"- {n['text'][:150]}")
        add("")
        add("## Why Now\n")
        add(f"- timing evidence status recorded in startup_research.md §16\n")
        add("## Why Hasn't This Been Built?\n")
        add(f"Most likely explanation: **{wnb.get('most_likely', 'unknown')}**")
        for f in wnb.get("explanations", []):
            if f["plausible"]:
                add(f"- {f['explanation']} (evidence: {', '.join(f['supporting_evidence'])})")
        if wnb.get("no_visible_competitors_note"):
            add(f"- ⚠ {wnb['no_visible_competitors_note']}")
        add("")
        add("## Potential Moats\n")
        for mo in moats:
            add(f"- {mo['moat_type']}: {mo['status']}"
                + (f" ({', '.join(mo['evidence_ids'])})" if mo["evidence_ids"] else ""))
        add("")
        add("## Readiness\n")
        add(f"- Level: **{readiness['level']}** "
            f"(coverage {readiness['coverage']['covered']}/{readiness['coverage']['total']}; "
            f"critical assumptions untested: {readiness['critical_assumptions_untested']})\n")
        add("## Recommendation\n")
        add(f"```\nRecommendation:\n    {recommendation['decision']} — "
            f"{recommendation['recommendation_text']}\n\n"
            f"Evidence supporting:\n    {recommendation['evidence_supporting']}\n\n"
            f"Evidence against:\n    {recommendation['evidence_against']}\n\n"
            f"Critical uncertainty:\n    {recommendation['critical_uncertainty']}\n\n"
            f"Most important assumption:\n    "
            f"{recommendation['most_important_assumption'] or 'not yet identified'}\n\n"
            f"Best next action:\n    {recommendation['best_next_action']}\n\n"
            f"What would change this recommendation:\n    "
            f"{recommendation['what_would_change_this_recommendation']}\n```")
        path = self.reports_dir / f"opportunity_report_{opp.id}.md"
        path.write_text("\n".join(L) + "\n", encoding="utf-8")
        return str(path)

    # ------------------------------------------------------------- epistemics
    def _epistemic_blocks(self, ctx, discovery, validation, diligence):
        """Derive KNOW/THINK/ASSUME/DONT_KNOW/TEST from artifact states."""
        know, think, assume, dontknow, test = [], [], [], [], []
        strong_pains = [p for p in ctx["pains"]
                        if p["hierarchy_weight"] >= 0.6]
        for p in strong_pains[:4]:
            know.append(f"pain ({p['evidence_class']}): {p['statement'][:120]}")
        for pl in ctx["pricing_plans"][:3]:
            know.append(f"pricing observation: {pl.competitor_name} `{pl.price_raw}`")
        for s in ctx["segments"][:3]:
            think.append(f"'{s['name']}' behaves as a distinct segment "
                         f"({len(s['evidence_ids'])} evidences)")
        if ctx["market"].definition_gaps:
            dontknow.append("exact market definition (" +
                            ", ".join(ctx["market"].definition_gaps) + ")")
        if ctx["whynow"].get("verdict") == "WHY_NOW_WEAK":
            dontknow.append("why now — no credible change evidence")
        for t in discovery.get("opportunities", []):
            assume.append(f"opportunity viable: {t['problem'][:90]}… "
                          f"(priority {t['priority']})")
        plans = validation.get("plans", [])
        for p in plans:
            for t in p.get("tests_designed", [])[:3]:
                test.append(f"{t['test_type']}: {t['title'][:90]}…")
        if ctx["whynow"].get("verdict") != "WHY_NOW_WEAK" and ctx["tech_shifts"]:
            think.append("recent technology shifts make new solutions practical")
        return know, think, assume, dontknow, test

    # ------------------------------------------------------------- full write
    def generate_all(self, project_id: str, ctx: dict, pipeline_result: dict,
                     diligence: dict) -> list[str]:
        written = []
        written.append(self.write_startup_research(
            ctx, pipeline_result.get("discovery", {}),
            pipeline_result.get("validation", {}), diligence))

        repos = ctx["_repos"][0]
        engine = ctx["_analyzer_handles"]["opportunities"]
        decisions = ctx["_analyzer_handles"]["decisions"]
        opps = repos.opportunities.all(project_id)
        for opp in opps[:3]:
            sb = opp.score_breakdown or {}
            gate = sb.get("gate", {})
            readiness = decisions.readiness(project_id, opp.id, gate)
            rec = decisions.recommend(project_id, opp, gate, readiness, [],
                                      counter_pair=engine.counter_evidence_pair(
                                          project_id, opp))
            try:
                written.append(self.write_opportunity_report(
                    opp, sb, engine.counter_evidence_pair(project_id, opp),
                    engine.why_not_built(project_id, opp, ctx),
                    engine.moat_analysis(project_id, opp),
                    readiness, rec))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "opportunity report failed for %s: %s", opp.id, exc)
        return written
