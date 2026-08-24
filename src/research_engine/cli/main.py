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
            console.print(f"[cyan]{br.category.value:22}[/cyan] imp={br.importance:.2f} {br.question[:100]}")
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

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()


app = main  # entry point alias
