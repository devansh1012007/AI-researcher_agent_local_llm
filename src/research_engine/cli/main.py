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

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()


app = main  # entry point alias
