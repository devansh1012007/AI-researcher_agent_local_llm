"""GAR CLI — research command.

Commands: new, run, status, pause, resume, inspect, report, gaps, sources, queries, evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import pathlib

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
    # P0-11: cooperative pause via the canonical service (no direct
    # state-machine mutation from the interface layer)
    ctx = _ctx4()
    pid = args.project_id
    stopped = ProjectService(ctx).pause(pid)
    console.print(f"[yellow]Paused.[/yellow] "
                  f"{'running job signalled' if stopped else 'no active job'}; "
                  f"resume with: research resume {pid}")


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
        # P0-12: canonical engine only — legacy StartupIntelligence
        # discovery/scoring retired from all production paths.
        from research_engine.specialists.startup.cli_glue import market_map_view
        view = market_map_view(_svc4(), p.id)
        console.print(f"[bold]Market map[/bold] ({p.id}):")
        for kind, n in view.get("extraction_counts", {}).items():
            console.print(f"  {kind}: {n}")
        for t in view.get("opportunities", []):
            console.print(f"\n[cyan]{t['opportunity_id']}[/cyan] "
                          f"score={t['total_score']} [{t['priority']}]")
            console.print(f"  problem: {t['problem'][:110]}")
        for gap in view.get("open_questions", [])[:5]:
            console.print(f"  open: {gap[:100]}")
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
    # P0-12: canonical specialist engine (legacy discover/score retired)
    from research_engine.specialists.startup.cli_glue import opportunity_portfolio
    _cfg, orch, _graph = _load2(args)
    portfolio = opportunity_portfolio(_svc4(), orch.project.id)
    if not portfolio:
        console.print("No opportunities discovered from current evidence.")
        return
    for t in portfolio:
        console.print(f"\n[bold cyan]{t['opportunity_id']}[/bold cyan] "
                      f"score={t['total_score']} [{t['priority']}]")
        console.print(f"  problem: {t['problem'][:130]}")


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
        # P0-12: canonical specialist path (legacy discovery retired here)
        from research_engine.specialists.startup.cli_glue import (
            ensure_business_hypotheses)
        try:
            n = ensure_business_hypotheses(_svc4(), orch.project.id)
            if n == 0:
                console.print("No NEW business hypotheses created "
                              "(already exist or no opportunities).")
                return
            console.print(f"created {n} business hypotheses")
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



# ------------------------------------------------------------------ Phase 4
def _ctx4(args=None):
    from research_engine.services.context import get_context
    return get_context()


# ---------------------------------------------------------------------------
# Phase 5: startup specialist commands (spec #76)
# ---------------------------------------------------------------------------

def _svc4():
    """StartupResearchService wired to CLI context."""
    from research_engine.specialists.startup.service import StartupResearchService
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    return StartupResearchService(cfg=cfg, data_dir=cfg.storage.data_dir)


def _latest_startup_project(explicit=""):
    if explicit:
        return explicit
    from research_engine.services.research_service import ProjectService
    projects = ProjectService(_ctx4()).list_projects()
    startup = [p for p in projects if p.get("mode") == "startup"]
    if not startup:
        raise SystemExit("no startup projects found; run: research new --mode startup \"<question>\"")
    return sorted(startup, key=lambda p: p.get("created_at", ""), reverse=True)[0]["id"]


def cmd_startup_discover(args):
    """Create (or reuse) a startup project for the market, then discover."""
    svc = _svc4()
    if args.project:
        pid = args.project
    else:
        ctx = _ctx4()
        from research_engine.services.research_service import ProjectCreate, ProjectService
        ps = ProjectService(ctx)
        existing = [p for p in ps.list_projects()
                    if p.get("question_raw", "").strip().lower() ==
                    args.market.strip().lower() and p.get("mode") == "startup"]
        if existing:
            pid = sorted(existing, key=lambda p: p["created_at"], reverse=True)[0]["id"]
            console.print(f"[dim]reusing[/dim] {pid}")
        else:
            created = ps.create(ProjectCreate(question=args.market, mode="startup"))
            pid = created["id"]
            console.print(f"created [bold cyan]{pid}[/bold cyan] — running retrieval "
                          "first is recommended; discovering on current evidence…")
    result = svc.run_mode(pid, "OPPORTUNITY_DISCOVERY")
    console.print(f"\n[bold]{result['count']} opportunities "
                  f"(patterns: {', '.join(result['patterns_seen']) or 'none'})[/bold]")
    for t in result["opportunities"]:
        console.print(f"\n[bold cyan]{t['opportunity_id']}[/bold cyan] "
                      f"score={t['total_score']} [{t['priority']}] — {t['portfolio_slot']}")
        console.print(f"  {t['problem'][:130]}")


def cmd_startup_research(args):
    """Full specialist pipeline over a market question (deep run)."""
    svc = _svc4()
    pid = args.project
    if not pid:
        ctx = _ctx4()
        from research_engine.services.research_service import ProjectCreate, ProjectService
        created = ProjectService(ctx).create(
            ProjectCreate(question=args.market, mode="startup"))
        pid = created["id"]
        console.print(f"created [bold cyan]{pid}[/bold cyan]")
        if not args.no_run:
            console.print("running live research first (network)…")
            try:
                orch = Orchestrator.load(svc.cfg, pid)
                orch.run()
            except Exception as exc:
                console.print(f"[yellow]live run failed ({exc}); "
                              "continuing with current evidence[/yellow]")
    result = svc.run_full_pipeline(pid)
    disc = result["discovery"]
    val = result["validation"]
    dil = result["diligence"]
    console.print(f"\n[bold]Discovery:[/bold] {disc.get('count', 0)} gated opportunities")
    console.print(f"[bold]Validation:[/bold] "
                  f"{val.get('business_hypotheses_created', 0)} hypotheses, "
                  f"{sum(len(p.get('tests_designed', [])) for p in val.get('plans', []))} tests")
    console.print(f"[bold]Diligence:[/bold] readiness="
                  f"{dil.get('readiness', {}).get('level')}, decision="
                  f"{dil.get('recommendation', {}).get('decision')}")
    console.print(f"\nNext: research report {pid}")


def cmd_startup_customer(args):
    pid = _latest_startup_project(args.project)
    result = _svc4().run_mode(pid, "CUSTOMER_RESEARCH", segment=args.segment)
    console.print(f"[bold]Customer research — {pid}[/bold]")
    for s in result["segments"]:
        console.print(f"\n[bold]{s['name']}[/bold] "
                      f"({len(s['evidence_ids'])} evidences; buyer={s.get('buyer') or 'unknown'})")
        for claim in s.get("pain_claims", [])[:2]:
            console.print(f"  · {claim[:110]}")
    console.print("\n[bold]Personas[/bold]")
    for p in result["personas"]:
        flag = "[yellow]SPECULATIVE[/yellow] " if p["speculative"] else ""
        console.print(f"- {flag}{p['role']} | authority: {p['decision_authority'][:60]} "
                      f"| tools: {', '.join(p['tools'][:4])}")
    console.print("\n[bold]Pain ranking (behavioral hierarchy)[/bold]")
    for pain in result["pain_points_ranked"][:6]:
        console.print(f"- [{pain['evidence_class']}] {pain['statement'][:100]}")
    wf = result.get("workflow_map") or {}
    if wf.get("steps"):
        console.print(f"\n[bold]Workflow around '{wf['topic']}'[/bold]")
        for i, stp in enumerate(wf["steps"][:6], 1):
            console.print(f"  {i}. {stp[:110]}")
        for kind, hits in (wf.get("friction_points") or {}).items():
            console.print(f"  friction[{kind}]: {hits[0][:90] if hits else ''}")


def cmd_startup_competitors(args):
    pid = _latest_startup_project(args.project)
    result = _svc4().run_mode(pid, "COMPETITOR_RESEARCH")
    ax = result["landscape_axes"]
    console.print(f"[bold]Competitor landscape — {pid}[/bold]\n"
                  f"axes: {ax['x_axis']} × {ax['y_axis']}\n")
    for pr in result["profiles"]:
        console.print(f"\n[bold cyan]{pr['name']}[/bold cyan] ({pr['classification']}) "
                      f"model={pr['business_model'] or '?'} pricing={pr['pricing_summary'] or '?'}")
        if pr["channels"]:
            ev = ", ".join(f"{c}:{pr['channel_evidence'].get(c, '?')}"
                           for c in pr["channels"][:4])
            console.print(f"  channels: {ev}")
        for wk in pr["weaknesses"][:2]:
            console.print(f"  weakness: {wk[:110]}")
        if pr["traction_note"]:
            console.print(f"  traction: {pr['traction_note']}")
    console.print("\n[bold]Pricing plans (raw preserved)[/bold]")
    for pl in result["pricing_plans"]:
        console.print(f"- {pl['company'] or '?'} `{pl['raw']}` [{pl['period']}] "
                      f"({pl['note']})")
    gaps = result.get("gaps_detected") or []
    if gaps:
        console.print("\n[bold]Gaps detected[/bold]")
        for g in gaps:
            console.print(f"- [{g['kind']}] {g['target']}: {g['reason'][:110]}")
    dd = result.get("distribution_difficulty") or {}
    console.print(f"\nDistribution verdict: [bold]{dd.get('verdict')}[/bold]")


def cmd_startup_opportunity(args):
    """Due diligence on one opportunity (or the top-ranked)."""
    pid = _latest_startup_project(args.project)
    result = _svc4().run_mode(pid, "OPPORTUNITY_DUE_DILIGENCE",
                              opportunity_id=args.opportunity_id)
    if result.get("verdict"):
        console.print(result["verdict"])
        return
    sb = result["rubric"]
    console.print(f"[bold]Due diligence — {result['opportunity_id']}[/bold]\n")
    for dim, w in sb.get("weights", {}).items():
        console.print(f"- {dim}: {sb['labels'].get(dim)} ({sb['factors'].get(dim)}) "
                      f"— {sb['reasons'].get(dim, '')[:90]}")
    rd = result["readiness"]
    console.print(f"\nReadiness: [bold]{rd['level']}[/bold] "
                  f"(coverage {rd['coverage']['covered']}/{rd['coverage']['total']}, "
                  f"untested critical assumptions: {rd['critical_assumptions_untested']})")
    rec = result["recommendation"]
    console.print(f"\n[bold]{rec['decision'].upper()}[/bold] — {rec['recommendation_text']}")
    console.print(f"for:     {rec['evidence_supporting'][:120]}")
    console.print(f"against: {rec['evidence_against'][:120]}")
    console.print(f"next:    {rec['best_next_action']}")
    console.print(f"changes if: {rec['what_would_change_this_recommendation'][:140]}")


def cmd_startup_validate(args):
    pid = _latest_startup_project(args.project)
    result = _svc4().run_mode(pid, "VALIDATION_PLANNING",
                              opportunity_id=args.opportunity_id)
    plans = result.get("plans") or []
    if not plans:
        console.print(result.get("note", "nothing to validate"))
        return
    for pl in plans:
        console.print(f"\n[bold]{pl['hypotheses_covered']} hypotheses, "
                      f"{pl['assumptions_created']} assumptions, "
                      f"{len(pl['tests_designed'])} tests[/bold] "
                      f"({pl['opportunity_id']})")
        for t in pl["tests_designed"][:8]:
            console.print(f"  [{t['test_type']}|cost={t['cost']}|gain={t['expected_information_gain']}] "
                          f"{t['title'][:95]} ({t['critic_verdict']})")
        for st in pl["staged_sequence"]:
            console.print(f"\n  gate: {st['stage']}\n    {st['gate_rule'][:110]}")
        unc = pl.get("biggest_behavioral_uncertainty")
        if unc:
            console.print(f"\n  [yellow]biggest uncertainty: {unc} — "
                          "internet research cannot resolve this; validate in the field[/yellow]")


def cmd_startup_compare(args):
    pid = _latest_startup_project(args.project)
    result = _svc4().run_mode(pid, "STARTUP_COMPARISON")
    comp = result.get("comparison") or {}
    matrix = comp.get("matrix", {})
    if not matrix:
        console.print(result.get("note"))
        return
    dims = ["pain_severity", "market_size", "competition_weakness",
            "distribution", "timing", "evidence_strength", "total"]
    header = f"{'opportunity':<42}" + "".join(f"{d[:12]:>14}" for d in dims)
    console.print(header)
    console.print("-" * len(header))
    for oid, row in matrix.items():
        cells = "".join(f"{row.get(d, 0):>14.3f}" for d in dims)
        console.print(f"{row['name'][:40]:<42}{cells}")
    console.print(f"\nleader by rubric: {comp.get('leader_by_rubric', '')}")
    console.print(comp.get("tradeoffs_note", ""))


def cmd_startup_assumptions(args):
    pid = _latest_startup_project(args.project)
    rows = _svc4().assumption_register(pid, args.opportunity_id)
    if not rows:
        console.print("no assumptions registered; run: research startup validate")
        return
    console.print("[bold]Assumption register (priority-ordered)[/bold]")
    for a in rows:
        console.print(f"\n- [{a['kind']}|{a['category']}|{a['status']}] "
                      f"{a['statement'][:130]}")
        console.print(f"  priority={a['priority']:.2f} "
                      f"(imp={a['importance']} unc={a['uncertainty']} "
                      f"impact={a['impact_of_failure']} ease={a['ease_of_testing']})")


def cmd_startup_next(args):
    """Highest-leverage next action for an opportunity (spec #68/#70)."""
    pid = _latest_startup_project(args.project)
    svc = _svc4()
    dil = svc.run_mode(pid, "OPPORTUNITY_DUE_DILIGENCE",
                       opportunity_id=args.opportunity_id)
    rec = dil.get("recommendation") or {}
    try:
        view = svc.recommendation_view(pid, args.opportunity_id)
        rec = view.get("recommendation", rec)
        eff = view.get("efficiency")
    except Exception:
        pass
    console.print(f"[bold]Recommendation:[/bold] {rec.get('decision')} — "
                  f"{rec.get('recommendation_text', '')}")
    console.print(f"[bold]Critical uncertainty:[/bold] {rec.get('critical_uncertainty')}")
    console.print(f"[bold]Best next action:[/bold] {rec.get('best_next_action')}")
    console.print(f"[bold]Changes if:[/bold] {rec.get('what_would_change_this_recommendation')}")
    if eff and eff.get("new_evidence_per_query") is not None:
        console.print(f"[dim]research efficiency: {eff['new_evidence_per_query']} "
                      f"new evidence/query → {eff['verdict']}[/dim]")


def cmd_jobs(args):
    from research_engine.models.job import TERMINAL_STATUSES
    ctx = _ctx4()
    rows = ctx.platform_db.list_jobs(status=args.status or "",
                                     project_id=args.project or "")
    if not rows:
        console.print("[dim]no jobs[/dim]")
        return
    t = Table(title="Research Jobs")
    for col in ("JOB", "TYPE", "STATUS", "PRI", "PROJECT", "PROGRESS", "CREATED"):
        t.add_column(col)
    for j in rows:
        prog = j.progress if isinstance(j.progress, dict) else {}
        t.add_row(j.id, j.type, _status_color(j.status), str(j.priority),
                  (j.project_id or "")[:24],
                  f"done={prog.get('done', 0)} q={prog.get('queued', 0)}",
                  j.created_at.strftime("%m-%d %H:%M"))
    console.print(t)


def _status_color(st: str) -> str:
    colors = {"RUNNING": "cyan", "COMPLETED": "green", "FAILED": "red",
              "FAILED_PARTIAL": "yellow", "PAUSED": "magenta",
              "CANCELLED": "dim", "QUEUED": "white"}
    c = colors.get(st, "white")
    return f"[{c}]{st}[/{c}]"


def cmd_specialists(args):
    """Phase 5 §71: specialist ecosystem visibility."""
    from research_engine.specialists.bootstrap import ensure_builtin_specialists
    from research_engine.specialists.runtime import get_registry
    ensure_builtin_specialists()
    reg = get_registry()
    if getattr(args, "sid", None):
        r = reg.lookup(args.sid)
        if r is None:
            console.print(f"[red]unknown specialist: {args.sid}[/red]")
            return
        d = r.descriptor
        console.print_json(json.dumps({
            "specialist_id": d.specialist_id, "name": d.name,
            "version": d.version, "description": d.description,
            "modes": d.supported_modes, "skills": d.skills,
            "entity_types": d.entity_types,
            "permissions": sorted(p.value for p in d.permissions),
            "budgets": d.budgets.model_dump(),
            "lifecycle": r.lifecycle.value,
            "health": {"state": r.health.state.value,
                       "reason": r.health.reason},
        }, default=str))
        return

    rows = []
    for r in reg.list_active():
        d = r.descriptor
        perf = _ctx4().platform_db.list_specialist_perf(d.specialist_id)
        runs = sum(p["runs"] for p in perf)
        fails = sum(p["failures"] for p in perf)
        rows.append((d.specialist_id, d.version, ",".join(
            d.supported_modes[:3]), r.lifecycle.value,
            f"{runs - fails}/{runs}"))
    t = Table(title="Specialists")
    for col in ("ID", "VER", "MODES", "LIFECYCLE", "OK/RUNS"):
        t.add_column(col)
    for row in rows:
        t.add_row(*[str(x) for x in row])
    console.print(t)


def cmd_research_specialists(args):
    """Which specialists ran on this project, why, and what came back."""
    ctx = _ctx4()
    inv = ctx.platform_db.list_specialist_invocations(args.project_id)
    if not inv:
        console.print("[dim]no specialist invocations[/dim]")
        return
    t = Table(title="Specialist invocations")
    for col in ("SPECIALIST", "STATUS", "EVIDENCE@START", "WHEN"):
        t.add_column(col)
    for i in inv:
        t.add_row(str(i.get("specialist_id")), str(i.get("status")),
                  str(i.get("evidence_count")), str(i.get("created_at")))
    console.print(t)


# ------------------------- Phase 6: process intelligence commands ---------
def _qs(args=None):
    from research_engine.services.quality_service import quality_service
    return quality_service(_ctx4(args))


def cmd_quality(args):
    """Research-process quality dashboard (§86)."""
    from rich.json import JSON
    qs = _qs(args)
    d = qs.dashboard(getattr(args, "project_id", ""))
    out = d["outcomes_summary"]
    console.print(f"[b]Outcomes[/b] runs={out['runs']} "
                  f"avg_gain={out['avg_gain']} "
                  f"avg_grounded={out['avg_grounded_ratio']}")
    t = Table(title="Specialist performance")
    for col in ("SPECIALIST", "VER", "TASK_TYPE", "RUNS", "FAIL%", "LAT(s)"):
        t.add_column(col)
    for s in d["specialists"]:
        t.add_row(s["specialist"], s["version"], s["task_type"],
                  str(s["runs"]),
                  f"{s['failure_rate']:.0%}" if s["failure_rate"]
                  is not None else "-",
                  str(s["avg_latency_s"]))
    console.print(t)
    mt = Table(title="Model performance")
    for col in ("PROVIDER/MODEL", "ROLE", "CALLS", "FAIL%", "SCHEMA", "Q/S",
                "VERDICT"):
        mt.add_column(col)
    for m in d["models"]:
        mt.add_row(f"{m['provider']}/{m['model']}", m["role"], str(m["calls"]),
                   f"{m['failure_rate']:.0%}",
                   f"{m['schema_reliability']:.0%}",
                   str(m["quality_per_second"]), m["verdict"])
    console.print(mt)
    qf = Table(title="Query family utility")
    for col in ("FAMILY", "TASK_TYPE", "QUERIES", "AVG UTILITY"):
        qf.add_column(col)
    for r in d["query_families"][:10]:
        qf.add_row(r["family"], r["task_type"], str(r["queries"]),
                   str(r["avg_utility"]))
    console.print(qf)
    div = d["diversity"]
    flags = [k for k, v in div.items() if v.get("concentration_flag")
             or v.get("confirmation_loop_flag")]
    if flags:
        console.print(f"[yellow]concentration flags:[/yellow] {', '.join(flags)}")
    drift = d["policy_drift"]
    if drift.get("status") == "ok" and drift.get("significant_shifts"):
        console.print(f"[yellow]policy drift shifts:[/yellow] "
                      f"{drift['significant_shifts']}")
    if getattr(args, "json", False):
        console.print(JSON.from_data(d))


def cmd_policy(args):
    """Policy registry control (§52-§55): list/show/propose/evaluate/
    activate/rollback/deactivate/compare. Activation is ALWAYS explicit."""
    import json as _json
    qs = _qs(args)
    a = args
    if a.action == "list":
        rows = qs.list_policies(a.kind or "")
        t = Table(title="Policies")
        for col in ("KIND", "VERSION", "STATUS", "ACTIVATED", "REASON"):
            t.add_column(col)
        for prow in rows:
            t.add_row(prow["kind"], prow["version"], prow["status"],
                      prow.get("activated_at") or "-",
                      (prow.get("activated_reason") or "")[:40])
        console.print(t)
        return
    if a.action == "show":
        pol = _ctx4().platform_db.get_policy(a.kind, a.version)
        if pol is None:
            console.print(f"[red]unknown policy {a.kind}@{a.version}[/red]")
            raise SystemExit(1)
        console.print(JSON.from_data(pol))
        return
    if a.action == "propose":
        body = _json.loads(a.body or "{}")
        ev = _json.loads(a.evaluation) if a.evaluation else None
        out = qs.propose_policy(a.kind, a.version, body, evaluation=ev)
        console.print(out)
        return
    if a.action == "evaluate":
        out = qs.record_evaluation(a.kind, a.version,
                                   _json.loads(a.evaluation))
        console.print(out)
        return
    if a.action == "activate":
        out = qs.activate_policy(a.kind, a.version,
                                 reason=a.reason or "manual activation")
        console.print({"activated": out})
        return
    if a.action == "rollback":
        out = qs.rollback_policy(a.kind, reason=a.reason or "manual rollback")
        console.print(out)
        return
    if a.action == "deactivate":
        ok = _qs(args).registry.deactivate(a.kind, reason=a.reason or "")
        console.print({"deactivated": ok})
        return
    if a.action == "compare":
        console.print(JSON.from_data(
            qs.compare_policies(a.kind, a.version_a, a.version_b)))
        return


def cmd_feedback(args):
    """Submit/list explicit user feedback (§85). Stored separately from
    objective metrics; never auto-applied to policy weights."""
    qs = _qs(args)
    if args.verdict:
        out = qs.submit_feedback(args.project_id, args.target_kind,
                                 args.target_id, args.verdict,
                                 note=args.note or "")
        console.print(out)
        return
    rows = qs.list_feedback(args.project_id)
    if not rows:
        console.print("[dim]no feedback recorded[/dim]")
        return
    t = Table(title="User feedback")
    for col in ("ID", "TARGET", "VERDICT", "NOTE", "WHEN"):
        t.add_column(col)
    for r in rows:
        t.add_row(r["feedback_id"], f"{r['target_kind']}:{r['target_id']}",
                  r["verdict"], (r["note"] or "")[:40], r["created_at"])
    console.print(t)


def cmd_decisions(args):
    """Inspectable adaptive decisions (§56-§58): why was X chosen?"""
    qs = _qs(args)
    rows = qs.decisions(args.project_id, kind=args.kind or "")
    if not rows:
        console.print("[dim]no adaptive decisions recorded[/dim]")
        return
    t = Table(title="Adaptive decisions")
    for col in ("KIND", "CHOSEN", "ALTERNATIVES", "POLICY", "EXPECTED",
                "ACTUAL", "WHY"):
        t.add_column(col)
    for drow in rows:
        t.add_row(drow["kind"], drow["chosen"],
                  ",".join(drow["alternatives"])[:24],
                  drow["policy_version"],
                  str(drow["expected_gain"]) if drow["expected_gain"]
                  is not None else "-",
                  str(drow["actual_gain"]) if drow["actual_gain"]
                  is not None else "-",
                  drow["reason"][:48])
    console.print(t)


def cmd_alerts(args):
    """Ranked research alerts (§83/§84)."""
    qs = _qs(args)
    if args.ack:
        console.print({"acknowledged": qs.acknowledge_alert(args.ack)})
        return
    rows = sorted(qs.alerts(args.project_id, status=args.status),
                  key=lambda x: -float(x.get("score") or 0))
    if not rows:
        console.print("[dim]no alerts[/dim]")
        return
    t = Table(title="Research alerts")
    for col in ("SCORE", "KIND", "SEVERITY", "STATUS", "ID"):
        t.add_column(col)
    for al in rows:
        t.add_row(str(al["score"]), al["kind"], al["severity"],
                  al["status"], al["alert_id"])
    console.print(t)


def cmd_review(args):
    """Run the independent critic over a project's current state (§42-§45).
    Produces review findings only — it never modifies research."""
    llm = None
    if args.level == "HIGH_RIGOR" and not args.no_llm:
        try:
            from research_engine.core.orchestrator import Orchestrator
            orch = Orchestrator.load(_ctx4().cfg, args.project_id)
            llm = orch.router.reasoning
        except Exception:
            llm = None
    rev = _qs(args).review(args.project_id, level=args.level, llm=llm)
    from rich.json import JSON
    console.print(JSON.from_data(rev))


def cmd_outcome(args):
    """Show stored research-outcome records (§6)."""
    from rich.json import JSON
    rows = _qs(args).outcomes(args.project_id, limit=args.limit)
    if not rows:
        console.print("[dim]no outcomes recorded[/dim]")
        return
    if args.outcome_id:
        row = next((r for r in rows if r["outcome_id"] == args.outcome_id),
                   None)
        if row is None:
            console.print("[red]unknown outcome id[/red]")
            raise SystemExit(1)
        console.print(JSON.from_data(row))
        return
    t = Table(title="Research outcomes")
    for col in ("OUTCOME", "TYPE", "FINGERPRINT", "GAIN v2", "NEXT ACTION",
                "WHEN"):
        t.add_column(col)
    for r in rows:
        dd = r["data"]
        t.add_row(r["outcome_id"], r["research_type"],
                  r["fingerprint"][:10],
                  str(dd.get("research_gain", {}).get("research_gain_v2")),
                  dd.get("final_decision", {}).get("next_action", "-"),
                  r["created_at"][:19])
    console.print(t)


def cmd_cross_domain(args):
    """Read-only cross-domain synthesis view (§70)."""
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.specialists.synthesis import synthesize
    orch = Orchestrator.load(_ctx4().cfg, args.project_id)
    console.print_json(json.dumps(synthesize(orch), default=str))


def cmd_job(args):
    ctx = _ctx4()
    j = ctx.platform_db.get_job(args.job_id)
    if j is None:
        console.print(f"[red]job not found: {args.job_id}[/red]")
        return
    console.print_json(json.dumps(json.loads(j.model_dump_json()), default=str))
    tasks = ctx.platform_db.tasks_for_job(j.id)
    if tasks:
        t = Table(title="Tasks")
        for col in ("TASK", "TYPE", "STATUS", "ATT", "PROFILE", "ERROR CAT"):
            t.add_column(col)
        for tk in tasks:
            t.add_row(tk.id, tk.type, tk.status, f"{tk.attempts}/{tk.max_attempts}",
                      tk.resource_profile, tk.error_category or "-")
        console.print(t)


def cmd_job_control(args):
    ctx = _ctx4()
    action, ident = args.action, args.id
    sched = ctx.scheduler
    ok = None
    if action == "pause":
        ok = sched.pause_job(ident)
    elif action == "resume":
        j = sched.resume_job(ident)
        ok = j is not None
        if ok:
            ctx.start_scheduler()
    elif action == "cancel":
        ok = sched.cancel_job(ident)
    elif action == "retry":
        from research_engine.storage.platform_db import TaskNotRetryable
        try:
            t = ctx.platform_db.requeue_task(ident)
        except TaskNotRetryable as exc:
            console.print(f"retry: REFUSED ({exc})")
            return
        ok = t is not None
        if ok:
            ctx.start_scheduler()
            console.print(f"task {ident} requeued")
            return
    console.print(f"{action}: {'OK' if ok else 'REFUSED (missing/terminal)'} "
                  f"-> {ident}")


def cmd_serve(args):
    import uvicorn
    ctx = _ctx4()
    host = args.host or ctx.cfg.platform.api.host
    port = args.port or ctx.cfg.platform.api.port
    if host not in ("127.0.0.1", "localhost", "::1") and \
            not ctx.cfg.platform.api.auth_token:
        raise SystemExit(
            "refusing to bind externally without platform.api.auth_token "
            "(spec #67) - set GAR_PLATFORM__API__AUTH_TOKEN")
    from research_engine.api.app import create_app
    uvicorn.run(create_app(ctx), host=host, port=port, log_level="info")


def cmd_mcp(args):
    from research_engine.mcp_server.server import McpServer
    McpServer(_ctx4()).serve_forever()


def cmd_watch_add(args):
    from research_engine.services.watcher_service import WatcherCreate, WatcherService
    w = WatcherService(_ctx4()).create(WatcherCreate(
        project_id=args.project_id, query=args.query,
        frequency_hours=args.every_hours,
        source_scope=[x.strip() for x in args.scope.split(",") if x.strip()],
        action=args.action))
    console.print(f"watcher {w['id']} registered "
                  f"(every {w['frequency_hours']}h, scope={w['source_scope']})")


def cmd_watch_list(args):
    from research_engine.services.watcher_service import WatcherService
    ws = WatcherService(_ctx4()).list(args.project)
    if not ws:
        console.print("[dim]no watchers[/dim]")
        return
    t = Table(title="Watchers")
    for col in ("ID", "PROJECT", "QUERY", "EVERY", "ENABLED", "LAST RUN"):
        t.add_column(col)
    for w in ws:
        last = (w.get("last_run_at") or "never")[:19]
        t.add_row(w["id"], (w["project_id"] or "")[:20], w["query"][:40],
                  f"{w['frequency_hours']}h", str(w["enabled"]), last)
    console.print(t)


def cmd_watch_run(args):
    from research_engine.services.watcher_service import WatcherService
    summary = WatcherService(_ctx4()).run_now(args.watcher_id)
    console.print_json(json.dumps(summary))


def cmd_backup(args):
    from research_engine.platform.backup import backup_project
    path = backup_project(_ctx4().data_dir, args.project_id, args.out)
    console.print(f"backup written: {path} ({path.stat().st_size // 1024} KB)")


def cmd_restore(args):
    from research_engine.platform.backup import restore_project
    report = restore_project(args.archive, _ctx4().data_dir,
                             overwrite=args.overwrite)
    console.print(f"verified {report['verified_files']} files; restored: "
                  f"{', '.join(report['restored']) or 'nothing'}")


def cmd_export_bundle(args):
    from research_engine.platform.backup import export_bundle
    path = export_bundle(_ctx4().data_dir, args.project_id, args.out)
    console.print(f"bundle exported: {path}")


def cmd_verify_archive(args):
    from research_engine.platform.backup import verify_archive
    result = verify_archive(args.archive)
    status = "[green]VALID[/green]" if result["valid"] else "[red]CORRUPT[/red]"
    console.print(f"{status} engine={result.get('engine_version')} "
                  f"projects={result.get('project_ids')} "
                  f"corrupt={result.get('corrupt')}")


def cmd_repair_startup(args):
    """Deduplicate startup domain rows + complete identity indexes
    (docs/data-repair.md). Auditable summary printed."""
    from research_engine.specialists.startup.data_repair import repair_project
    from research_engine.storage.database import Database

    def _repair(pid: str) -> dict:
        ws = pathlib.Path(AppConfig.load().storage.data_dir) / pid
        db = Database(ws / "db.sqlite")
        return repair_project(db)

    if getattr(args, "all", False):
        root = pathlib.Path(AppConfig.load().storage.data_dir)
        pids = sorted(d.name for d in root.iterdir()
                      if d.is_dir() and d.name.startswith("proj_"))
    else:
        pids = [args.project_id]
    for pid in pids:
        summary = _repair(pid)
        console.print(f"[bold]{pid}[/bold]")
        for t in summary["tables"]:
            if t["removed"]:
                console.print(f"  {t['table']}: {t['before']} -> {t['after']} "
                              f"({t['removed']} removed)")
        console.print(f"  legacy conflicts marked: "
                      f"{summary.get('legacy_unlinked_conflicts_marked', 0)}; "
                      f"indexes completed: {summary.get('indexes_completed', 0)}")
    console.print("[green]repair complete[/green]")


def cmd_doctor(args):
    from research_engine.api.app import health_report
    report = health_report(_ctx4())
    icon = {"healthy": "[green]healthy[/green]",
            "degraded": "[yellow]degraded[/yellow]",
            "unavailable": "[red]unavailable[/red]"}
    console.print(f"Overall: {icon[report['status']]}")
    for name, check in report["checks"].items():
        extra = "" if check["level"] == "healthy" else \
            f" — {check.get('note') or check.get('detail') or ''}"
        console.print(f"  {name:<12} {icon[check['level']]}{extra}")


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


    # --- Phase 4: platform ---
    p = sub.add_parser("jobs", help="platform job queue visibility")
    p.add_argument("--status", default="")
    p.add_argument("--project", default="")
    p.set_defaults(fn=cmd_jobs)

    p = sub.add_parser("job", help="inspect one job incl. tasks")
    p.add_argument("job_id")
    p.set_defaults(fn=cmd_job)

    p = sub.add_parser("job-control", help="pause/resume/cancel/retry a job or task")
    p.add_argument("action", choices=["pause", "resume", "cancel", "retry"])
    p.add_argument("id")
    p.set_defaults(fn=cmd_job_control)

    # --- Phase 5: specialists ---
    sp = sub.add_parser("specialists", help="specialist registry visibility")
    sp.add_argument("sid", nargs="?", default=None,
                    help="inspect one specialist (capabilities)")
    sp.set_defaults(fn=cmd_specialists)

    rsp = sub.add_parser("research-specialists",
                         help="specialist invocations for a project")
    rsp.add_argument("project_id")
    rsp.set_defaults(fn=cmd_research_specialists)

    xdom = sub.add_parser("cross-domain",
                          help="read-only cross-domain synthesis view")
    xdom.add_argument("project_id")
    xdom.set_defaults(fn=cmd_cross_domain)

    # --- Phase 6: process intelligence ---
    p = sub.add_parser("quality", help="research-process quality dashboard (§86)")
    p.add_argument("project_id", nargs="?", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_quality)

    p = sub.add_parser("policy", help="versioned policy registry control (§52)")
    p.add_argument("action",
                   choices=["list", "show", "propose", "evaluate", "activate",
                            "rollback", "deactivate", "compare"])
    p.add_argument("kind", nargs="?", default="")
    p.add_argument("version", nargs="?", default="")
    p.add_argument("--body", default="{}", help="JSON body for propose")
    p.add_argument("--evaluation", default="", help="JSON evaluation record")
    p.add_argument("--reason", default="")
    p.add_argument("--version-a", dest="version_a", default="")
    p.add_argument("--version-b", dest="version_b", default="")
    p.set_defaults(fn=cmd_policy)

    p = sub.add_parser("feedback", help="submit/list user feedback (§85)")
    p.add_argument("project_id")
    p.add_argument("--verdict", default="",
                   help="correct|incorrect|useful|irrelevant|missing_context|"
                        "bad_source|bad_reasoning")
    p.add_argument("--target-kind", dest="target_kind", default="report")
    p.add_argument("--target-id", dest="target_id", default="")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_feedback)

    p = sub.add_parser("decisions", help="inspectable adaptive decisions (§56)")
    p.add_argument("project_id")
    p.add_argument("--kind", default="")
    p.set_defaults(fn=cmd_decisions)

    p = sub.add_parser("alerts", help="ranked research alerts (§83)")
    p.add_argument("project_id")
    p.add_argument("--status", default="open")
    p.add_argument("--ack", default="", help="alert id to acknowledge")
    p.set_defaults(fn=cmd_alerts)

    p = sub.add_parser("review", help="independent critic review (§42)")
    p.add_argument("project_id")
    p.add_argument("--level", default="STANDARD",
                   choices=["STANDARD", "DEEP", "HIGH_RIGOR"])
    p.add_argument("--no-llm", dest="no_llm", action="store_true")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("outcome", help="stored research outcomes (§6)")
    p.add_argument("project_id")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--outcome-id", dest="outcome_id", default="")
    p.set_defaults(fn=cmd_outcome)

    p = sub.add_parser("serve", help="run the REST API server")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("mcp", help="run the MCP server over stdio")
    p.set_defaults(fn=cmd_mcp)

    p = sub.add_parser("watch-add", help="register a research watcher")
    p.add_argument("project_id")
    p.add_argument("query")
    p.add_argument("--every-hours", type=float, default=24.0)
    p.add_argument("--scope", default="web",
                   help="comma list: web,openalex,arxiv,crossref")
    p.add_argument("--action", default="incremental_update",
                   choices=["incremental_update", "notify_only"])
    p.set_defaults(fn=cmd_watch_add)

    p = sub.add_parser("watch-list", help="list watchers")
    p.add_argument("--project", default="")
    p.set_defaults(fn=cmd_watch_list)

    p = sub.add_parser("watch-run", help="run a watcher tick now")
    p.add_argument("watcher_id")
    p.set_defaults(fn=cmd_watch_run)

    p = sub.add_parser("backup", help="back up a project to a verified archive")
    p.add_argument("project_id")
    p.add_argument("out")
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser("restore", help="restore a project from an archive (verifies first)")
    p.add_argument("archive")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("export-bundle", help="export portable research bundle")
    p.add_argument("project_id")
    p.add_argument("out")
    p.set_defaults(fn=cmd_export_bundle)

    p = sub.add_parser("verify-archive", help="validate an archive without restoring")
    p.add_argument("archive")
    p.set_defaults(fn=cmd_verify_archive)

    p = sub.add_parser("doctor", help="system health checks (db/storage/llm/scheduler)")
    p.set_defaults(fn=cmd_doctor)

    q = sub.add_parser("repair-startup",
                       help="dedupe startup entities by natural key (INV-003)")
    q.add_argument("project_id", nargs="?", default="")
    q.add_argument("--all", action="store_true",
                   help="repair every project workspace")
    q.set_defaults(fn=cmd_repair_startup)

    # --- startup specialist (spec #76) ---
    sp = sub.add_parser("startup", help="startup researcher commands")
    ssub = sp.add_subparsers(dest="startup_cmd", required=True)

    q = ssub.add_parser("discover", help="create/reuse a market project + discover opportunities")
    q.add_argument("market", help="market question, quoted")
    q.add_argument("--project", default="", help="existing project id to reuse")
    q.set_defaults(fn=cmd_startup_discover)

    q = ssub.add_parser("research", help="full specialist pipeline (discovery->validation->diligence)")
    q.add_argument("market", help="market question, quoted")
    q.add_argument("--project", default="", help="existing project id")
    q.add_argument("--no-run", action="store_true", help="skip the live retrieval run")
    q.set_defaults(fn=cmd_startup_research)

    q = ssub.add_parser("customer", help="customer research for a segment")
    q.add_argument("segment", nargs="?", default="", help="segment name filter")
    q.add_argument("--project", default="", help="project id (default: latest startup)")
    q.set_defaults(fn=cmd_startup_customer)

    q = ssub.add_parser("competitors", help="competitor landscape, pricing, distribution")
    q.add_argument("market", nargs="?", default="", help=argparse.SUPPRESS)
    q.add_argument("--project", default="", help="project id (default: latest startup)")
    q.set_defaults(fn=cmd_startup_competitors)

    q = ssub.add_parser("opportunity", help="due diligence on one opportunity")
    q.add_argument("opportunity_id", nargs="?", default="", help="opp_ id (default: top)")
    q.add_argument("--project", default="")
    q.set_defaults(fn=cmd_startup_opportunity)

    q = ssub.add_parser("validate", help="assumptions -> ranked validation tests")
    q.add_argument("opportunity_id", nargs="?", default="")
    q.add_argument("--project", default="")
    q.set_defaults(fn=cmd_startup_validate)

    q = ssub.add_parser("compare", help="compare opportunities side by side")
    q.add_argument("a", nargs="?", default="", help=argparse.SUPPRESS)
    q.add_argument("b", nargs="?", default="", help=argparse.SUPPRESS)
    q.add_argument("--project", default="")
    q.set_defaults(fn=cmd_startup_compare)

    q = ssub.add_parser("assumptions", help="ranked assumption register")
    q.add_argument("opportunity_id", nargs="?", default="")
    q.add_argument("--project", default="")
    q.set_defaults(fn=cmd_startup_assumptions)

    q = ssub.add_parser("next", help="highest-leverage next action")
    q.add_argument("opportunity_id", nargs="?", default="")
    q.add_argument("--project", default="")
    q.set_defaults(fn=cmd_startup_next)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()


app = main  # entry point alias
