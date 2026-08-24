"""Phase 2 intelligence reports: literature map, benchmarks, market map,
opportunity map, evidence map, contradiction report, timeline.

Deterministic derivations from DB + graph; every item cites IDs.
"""
from __future__ import annotations

from research_engine.intelligence.literature import (LiteratureMapper,
                                                     compare_methods,
                                                     extract_benchmark_results)
from research_engine.intelligence.startup import StartupIntelligence
from research_engine.reasoning.priority import BranchCoverageModel
from research_engine.storage.graph_store import GraphStore


class IntelligenceReports:
    def __init__(self, repos, ws, graph: GraphStore | None = None):
        self.repos = repos
        self.ws = ws
        self.graph = graph or GraphStore(repos.db)

    def _write(self, name: str, content: str) -> bool:
        (self.ws.report_path(name)).write_text(content, encoding="utf-8")
        return True

    # ------------------------------------------------------------------ academic
    def write_literature_map(self, project_id: str) -> bool:
        lm = LiteratureMapper(self.repos, self.graph)
        m = lm.build_map(project_id)
        lines = [f"# Literature Map", "",
                 f"Papers parsed: **{m['n_papers']}**", ""]
        if m["n_papers"] == 0:
            lines.append("_No research papers were parsed in this project._")
            return self._write("literature_map.md", "\n".join(lines))
        lines += ["## Clusters (research directions)", ""]
        for c in m["clusters"]:
            lines.append(f"### {c['label']} ({c['size']} papers)")
            lines.append(f"- key terms: {', '.join(c['top_terms'])}")
            for p in c["representative_papers"]:
                lines.append(f"- [{p['title'][:90]}]({p['url']}) "
                             f"({p['year'] or 'n.d.'}, citations={p['citations']})")
            lines.append("")
        lines += ["## Foundational Work (composite score)", ""]
        for p in m["foundational"]:
            lines.append(f"- **{p['title'][:100]}** ({p.get('year')}) — score "
                         f"{p['foundational_score']} — {p['url']}")
        lines += ["", "## Recent Work", ""]
        recent = m["recent"]
        if not recent:
            lines.append("_No papers within the recency window._")
        for p in recent:
            lines.append(f"- **{p['title'][:100]}** ({p.get('year')}) — score "
                         f"{p['recent_score']} — {p['url']}")
        lines += ["", "## Publication Trend", "", m["trend_observation"], ""]
        return self._write("literature_map.md", "\n".join(lines))

    def write_method_comparison(self, project_id: str) -> bool:
        results = extract_benchmark_results(self.repos, project_id)
        by_method: dict[str, list[dict]] = {}
        sources = {s.id: s for s in self.repos.sources.all(project_id)}
        for r in results:
            method = ""
            ev = self.repos.evidence.get(r["evidence_id"])
            if ev:
                src = sources.get(ev.source_id)
                method = src.title[:40] if src else "unknown"
            if method:
                by_method.setdefault(method, []).append(r)
        rows = compare_methods(by_method) if len(by_method) >= 2 else []
        lines = ["# Methods Comparison", "",
                 "_Metrics are NEVER compared across incompatible evaluation settings; "
                 "rows without shared settings are flagged instead of compared._", ""]
        if rows:
            lines += ["| A | B | shared setting? | note |", "|---|---|---|---|"]
            for r in rows[:30]:
                lines.append(f"| {r['method_a'][:35]} | {r['method_b'][:35]} | "
                             f"{'yes' if r['comparable_on_shared_benchmarks'] else 'NO'} "
                             f"| {r['note'][:80]} |")
        else:
            lines.append("_Insufficient structured benchmark data for a comparison table._")
        lines += ["", "## Extracted Benchmark Results", ""]
        for r in results[:40]:
            lines.append(f"- [{r['evidence_id']}] {r['paper'][:50]}: {r['metric']}="
                         f"{r['value'] or '?'} on {r['benchmark'] or '?'} ({r['setting']}, "
                         f"{r['date'] or 'n.d.'})")
        if not results:
            lines.append("_No benchmark-tagged evidence found._")
        return self._write("methods_comparison.md", "\n".join(lines))

    def write_benchmark_analysis(self, project_id: str) -> bool:
        results = extract_benchmark_results(self.repos, project_id)
        per_bench: dict[str, list] = {}
        for r in results:
            per_bench.setdefault(r["benchmark"] or "unclassified", []).append(r)
        lines = ["# Benchmark Analysis", ""]
        lines = [f"# Benchmark Analysis", "",
                 f"Benchmarks identified: **{len([b for b in per_bench if b != 'unclassified'])}** · "
                 f"results extracted: **{len(results)}**", ""]
        for bench, items in sorted(per_bench.items(), key=lambda kv: -len(kv[1])):
            dates = sorted({i["date"] for i in items if i["date"]})
            lines.append(f"## {bench} ({len(items)} results)")
            lines.append(f"- used across {len({i['paper'] for i in items})} papers; "
                         f"dates observed: {dates[0] if dates else '?'} … {dates[-1] if dates else '?'}")
            saturation = "possibly saturated (many results)" if len(items) >= 6 else \
                         ("thin coverage" if len(items) <= 2 else "moderate usage")
            lines.append(f"- usage signal: {saturation}")
            lines.append("")
        return self._write("benchmark_analysis.md", "\n".join(lines))

    # ------------------------------------------------------------------ startup
    def write_market_map(self, project_id: str) -> bool:
        si = StartupIntelligence(self.repos, self.graph)
        pains = si.load_startup_entities(project_id, "pain_point")
        prices = si.load_startup_entities(project_id, "price_observation")
        signals = si.load_startup_entities(project_id, "market_signal")
        comps = si.load_startup_entities(project_id, "competitor")
        lines = ["# Market Map", ""]
        lines += ["## Customer Pains (stated/observed)", ""]
        for p in pains[:20]:
            lines.append(f"- {p['statement'][:140]} *(signals={p.get('frequency_signals', 1)}, "
                         f"kind={p.get('kind')})*")
        if not pains:
            lines.append("_No pain-point evidence collected._")
        lines += ["", "## Competitors / Alternatives", ""]
        for c in comps[:20]:
            traction = c.get("funding_signal") or c.get("customer_evidence") or "existence only"
            lines.append(f"- **{c.get('name', c)[:60]}** — positioning: "
                         f"{c.get('positioning', '')[:60]}; traction evidence: {traction}")
        lines += ["", "## Price Observations (never compare without comparing what is included)", ""]
        for pr in prices[:20]:
            lines.append(f"- {pr.get('amount_raw')} {pr.get('currency')}/"
                         f"{pr.get('billing_period') or '?'} — limits: "
                         f"{pr.get('included_limits', '')[:50]} — observed {pr.get('observed_date')}")
        lines += ["", "## Market Signals (aggregated, not counted blindly)", ""]
        by_kind: dict[str, int] = {}
        for s in signals:
            k = s.get("kind", "?")
            by_kind[k] = by_kind.get(k, 0) + 1
        for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
            lines.append(f"- **{k}**: {n} independent observations")
        return self._write("market_map.md", "\n".join(lines))

    def write_opportunity_map(self, project_id: str) -> bool:
        si = StartupIntelligence(self.repos, self.graph)
        opps = si.discover_opportunities(project_id)
        lines = ["# Opportunity Map", "",
                 "_Every opportunity emerges from clustered evidence with transparent scoring. "
                 "'why_now' items require change-evidence; assumptions are unvalidated until "
                 "falsification tests pass._", ""]
        scored = [(o, si.score_opportunity(project_id, o)) for o in opps]
        scored.sort(key=lambda t: -t[1]["total"])
        for o, br in scored:
            lines.append(f"## {o.id} — score {br['total']:.2f} (confidence {o.confidence:.2f})")
            lines.append(f"- segment: {o.customer_segment}")
            lines.append(f"- problem: {o.problem[:200]}")
            lines.append(f"- current alternative: {o.current_alternative}")
            lines.append(f"- factors:")
            for k, v in br["factors"].items():
                lines.append(f"    - {k}: {v:.2f} ({br['reasons'].get(k, '')})")
            lines.append(f"- why_now: {[w[:80] for w in o.why_now] or 'no change-evidence yet'}")
            lines.append(f"- risks: {o.risks}")
            lines.append(f"- evidence ids: {o.evidence_ids[:8]}")
            lines.append("")
        if not scored:
            lines.append("_No opportunities met the evidence threshold (needs >=2 distinct "
                         "pain evidences or pain + corroborating signal)._")
        return self._write("opportunity_map.md", "\n".join(lines))

    def write_validation_candidates(self, project_id: str) -> bool:
        from research_engine.intelligence.falsification import AssumptionEngine
        si = StartupIntelligence(self.repos, self.graph)
        eng = AssumptionEngine(self.repos, provider=None)  # deterministic template tests
        opps = si.discover_opportunities(project_id)
        lines = ["# Validation Candidates (assumptions + falsification tests)", ""]
        for o in opps[:5]:
            o.critical_assumptions = eng.critical_assumptions(o)
            tests = eng.design_falsification_tests(project_id, o)
            lines.append(f"## {o.id}: {o.problem[:110]}")
            lines.append("**Critical assumptions:**")
            for a in o.critical_assumptions:
                lines.append(f"- {a}")
            lines.append("\n**Falsification tests:**")
            for t in tests:
                lines.append(f"- *{t.assumption[:90]}*")
                lines.append(f"    - test: {t.cheapest_test}")
                lines.append(f"    - pass: {t.success_condition}")
                lines.append(f"    - fail: {t.failure_condition}")
                lines.append(f"    - decision: {t.decision_rule}")
            lines.append("")
        if not opps:
            lines.append("_No opportunities to validate yet._")
        return self._write("validation_candidates.md", "\n".join(lines))

    # ------------------------------------------------------------------ general
    def write_evidence_map(self, project_id: str) -> bool:
        """Evidence density by branch + tier histogram."""
        cov_repo = BranchCoverageModel(self.repos)
        plans = self.repos.plans.all(project_id)
        branches = plans[-1].branches if plans else []
        coverage = cov_repo.compute(project_id, branches)
        tiers: dict[int, int] = {}
        evs = [e for e in self.repos.evidence.all(project_id)
               if e.status.value != "REJECTED"]
        for e in evs:
            tiers[e.source_tier] = tiers.get(e.source_tier, 0) + 1
        lines = ["# Evidence Map", "",
                 f"Evidence items (accepted): **{len(evs)}**",
                 f"Tier histogram: {dict(sorted(tiers.items()))}", "",
                 "| branch | importance | coverage | evidence | strong | gaps |",
                 "|---|---|---|---|---|---|"]
        for b in branches:
            c = coverage.get(b.id, {})
            lines.append(f"| {b.question[:60]} | {b.importance:.2f} | "
                         f"{c.get('coverage', 0):.2f} | {c.get('evidence_count', 0)} | "
                         f"{c.get('strong_evidence_count', 0)} | {c.get('gap_count', 0)} |")
        return self._write("evidence_map.md", "\n".join(lines))

    def write_contradiction_report(self, project_id: str) -> bool:
        from research_engine.reasoning.contradiction_analyzer import ContradictionAnalyzer
        analyzer = ContradictionAnalyzer(self.repos)
        cons = self.repos.contradictions.all(project_id)
        lines = ["# Contradiction Report", "",
                 "_Contradictions are analyzed but never auto-resolved._", ""]
        if not cons:
            lines.append("_No contradictions detected._")
            return self._write("contradiction_report.md", "\n".join(lines))
        for c in cons:
            assessment = analyzer.assess(project_id, c)
            lines.append(f"## {c.id} — verdict: **{assessment.verdict}**")
            lines.append(f"- A: {c.statement_a}")
            lines.append(f"- B: {c.statement_b}")
            lines.append(f"- analysis: {assessment.explanation}")
            lines.append(f"- dimensions: {assessment.dimensions}")
            lines.append(f"- suggested follow-up: *{c.follow_up_query}*")
            lines.append("")
        return self._write("contradiction_report.md", "\n".join(lines))

    def write_research_timeline(self, project_id: str) -> bool:
        events = []
        import json as _json
        from pathlib import Path as _P
        ev_path = self.ws.root / "events.jsonl"
        if ev_path.exists():
            for line in ev_path.read_text().splitlines():
                try:
                    events.append(_json.loads(line))
                except Exception:
                    continue
        lines = ["# Research Timeline", ""]
        for e in events:
            ts = e.get("ts", "")[:19].replace("T", " ")
            meta = e.get("metadata", {})
            detail = ", ".join(f"{k}={v}" for k, v in list(meta.items())[:4])
            lines.append(f"- `{ts}` {e['event']}" + (f" — {detail}" if detail else ""))
        return self._write("research_timeline.md", "\n".join(lines))
