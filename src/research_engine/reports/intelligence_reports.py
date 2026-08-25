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
        """READ-ONLY render of persisted opportunities (P0-10/P0-12).
        Discovery/scoring belong to the specialist pipeline, never to report
        generation; this writer renders whatever the canonical engine stored."""
        opps = sorted(
            self.repos.opportunities.all(project_id),
            key=lambda o: -((o.score_breakdown or {}).get("total", 0)))
        lines = ["# Opportunity Map", "",
                 "_Rendered from the canonical opportunity store (read-only). "
                 "Scores follow score_breakdown.schema_version; 'why_now' items "
                 "require change-evidence; assumptions are unvalidated until "
                 "falsification tests pass._", ""]
        for o in opps:
            br = o.score_breakdown or {}
            factors = br.get("factors") or {}
            reasons = br.get("reasons") or {}
            gate = br.get("gate") or {}
            lines.append(f"## {o.id} — score {br.get('total', 0):.2f} "
                         f"(priority {gate.get('priority', 'n/a')})")
            lines.append(f"- segment: {o.customer_segment}")
            lines.append(f"- problem: {o.problem[:200]}")
            lines.append(f"- current alternative: {o.current_alternative}")
            if factors:
                lines.append("- factors:")
                for k, v in factors.items():
                    label = (br.get("labels") or {}).get(k, "")
                    lines.append(f"    - {k}: {v:.2f} [{label}] ({reasons.get(k, '')})")
                lines.append(f"- schema_version: {br.get('schema_version', 1)}")
            else:
                lines.append("- _legacy score format (schema_version 1) — rerun "
                             "`startup discover` to re-score with canonical rubric_")
            lines.append(f"- why_now: {[w[:80] for w in o.why_now] or 'no change-evidence yet'}")
            lines.append(f"- risks: {o.risks}")
            lines.append(f"- evidence ids: {o.evidence_ids[:8]}")
            lines.append("")
        if not opps:
            lines.append("_No opportunities stored. Run `research startup discover`._")
        return self._write("opportunity_map.md", "\n".join(lines))

    def write_validation_candidates(self, project_id: str) -> bool:
        """READ-ONLY render of persisted assumptions + validation artifacts
        (P0-10). Test DESIGN is a research action owned by the specialist
        VALIDATION_PLANNING mode / human approval flow — reports never design."""
        from research_engine.storage.reasoning_repos import ReasoningRepos
        rr = ReasoningRepos(self.repos.db)
        opps = sorted(self.repos.opportunities.all(project_id),
                      key=lambda o: -((o.score_breakdown or {}).get("total", 0)))[:5]
        asm_rows = rr.assumptions.all(project_id)
        experiments = rr.experiments.all(project_id)
        ftests = list(self.repos.db.execute(
            "SELECT data FROM falsification_tests WHERE project_id=?",
            (project_id,)))
        lines = ["# Validation Candidates (persisted state, read-only)", ""]
        for o in opps:
            mine = [a for a in asm_rows
                    if getattr(a, "opportunity_id", "") == o.id]
            tests = [e for e in experiments
                     if getattr(e, "hypothesis_id", "") and True][:6]
            lines.append(f"## {o.id}: {o.problem[:110]}")
            if mine:
                ranked = sorted(mine, key=lambda a: -a.priority)
                lines.append("**Critical assumptions:**")
                for a in ranked[:5]:
                    lines.append(f"- [{a.category}/{a.status}] {a.statement[:140]}")
            else:
                lines.append("_No assumption rows yet — run startup validate._")
            lines.append("")
        if experiments:
            lines.append("## Designed validation tests")
            from research_engine.reasoning.validation_designer import ValidationCritic
            critic = ValidationCritic()
            for e in experiments[:8]:
                verdict = critic.inspect(e)["verdict"]
                lines.append(f"- [{e.status}] {e.title[:100]} — critic: {verdict}")
        elif ftests:
            lines.append("## Legacy falsification templates on file")
            import json as _json
            for r in ftests[:8]:
                d = _json.loads(r["data"])
                lines.append(f"- *{(d.get('assumption') or '')[:90]}*")
        else:
            lines.append("_No validation tests designed yet — run `research "
                         "startup validate`._")
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
