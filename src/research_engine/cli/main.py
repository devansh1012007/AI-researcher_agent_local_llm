"""GAR CLI — research command.

Commands: new, run, status, pause, resume, inspect, report, gaps, sources, queries, evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from research_engine.core.config import AppConfig

console = Console()


def _cfg(args) -> AppConfig:
    return AppConfig.load(getattr(args, "config", None))


def _project_id_or_fail(cfg: AppConfig, pid: str) -> str:
    from research_engine.storage.workspace import Workspace
    if (Path(cfg.storage.data_dir) / pid / "project.json").exists():
        return pid
    console.print(f"[red]Project not found:[/red] {pid} (looked in {cfg.storage.data_dir}/{pid})")
    sys.exit(1)


def cmd_new(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.create_project(cfg, args.question, mode=args.mode)
    console.print(f"[green]Research project created.[/green]")
    console.print(f"  id:      {orch.project.id}")
    console.print(f"  mode:    {orch.project.mode}")
    console.print(f"  state:   {orch.project.state.value}")
    if not args.no_run:
        console.print("\n[bold]Running research...[/bold]\n")
        project = orch.run()
        _print_status(orch)
        console.print(f"\nReports: {orch.ws.reports}")
        console.print(f"Stop reason: {project.stop_reason.value if project.stop_reason else 'n/a'}")


def cmd_run(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    pid = _project_id_or_fail(cfg, args.project_id)
    orch = Orchestrator.load(cfg, pid)
    project = orch.run(max_iterations=args.iterations)
    _print_status(orch)


def cmd_status(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    _print_status(orch)


def _print_status(orch):
    p = orch.project
    r = orch.repos
    table = Table(title=f"Project {p.id}", show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    b = p.budget
    parsed_sources = r.sources.count(p.id, "status='PARSED'")
    accepted_ev = r.evidence.count(p.id, "status!='REJECTED'")
    rejected_ev = r.evidence.count(p.id, "status='REJECTED'")
    rows = [
        ("state", f"{p.state.value}" + (f"  (gate: {p.review_gate_pending})" if p.review_gate_pending else "")),
        ("mode", p.mode),
        ("iteration", str(p.current_iteration)),
        ("stop reason", p.stop_reason.value if p.stop_reason else "-"),
        ("sources", f"{parsed_sources} parsed / {r.sources.count(p.id)} discovered"),
        ("documents", str(r.documents.count(p.id))),
        ("evidence", f"{accepted_ev} accepted / {rejected_ev} rejected"),
        ("claims", str(r.claims.count(p.id))),
        ("contradictions", str(r.contradictions.count(p.id))),
        ("gaps", f"{r.gaps.count(p.id, 'resolved=0')} open / {r.gaps.count(p.id, 'resolved=1')} resolved"),
        ("queries", f"{r.queries.count(p.id, 'executed=0')} pending / "
                    f"{r.queries.count(p.id, 'executed=1')} executed"),
        ("tasks failed", str(r.tasks.count(p.id, "status IN ('FAILED','DEAD')"))),
        ("budget", json.dumps(orch.budget.snapshot())),
    ]
    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


def cmd_pause(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.models.enums import ProjectState
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    orch.request_stop()
    orch.sm.transition(orch.project, ProjectState.PAUSED, "user pause")
    orch.persist_checkpoint()
    console.print("[yellow]Paused.[/yellow] Resume with: research resume " + orch.project.id)


def cmd_resume(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    project = orch.resume()
    _print_status(orch)


def cmd_inspect(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    p = orch.project
    r = orch.repos
    console.rule("problem")
    for prob in r.problems.all(p.id):
        console.print_json(prob.model_dump_json())
    console.rule("branches")
    plans = r.plans.all(p.id)
    if plans:
        for br in sorted(plans[-1].branches, key=lambda x: -x.importance):
            console.print(f"[cyan]{br.category:22}[/cyan] imp={br.importance:.2f} {br.question[:100]}")
    console.rule("recent claims")
    for c in sorted(r.claims.all(p.id), key=lambda x: -x.confidence)[:args.limit]:
        console.print(f"[green]{c.id}[/green] conf={c.confidence:.2f} [{c.kind.value}] {c.text[:120]}")


def cmd_report(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    from research_engine.reports.generator import ReportGenerator
    gen = ReportGenerator(cfg, orch.router.synthesis, orch.repos, orch.ws)
    written = gen.generate_all(orch.project)
    console.print("[green]Regenerated:[/green] " + ", ".join(written))
    console.print(f"Directory: {orch.ws.reports}")


def cmd_gaps(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    gaps = sorted([g for g in orch.repos.gaps.all(orch.project.id) if not g.resolved],
                  key=lambda g: -g.importance)
    if not gaps:
        console.print("No open gaps.")
        return
    t = Table(title="Open Gaps")
    for col in ("id", "importance", "category", "description"):
        t.add_column(col)
    for g in gaps[:40]:
        t.add_row(g.id, f"{g.importance:.2f}", g.category.value, g.description[:90])
    console.print(t)


def cmd_sources(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    srcs = sorted(orch.repos.sources.all(orch.project.id), key=lambda s: s.source_tier)
    t = Table(title="Sources")
    for col in ("id", "tier", "type", "status", "title", "url"):
        t.add_column(col, overflow="fold")
    for s in srcs[:80]:
        t.add_row(s.id, str(s.source_tier), s.source_type.value, s.content_status,
                  s.title[:50], s.url[:60])
    console.print(t)


def cmd_evidence(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    evs = orch.repos.evidence.all(orch.project.id, "status!='REJECTED'")
    if args.search:
        ids = set(orch.db.fts_search(orch.project.id, args.search, limit=100))
        evs = [e for e in evs if e.id in ids]
    for e in sorted(evs, key=lambda x: (x.source_tier, -x.confidence))[:args.limit]:
        console.print(f"[green]{e.id}[/green] tier:{e.source_tier} conf:{e.confidence:.2f} "
                      f"({e.location})\n  claim: {e.claim_text[:140]}\n  quote: \"{e.quote[:140]}\"\n"
                      f"  src: {e.source_title[:70]} {e.source_url[:60]}\n")


# ---------------------------------------------------------------------------
# Phase 2 commands
# ---------------------------------------------------------------------------

def _load2(args):
    cfg = _cfg(args)
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.load(cfg, _project_id_or_fail(cfg, args.project_id))
    from research_engine.storage.graph_store import GraphStore
    return cfg, orch, GraphStore(orch.db)


def cmd_map(args):
    """Literature/market map depending on mode."""
    _cfg, orch, graph = _load2(args)
    p = orch.project
    if p.mode == "startup":
        from research_engine.intelligence.startup import StartupIntelligence
        si = StartupIntelligence(orch.repos, graph)
        stats = si.extract_all(p.id)
        console.print(f"[bold]Market map[/bold] ({p.id}):")
        for kind, items in stats.items():
            console.print(f"  {kind}: {len(items)}")
        opps = si.discover_opportunities(p.id)
        for o in opps:
            br = si.score_opportunity(p.id, o)
            console.print(f"\n[cyan]{o.id}[/cyan] score={br['total']:.2f} "
                          f"(conf={o.confidence:.2f})")
            console.print(f"  problem: {o.problem[:110]}")
            console.print(f"  why_now: {[w[:60] for w in o.why_now]}")
            console.print(f"  factors: {br['factors']}")
    else:
        from research_engine.intelligence.literature import LiteratureMapper
        lm = LiteratureMapper(orch.repos, graph)
        m = lm.build_map(p.id)
        console.print(f"[bold]Literature map[/bold] ({p.id}): {m['n_papers']} papers parsed")
        for c in m["clusters"]:
            console.print(f"  cluster [{c['label']}]: {c['size']} papers; terms={c['top_terms'][:4]}")
        console.print(f"\nFoundational: "
                      + "; ".join(x["title"][:40] for x in m["foundational"][:3]))
        console.print(f"Recent: " + "; ".join(x["title"][:40] for x in m["recent"][:3]))
        console.print(f"Trend: {m['trend_observation']}")


def cmd_branches(args):
    from research_engine.reasoning.priority import BranchCoverageModel
    _cfg, orch, _g = _load2(args)
    plans = orch.repos.plans.all(orch.project.id)
    plan = plans[-1] if plans else None
    if not plan:
        console.print("No research plan yet.")
        return
    coverage = BranchCoverageModel(orch.repos).compute(orch.project.id, plan.branches)
    t = Table(title="Research Branches (coverage)")
    for col in ("id", "importance", "coverage", "status", "ev", "gaps", "question"):
        t.add_column(col)
    for b in sorted(plan.branches, key=lambda x: -x.importance):
        c = coverage.get(b.id, {})
        t.add_row(b.id, f"{b.importance:.2f}", f"{c.get('coverage', 0):.2f}",
                  b.status, str(c.get("evidence_count", 0)), str(c.get("gap_count", 0)),
                  b.question[:70])
    console.print(t)


def cmd_papers(args):
    _cfg, orch, graph = _load2(args)
    papers = graph.entities(orch.project.id, "paper")
    if not papers:
        console.print("No paper entities yet.")
        return
    t = Table(title=f"Papers ({len(papers)})")
    for col in ("id", "title", "venue", "published", "citations"):
        t.add_column(col, overflow="fold")
    for p in papers:
        a = p.attributes
        t.add_row(p.id, (a.get("title") or p.name)[:60], a.get("venue", "")[:20],
                  str(a.get("published") or ""), str(a.get("citations", "")))
    console.print(t)


def cmd_competitors(args):
    _cfg, orch, graph = _load2(args)
    comps = graph.entities(orch.project.id, "competitor")
    pains = graph.entities(orch.project.id, "pain_point")
    prices = graph.entities(orch.project.id, "price_observation")
    signals = graph.entities(orch.project.id, "market_signal")
    console.print(f"Competitors: {len(comps)} | Pain points: {len(pains)} | "
                  f"Price observations: {len(prices)} | Market signals: {len(signals)}")
    for e in prices:
        a = e.attributes
        console.print(f"  price: {a.get('amount_raw')} {a.get('currency')}/"
                      f"{a.get('billing_period') or '?'} ({e.name[:30]})")
    for s in signals[:10]:
        console.print(f"  signal[{s.attributes.get('kind')}]: {e and ''}{s.name[:80]}")


def cmd_opportunities(args):
    _cfg, orch, graph = _load2(args)
    from research_engine.intelligence.startup import StartupIntelligence
    si = StartupIntelligence(orch.repos, graph)
    opps = si.discover_opportunities(orch.project.id)
    if not opps:
        console.print("No opportunities discovered from current evidence.")
        return
    for o in opps:
        br = si.score_opportunity(orch.project.id, o)
        console.print(f"\n[bold cyan]{o.id}[/bold cyan] score={br['total']:.2f} conf={o.confidence:.2f}")
        console.print(f"  segment:   {o.customer_segment}")
        console.print(f"  problem:   {o.problem[:120]}")
        console.print(f"  alt:       {o.current_alternative}")
        console.print(f"  evidence:  {len(o.evidence_ids)} ids; why_now: {len(o.why_now)}")


def cmd_ask(args):
    _cfg, orch, graph = _load2(args)
    from research_engine.memory.qa import GroundedQA
    from research_engine.memory.retrieval import build_retriever
    ret = build_retriever(_cfg, orch.repos)
    n = ret.index_project(orch.project.id)
    log = console.status if False else None
    qa = GroundedQA(orch.repos, ret, provider=orch.router.reasoning)
    r = qa.ask(orch.project.id, args.question)
    console.print(qa.format_response(r))


def cmd_trace_claim(args):
    _cfg, orch, graph = _load2(args)
    from research_engine.memory.qa import trace_claim
    chain = trace_claim(orch.repos, args.claim_id)
    console.print_json(json.dumps(chain, default=str))


def cmd_verify_claim(args):
    """Focused verification branch for one claim (spec #108)."""
    _cfg, orch, graph = _load2(args)
    from research_engine.models.research import SearchQuery
    claim = orch.repos.claims.get(args.claim_id)
    if claim is None:
        console.print("[red]Claim not found.[/red]")
        return
    core = " ".join(claim.text.split()[:10])
    queries = [f"{core} independent confirmation",
               f"{core} criticism limitations",
               f"{core} replication study"]
    created = []
    for qtext in queries:
        q = SearchQuery(project_id=orch.project.id, text=qtext,
                        reason=f"verification of {args.claim_id}",
                        kind="contradiction", priority=0.9,
                        expected_information_gain=0.85,
                        iteration=orch.project.current_iteration + 1)
        q.ensure_id()
        orch.repos.queries.save(q)
        created.append(q)
    console.print(f"[green]Verification branch queued for {args.claim_id}.[/green] "
                  f"Run 'research run {orch.project.id}' to execute:")
    for q in created:
        console.print(f"  + {q.text}")


def cmd_snapshot(args):
    _cfg, orch, _g = _load2(args)
    from research_engine.memory.snapshots import SnapshotManager
    sm = SnapshotManager(orch.ws)
    m = sm.create(orch.repos, orch.project.id, label=args.label or "")
    console.print(f"[green]{m.snapshot_id}[/green] at iteration {m.iteration}: {m.counts}")


def cmd_diff(args):
    _cfg, orch, _g = _load2(args)
    from research_engine.memory.snapshots import iteration_diff
    d = iteration_diff(orch.repos, orch.project.id,
                       max(1, orch.project.current_iteration - 1),
                       orch.project.current_iteration)
    console.print_json(json.dumps(d, default=str))


def cmd_replay(args):
    _cfg, orch, _g = _load2(args)
    events = orch.events.read_events()
    it = None
    for e in events:
        if e["event"] == "iteration_begin":
            it = e["metadata"].get("iteration")
            console.rule(f"[bold]Iteration {it}")
        elif it is not None and e["event"] in ("cycle_complete", "analysis_complete",
                                               "adaptive_plan", "followup_queries_generated"):
            meta = e.get("metadata", {})
            summary = ", ".join(f"{k}={v}" for k, v in list(meta.items())[:5])
            console.print(f"  {e['event']}: {summary}")


def cmd_focus_branch(args):
    _cfg, orch, _g = _load2(args)
    b = orch.repos.branches.get(args.branch_id)
    if b is None:
        console.print("[red]Branch not found.[/red]")
        return
    b.importance = min(1.0, b.importance + 0.3)
    b.priority = 1
    orch.repos.branches.save(b)
    console.print(f"[green]Boosted importance of '{b.question[:70]}' to {b.importance:.2f}. "
                  f"It will be prioritized next run.[/green]")


# ---------------------------------------------------------------------------
# Phase 3 commands
# ---------------------------------------------------------------------------

def _load3(args):
    cfg, orch, graph = _load2(args)
    from research_engine.storage.reasoning_repos import ReasoningRepos
    return cfg, orch, ReasoningRepos(orch.db)


def cmd_hypotheses(args):
    from research_engine.reasoning.hypothesis_engine import rank_hypotheses
    _cfg, orch, rrepos = _load3(args)
    ranked = rank_hypotheses(orch.repos, rrepos, orch.project.id,
                             objective=args.objective)
    if not ranked:
        console.print("No hypotheses yet.")
        return
    t = Table(title=f"Hypothesis Portfolio (objective={args.objective})")
    for col in ("rank", "id", "score", "conf", "status", "type", "title"):
        t.add_column(col)
    for i, r in enumerate(ranked[:20], 1):
        h = r["hypothesis"]
        t.add_row(str(i), h.id, f"{r['rank_score']:.3f}", f"{h.confidence:.2f}",
                  h.status, h.type[:8], h.title[:60])
    console.print(t)


def cmd_generate_hypotheses(args):
    _cfg, orch, rrepos = _load3(args)
    from research_engine.reasoning.pipeline import ReasoningPipeline
    pipe = ReasoningPipeline(orch.repos, rrepos, orch.router.reasoning, orch.registry)
    if orch.project.mode == "startup":
        try:
            from research_engine.storage.graph_store import GraphStore
            from research_engine.intelligence.startup import StartupIntelligence
            si = StartupIntelligence(orch.repos, GraphStore(orch.db))
            opps = si.discover_opportunities(orch.project.id)
            if not opps:
                console.print("No opportunity candidates found to derive hypotheses from.")
                return
            for opp in opps:
                res = pipe.run_business_hypotheses(orch.project.id, opp)
                for hh in res["hypotheses"]:
                    console.print(f"[cyan]{hh['id']}[/cyan] [{hh['type']}] {hh['title']}")
        except Exception as exc:
            console.print(f"[red]generation failed:[/red] {exc}")
        return
    summary = pipe.run_for_project(orch.project.id, mode=orch.project.mode,
                                   max_gaps=args.gaps)
    for r in summary["ranked"]:
        console.print(f"[cyan]{r['id']}[/cyan] score={r['score']:.3f} "
                      f"conf={r['confidence']:.2f} {r['title']}")


def cmd_show_hypothesis(args):
    _cfg, orch, rrepos = _load3(args)
    h = rrepos.hypotheses.get(args.hypothesis_id)
    if h is None:
        console.print("[red]Hypothesis not found.[/red]")
        return
    versions = rrepos.hypothesis_versions.history(orch.project.id, h.id)
    console.print(f"[bold]{h.id}[/bold] [{h.status}] v{h.version} type={h.type} "
                  f"origin={h.origin}:{','.join(h.origin_refs)}")
    console.print(f"  {h.statement}")
    if h.scores:
        console.print("  scores:", {k: round(v, 2) for k, v in h.scores.items()
                                    if isinstance(v, (int, float))})
    console.print(f"  supporting: {h.supporting_evidence[:8]}")
    console.print(f"  contradicting: {h.contradicting_evidence[:6]}")
    console.print(f"  assumptions: {h.assumptions[:6]}")
    console.print(f"  falsifiers: {h.falsification_conditions[:3]}")
    if versions:
        console.print(f"  history: {[(v.version, v.change_reason[:40]) for v in versions]}")


def cmd_critique_hypothesis(args):
    _cfg, orch, rrepos = _load3(args)
    from research_engine.reasoning.hypothesis_engine import HypothesisCritic
    critic = HypothesisCritic(orch.repos, rrepos, orch.router.reasoning)
    h = rrepos.hypotheses.get(args.hypothesis_id)
    if h is None:
        console.print("[red]Hypothesis not found.[/red]")
        return
    result = critic.critique(orch.project.id, h)
    console.print_json({"hypothesis_id": result["hypothesis_id"],
                        "revision_needed": result["revision_needed"],
                        "problems": result["problems"]})


def cmd_compare_hypotheses(args):
    _cfg, orch, rrepos = _load3(args)
    hyps = [rrepos.hypotheses.get(hid) for hid in args.hypothesis_ids]
    hyps = [h for h in hyps if h]
    if len(hyps) < 2:
        console.print("Need at least 2 hypothesis ids.")
        return
    a, b = hyps[0], hyps[1]
    sup_a, sup_b = set(a.supporting_evidence), set(b.supporting_evidence)
    console.print(f"[bold]{a.id} vs {b.id}[/bold]")
    console.print(f"A: {a.statement[:140]}")
    console.print(f"B: {b.statement[:140]}")
    console.print(f"\nEvidence favoring A only: {sorted(sup_a - sup_b)[:8]}")
    console.print(f"Evidence favoring B only: {sorted(sup_b - sup_a)[:8]}")
    shared = sorted(sup_a & sup_b)
    console.print(f"Evidence shared: {shared[:6]}")
    console.print("\nDiscriminating test needed: an observation that changes support "
                  "for exactly one — see each hypothesis's falsification conditions:")
    console.print(f"  A falsified by: {a.falsification_conditions[:2]}")
    console.print(f"  B falsified by: {b.falsification_conditions[:2]}")


def cmd_methodology(args):
    _cfg, orch, rrepos = _load3(args)
    from research_engine.reasoning.methodology_designer import (MethodologyDesigner,
                                                                MethodologyCritic)
    h = rrepos.hypotheses.get(args.hypothesis_id)
    if h is None:
        console.print("[red]Hypothesis not found.[/red]")
        return
    designer = MethodologyDesigner(orch.repos, rrepos, orch.router.reasoning)
    meths = designer.design(orch.project.id, h)
    critic = MethodologyCritic()
    for m in meths:
        v = critic.inspect(orch.project.id, m, h)
        console.print(f"\n[bold]{m.tier}[/bold] ({m.experiment_kind}) — critic: {v['verdict']}")
        console.print(f"  objective: {m.objective[:110]}")
        console.print(f"  indep={m.independent_vars[:1]} dep={m.dependent_vars[:1]}")
        console.print(f"  baselines: {[b.get('tier') for b in m.baselines]}")
        console.print(f"  success: {m.success_condition[:100]}")
        if v["problems"]:
            console.print(f"  [yellow]problems:[/yellow] {[p['type'] for p in v['problems']]}")


def cmd_experiments(args):
    _cfg, orch, rrepos = _load3(args)
    exps = rrepos.experiments.all(orch.project.id, "hypothesis_id=?", (args.hypothesis_id,))
    if not exps:
        console.print("No experiments for this hypothesis.")
        return
    for x in exps:
        gate = " [AWAITING APPROVAL]" if x.awaiting_approval else ""
        console.print(f"[cyan]{x.id}[/cyan] [{x.status}] {x.risk_level}{gate}\n  {x.title}\n"
                      f"  {x.decision_note[:150]}")


def cmd_approve_experiment(args):
    _cfg, orch, rrepos = _load3(args)
    from research_engine.reasoning.result_ingestion import approve_experiment
    try:
        x = approve_experiment(rrepos, orch.project.id, args.experiment_id,
                               approved=not args.reject, note=args.note or "")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    console.print(f"{x.id} -> [bold]{x.status}[/bold]")


def cmd_add_result(args):
    _cfg, orch, rrepos = _load3(args)
    from research_engine.reasoning.result_ingestion import ResultIngestor
    print("Enter observations one per line; empty line to finish:")
    observations = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        observations.append(line)
    metrics_raw = input("Metrics as JSON (optional, enter to skip): ").strip()
    metrics = {}
    if metrics_raw:
        try:
            metrics = json.loads(metrics_raw)
        except json.JSONDecodeError:
            console.print("[yellow]metrics ignored (invalid JSON)[/yellow]")
    hint = input("Interpretation hint (supports/contradicts/inconclusive, optional): ").strip()
    try:
        res = ResultIngestor(orch.repos, rrepos).ingest(
            orch.project.id, args.experiment_id, observations, metrics,
            interpretation_hint=hint)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    console.print_json(res)


def cmd_assumptions(args):
    _cfg, orch, rrepos = _load3(args)
    asm = sorted(rrepos.assumptions.all(orch.project.id), key=lambda a: -a.priority)
    if not asm:
        console.print("No tracked assumptions.")
        return
    t = Table(title="Assumptions (priority-ordered)")
    for col in ("id", "kind", "priority", "status", "statement"):
        t.add_column(col)
    for a in asm[:25]:
        t.add_row(a.id, a.kind, f"{a.priority:.2f}", a.status, a.statement[:80])
    console.print(t)


def cmd_next_action(args):
    _cfg, orch, rrepos = _load3(args)
    from research_engine.reasoning.decision_layer import DecisionLayer
    dl = DecisionLayer(orch.repos, rrepos)
    nx = dl.recommend_next(orch.project.id, objective=args.objective)
    console.print(f"[bold]Headline:[/bold] {nx['headline']}")
    for a in nx["actions"]:
        console.print(f"- [cyan]{a['action']}[/cyan] → {a['target_id']} "
                      f"(gain {a['expected_information_gain']:.2f}, cost {a['cost']})")
        console.print(f"    {a['reason'][:150]}")
    dr = dl.decision_readiness(orch.project.id)
    console.print(f"\nDecision readiness: [bold]{dr['level']}[/bold] ({dr['score']})")
    if dr["research_debt"]:
        console.print("Research debt:")
        for d in dr["research_debt"]:
            console.print(f"  - {d}")


def cmd_trace_hypothesis(args):
    _cfg, orch, rrepos = _load3(args)
    h = rrepos.hypotheses.get(args.hypothesis_id)
    if h is None:
        console.print("[red]Hypothesis not found.[/red]")
        return
    all_ev = {e.id: e for e in orch.repos.evidence.all(orch.project.id)}
    chain = {"hypothesis": h.model_dump(), "trace": []}
    for eid in list(dict.fromkeys(h.supporting_evidence + h.contradicting_evidence)):
        ev = all_ev.get(eid)
        if ev is None:
            continue
        src = orch.repos.sources.get(ev.source_id)
        chain["trace"].append({
            "evidence": eid, "stance": ("supports" if eid in h.supporting_evidence
                                        else "contradicts"),
            "claim": ev.claim_text[:120], "source": src.title[:60] if src else "",
            "url": ev.source_url, "tier": ev.source_tier})
    alternatives = [x.id for x in rrepos.hypotheses.all(orch.project.id)
                    if x.alternative_of == h.alternative_of and x.id != h.id]
    chain["alternative_hypotheses"] = alternatives
    console.print_json(json.dumps(chain, default=str))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="research", description="GAR local research engine")
    parser.add_argument("--config", help="path to gar.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create and run a new research project")
    p.add_argument("question")
    p.add_argument("--mode", default=None, choices=["academic", "startup"])
    p.add_argument("--no-run", action="store_true", help="only create the project")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("run", help="run/resume a project to completion")
    p.add_argument("project_id")
    p.add_argument("--iterations", type=int, default=None)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("status", help="show project status dashboard")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("pause", help="request a cooperative pause")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_pause)

    p = sub.add_parser("resume", help="resume a paused project")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("inspect", help="inspect problem/plan/claims")
    p.add_argument("project_id")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("report", help="(re)generate markdown reports")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("gaps", help="list open gaps")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_gaps)

    p = sub.add_parser("sources", help="list sources with tiers/status")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_sources)

    p = sub.add_parser("evidence", help="search/list stored evidence")
    p.add_argument("project_id")
    p.add_argument("--search", default="", help="FTS query over claims+quotes")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_evidence)

    # --- Phase 2 ---
    p = sub.add_parser("map", help="literature map (academic) or market map (startup)")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_map)

    p = sub.add_parser("branches", help="branch list with coverage scores")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_branches)

    p = sub.add_parser("papers", help="paper entities in the research graph")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_papers)

    p = sub.add_parser("competitors", help="competitors/pains/prices/signals (startup)")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_competitors)

    p = sub.add_parser("opportunities", help="discover + score startup opportunities")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_opportunities)

    p = sub.add_parser("ask", help="grounded Q&A over the project archive")
    p.add_argument("project_id")
    p.add_argument("question")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("trace-claim", help="claim -> evidence -> source chain")
    p.add_argument("project_id")
    p.add_argument("claim_id")
    p.set_defaults(fn=cmd_trace_claim)

    p = sub.add_parser("verify", help="queue a focused verification branch for a claim")
    p.add_argument("project_id")
    p.add_argument("claim_id")
    p.set_defaults(fn=cmd_verify_claim)

    p = sub.add_parser("snapshot", help="create a research snapshot")
    p.add_argument("project_id")
    p.add_argument("--label", default="")
    p.set_defaults(fn=cmd_snapshot)

    p = sub.add_parser("diff", help="diff between last two iterations")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("replay", help="replay the research process iteration by iteration")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("focus", help="boost a branch's priority for the next run")
    p.add_argument("project_id")
    p.add_argument("branch_id")
    p.set_defaults(fn=cmd_focus_branch)

    # --- Phase 3 ---
    p = sub.add_parser("hypotheses", help="ranked hypothesis portfolio")
    p.add_argument("project_id")
    p.add_argument("--objective", default="balanced",
                   choices=["balanced", "novelty", "feasibility", "impact"])
    p.set_defaults(fn=cmd_hypotheses)

    p = sub.add_parser("generate-hypotheses", help="generate hypotheses from gaps/contradictions/opportunities")
    p.add_argument("project_id")
    p.add_argument("--gaps", type=int, default=2)
    p.set_defaults(fn=cmd_generate_hypotheses)

    p = sub.add_parser("hypothesis", help="show one hypothesis with full traceability")
    p.add_argument("project_id")
    p.add_argument("hypothesis_id")
    p.set_defaults(fn=cmd_show_hypothesis)

    p = sub.add_parser("critique-hypothesis", help="run the structured hypothesis critic")
    p.add_argument("project_id")
    p.add_argument("hypothesis_id")
    p.set_defaults(fn=cmd_critique_hypothesis)

    p = sub.add_parser("compare-hypotheses", help="head-to-head comparison of 2 hypotheses")
    p.add_argument("project_id")
    p.add_argument("hypothesis_ids", nargs=2)
    p.set_defaults(fn=cmd_compare_hypotheses)

    p = sub.add_parser("methodology", help="design + compare methodologies for a hypothesis")
    p.add_argument("project_id")
    p.add_argument("hypothesis_id")
    p.set_defaults(fn=cmd_methodology)

    p = sub.add_parser("experiments", help="experiments for a hypothesis")
    p.add_argument("project_id")
    p.add_argument("hypothesis_id")
    p.set_defaults(fn=cmd_experiments)

    p = sub.add_parser("approve", help="approve/reject an experiment at the human gate")
    p.add_argument("project_id")
    p.add_argument("experiment_id")
    p.add_argument("--reject", action="store_true")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_approve_experiment)

    p = sub.add_parser("add-result", help="ingest experiment results manually")
    p.add_argument("project_id")
    p.add_argument("experiment_id")
    p.set_defaults(fn=cmd_add_result)

    p = sub.add_parser("assumptions", help="assumption register (priority-ordered)")
    p.add_argument("project_id")
    p.set_defaults(fn=cmd_assumptions)

    p = sub.add_parser("next", help="'what should I do next?' engine + decision readiness")
    p.add_argument("project_id")
    p.add_argument("--objective", default="balanced",
                   choices=["balanced", "novelty", "feasibility", "impact"])
    p.set_defaults(fn=cmd_next_action)

    p = sub.add_parser("trace-hypothesis", help="hypothesis -> evidence -> source chain")
    p.add_argument("project_id")
    p.add_argument("hypothesis_id")
    p.set_defaults(fn=cmd_trace_hypothesis)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()


app = main  # entry point alias
