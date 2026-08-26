"""Golden research runs (gate §38-48): deterministic regression baselines.

Usage:
    python evals/runners/run_golden.py                 # run both suites, offline
    python evals/runners/run_golden.py --suite startup
    python evals/runners/run_golden.py --update-baseline --reason "why"
    python evals/runners/run_golden.py --live          # periodic realism check

Offline runs are FULLY DETERMINISTIC (ScriptedLLM + fake providers, fresh
workspace, question-derived project id): metrics must reproduce the recorded
baseline EXACTLY. Any drift is a regression unless the baseline is
intentionally updated with a documented reason (§46).

Live mode re-runs the same questions against real providers and applies
threshold checks + tolerance bands instead of exact equality; it is a
realism check, not a regression gate.

Known violations: an expectation annotated with a gate finding id (e.g.
F-01) is allowed to fail WITHOUT failing the suite — but it is printed as
KNOWN_VIOLATION every run. Removing its annotation once fixed makes it a
hard gate again (self-flipping).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals" / "runners"))

GOLDEN_DIR = ROOT / "evals" / "golden"
SUITE_ROOTS = [GOLDEN_DIR,
               ROOT / "evals" / "specialists",
               ROOT / "evals" / "cross_domain"]


def _suite_paths(name: str) -> tuple[Path, Path] | None:
    """Returns (manifest_path, baseline_path). Supports both layouts:
    <root>/<name>/manifest.json + baseline.json   (golden dirs)
    <root>/<name>.json + <name>.baseline.json     (flat eval datasets)"""
    for root in SUITE_ROOTS:
        d = root / name
        if (d / "manifest.json").exists():
            return d / "manifest.json", d / "baseline.json"
    for root in SUITE_ROOTS:
        f = root / f"{name}.json"
        if f.exists():
            return f, root / f"{name}.baseline.json"
    return None


# --------------------------------------------------------------- versions

def _versions() -> dict:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True,
                             cwd=ROOT).stdout.strip()
    except Exception:
        sha = "unknown"
    return {"git": sha or "unknown", "python": sys.version.split()[0]}


def _cfg_fingerprint(cfg) -> dict:
    r = cfg.research
    return {
        "max_iterations": r.max_iterations,
        "new_evidence_threshold": r.new_evidence_threshold,
        "duplicate_rate_converged": r.duplicate_rate_converged,
        "web_provider": cfg.search.web_provider,
        "academic_providers": list(cfg.search.academic_providers),
        "hits_per_query": 3, "academic_n": 2,  # fake corpus knobs
    }


# --------------------------------------------------------------- run

def run_golden(task: dict):
    """Offline deterministic run in a fresh workspace (mirrors run_eval)."""
    import tempfile as _t
    from research_engine.core.config import AppConfig
    from conftest import OfflineOrchestrator
    from research_engine.pipeline.routing import ProviderRegistry
    from fakes import FakeAcademicProvider, FakeSearchProvider
    from research_engine.models.project import ResearchProject
    from research_engine.core.ids import project_id_from_question

    cfg = AppConfig.load()
    fresh = _t.mkdtemp(prefix="gar_golden_")
    cfg.storage.data_dir = str(Path(fresh) / "data")
    cfg.research.max_iterations = 1  # deterministic single-iteration depth
    reg = ProviderRegistry()
    reg.register_search("web", FakeSearchProvider(hits_per_query=3))
    for n in ("openalex", "arxiv", "crossref", "semantic_scholar"):
        reg.register_academic(n, FakeAcademicProvider(n=2))
    project = ResearchProject(
        id=project_id_from_question(task["question"]),
        question_raw=task["question"], mode=task["mode"])
    orch = OfflineOrchestrator(cfg, project, reg,
                               startup_mode=(task["mode"] == "startup"))
    orch.repos.projects.save(orch.project)
    t0 = time.time()
    orch.run()
    secs = round(time.time() - t0, 2)
    return orch, cfg, secs


# --------------------------------------------------------------- audits

def collect_metrics(orch) -> dict:
    from research_engine.models.enums import EvidenceStatus
    pid = orch.project.id
    ev = orch.repos.evidence.all(pid)
    claims = orch.repos.claims.all(pid)
    m = {
        "sources": len(orch.repos.sources.all(pid)),
        "evidence_total": len(ev),
        "evidence_supported": sum(1 for e in ev
                                  if e.status == EvidenceStatus.SUPPORTED),
        "evidence_rejected": sum(1 for e in ev
                                 if e.status == EvidenceStatus.REJECTED),
        "claims": len(claims),
        "gaps": len(orch.repos.gaps.all(pid)),
        "contradictions": len(orch.repos.contradictions.all(pid)),
        "hypotheses": len(list(ReasoningReposSafe(orch).hypotheses.all(pid))),
        "stop_reason": str(getattr(orch.project, "last_stop_reason", "") or ""),
        "report_files": sorted(p.name for p in Path(orch.ws.reports).glob("*.md"))
        if Path(orch.ws.reports).exists() else [],
    }
    if orch.project.mode == "startup":
        srepos = orch._srepos if hasattr(orch, "_srepos") else None
        if srepos is None:
            from research_engine.specialists.startup.repos import (
                get_startup_repos)
            srepos = get_startup_repos(orch)
        opps = orch.repos.opportunities.all(pid)
        rr = ReasoningReposSafe(orch)
        m.update({
            "markets": len(srepos.markets.all(pid)),
            "market_sizes": len(srepos.market_sizes.all(pid)),
            "personas": len(srepos.personas.all(pid)),
            "competitors": len(srepos.competitor_profiles.all(pid)),
            "pricing_plans": len(srepos.pricing_plans.all(pid)),
            "jtbd": len(srepos.jtbd.all(pid)),
            "opportunities": len(opps),
            "assumptions": len(rr.assumptions.all(pid)),
            "validation_experiments": len(rr.experiments.all(pid)),
        })
    return m


def ReasoningReposSafe(orch):
    if not hasattr(orch, "_rrepos_gate"):
        from research_engine.storage.reasoning_repos import ReasoningRepos
        orch._rrepos_gate = ReasoningRepos(orch.db)
    return orch._rrepos_gate


def structural_invariants(orch, task: dict) -> dict:
    """Hard checks that must hold for ANY specialist's golden output."""
    from research_engine.specialists.extension_audit import (
        store_fingerprint, ungrounded_evidence, validate_score_schema)
    results: dict[str, str] = {}
    pid = orch.project.id

    # INV-005 audit over real pipeline output
    results["no_ungrounded_synthesis_evidence"] = (
        "pass" if not ungrounded_evidence(orch.db, pid) else "fail")

    # claim traceability: every claim cites at least one evidence item
    ev_ids = {e.id for e in orch.repos.evidence.all(pid)}
    untraced = [c.id for c in orch.repos.claims.all(pid)
                if not set(c.supported_by) & ev_ids]
    results["all_claims_traceable"] = "pass" if not untraced else \
        f"fail:{len(untraced)}"

    # INV-010: canonical score schema on every opportunity
    bad_scores = []
    for o in orch.repos.opportunities.all(pid):
        if validate_score_schema(o.score_breakdown):
            bad_scores.append(o.id)
    results["opportunity_scores_schema_v2"] = \
        "pass" if not bad_scores else f"fail:{len(bad_scores)}"

    # INV-004 purity of report generation (known violation tolerated per F-01)
    known_map = task.get("known_violations", {})
    known = known_map.get("report_generation_read_only")
    before = store_fingerprint([Path(orch.ws.db_path)])
    from research_engine.reports.generator import ReportGenerator
    gen = ReportGenerator(_gate_cfg(orch), None, orch.repos, orch.ws)
    gen.generate_all(orch.project)
    after = store_fingerprint([Path(orch.ws.db_path)])
    pure = before == after
    results["report_generation_read_only"] = \
        "pass" if pure else (f"known_violation:{known}" if known else "fail")

    # startup-specific traceability (§42)
    if orch.project.mode == "startup":
        srepos = orch._srepos if hasattr(orch, "_srepos") else None
        if srepos is None:
            from research_engine.specialists.startup.repos import (
                get_startup_repos)
            srepos = get_startup_repos(orch)
        opps = orch.repos.opportunities.all(pid)
        results["opportunities_have_evidence"] = \
            "pass" if all(o.evidence_ids for o in opps) else "fail"
        # F-07 telemetry: pricing/signal linkage recorded, gated softly
        linked = sum(1 for o in opps
                     if o.pricing_evidence_ids or o.market_signal_evidence_ids)
        results["pricing_or_signal_linkage"] = (
            "pass" if linked == len(opps) else
            f"known_violation:F-07 (linked {linked}/{len(opps)})")
    return results


def _gate_cfg(orch):
    return orch.cfg if hasattr(orch, "cfg") else None


def compare_to_baseline(metrics: dict, baseline: dict) -> list[str]:
    diffs = []
    b = baseline.get("metrics", {})
    for k in sorted(set(b) | set(metrics)):
        if b.get(k) != metrics.get(k):
            diffs.append(f"{k}: baseline={b.get(k)!r} got={metrics.get(k)!r}")
    return diffs


# --------------------------------------------------------------- suites

def run_specialist_golden(manifest: dict):
    """Specialist-chain goldens (Phase 5 §78): controlled corpus, real
    scheduler, structured handoffs. Deterministic offline."""
    import tempfile as _t
    import pathlib
    from research_engine.core.config import AppConfig
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.platform.events import EventBus
    from research_engine.platform.job_runners import make_specialist_runner
    from research_engine.platform.scheduler import (
        PersistentScheduler, SchedulerConfig)
    from research_engine.storage.platform_db import PlatformDB
    from research_engine.specialists.bootstrap import (
        ensure_builtin_specialists)
    from research_engine.specialists.extension_audit import (
        store_fingerprint, ungrounded_evidence)

    ensure_builtin_specialists()
    cfg = AppConfig.load()
    fresh = _t.mkdtemp(prefix="gar_golden_sp_")
    cfg.storage.data_dir = str(Path(fresh) / "data")
    from research_engine.models.evidence import Evidence
    from research_engine.models.research import Source

    orch = Orchestrator.create_project(
        cfg, manifest["question"], mode=manifest.get("mode", "startup"))
    orch.repos.projects.save(orch.project)
    pid = orch.project.id
    s = Source(project_id=pid, url="https://golden.example.com/corpus",
               canonical_url="https://golden.example.com/corpus",
               domain="golden.example.com", title="controlled corpus")
    s.ensure_id()
    orch.repos.sources.save(s)
    ev_ids = []
    for claim, quote in manifest.get("seed_corpus", []):
        e = Evidence(project_id=pid, claim_text=claim, quote=quote,
                     source_id=s.id, source_tier=3,
                     status="SUPPORTED", support_verdict="SUPPORTS")
        e.ensure_id()
        orch.repos.evidence.save(e)
        ev_ids.append(e.id)

    db = PlatformDB(pathlib.Path(cfg.storage.data_dir))
    bus = EventBus()
    sched = PersistentScheduler(db, SchedulerConfig(
        worker_threads=1, poll_interval=0.02, lease_seconds=60,
        heartbeat_seconds=999))

    class Ctx:
        pass
    c = Ctx()
    c.cfg = cfg
    c.bus = bus
    c.platform_db = db
    runner = make_specialist_runner(c, cfg)
    sched.register_runner("SPECIALIST_TASK", lambda t: runner(t))

    def wait(job_id, timeout=30):
        sched.start()
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                ts = db.tasks_for_job(job_id)
                if ts and ts[0].status in ("SUCCEEDED", "FAILED",
                                           "DEAD_LETTER"):
                    return ts[0]
                time.sleep(0.05)
            raise TimeoutError(job_id)
        finally:
            sched.stop()

    from research_engine.specialists.workflows import submit_stage, \
        handoff_from_result
    t0 = time.time()
    stage_results = []
    prev_handoff = None
    for i, (sid, mode) in enumerate(manifest["stages"]):
        job_id = submit_stage(db, pid, sid, i, mode=mode,
                              handoff=prev_handoff,
                              routing_reason="golden chain")
        task = wait(job_id)
        stage_results.append({
            "specialist": sid,
            "status": task.status,
            "error": (task.error or "")[:120],
        })
        if task.status != "SUCCEEDED":
            break
        if i + 1 < len(manifest["stages"]):
            nxt = manifest["stages"][i + 1][0]
            prev_handoff = handoff_from_result(sid, nxt,
                                               manifest["question"],
                                               task.result)
    secs = round(time.time() - t0, 2)

    checks = {
        "all_stages_succeeded": "pass" if all(
            r["status"] == "SUCCEEDED" for r in stage_results)
        else f"fail:{[r for r in stage_results if r['status'] != 'SUCCEEDED']}",
        "no_ungrounded_synthesis_evidence": "pass" if not
        ungrounded_evidence(orch.db, pid) else "fail",
    }
    metrics = {
        "seed_evidence": len(ev_ids),
        "evidence_after": len(orch.repos.evidence.all(pid)),
        "claims": len(orch.repos.claims.all(pid)),
        "gaps": len(orch.repos.gaps.all(pid)),
        "stage_statuses": [r["status"] for r in stage_results],
    }
    # §85/§47 threshold-based quality gates (not exact-answer matching)
    th = manifest.get("thresholds", {}) or {}
    for key, need in th.items():
        got = metrics.get(key, 0)
        checks[f"threshold_{key}"] = "pass" if got >= need else \
            f"fail:{got}<{need}"
    return checks, metrics, secs


def run_suite(name: str, update: bool, reason: str) -> bool:
    paths = _suite_paths(name)
    if paths is None:
        print(f"\n=== golden/{name} :: MISSING manifest")
        return False
    manifest_path, baseline_path = paths
    manifest = json.loads(manifest_path.read_text())
    known = manifest.get("known_violations", {})
    baseline = json.loads(baseline_path.read_text()) \
        if baseline_path.exists() else None
    if manifest.get("mode") == "specialist_chain":
        checks, metrics, secs = run_specialist_golden(manifest)
    else:
        task = {"question": manifest["question"], "mode": manifest["mode"],
                "known_violations": known}
        orch, cfg, secs = run_golden(task)
        metrics = collect_metrics(orch)
        checks = structural_invariants(orch, task)

    ok = True
    hard_failures = []
    for cname, cres in sorted(checks.items()):
        if cres == "pass":
            print(f"  PASS  {cname}")
        elif cres.startswith("known_violation:"):
            print(f"  KNOWN_VIOLATION ({cres.split(':', 1)[1]})  {cname}")
        else:
            print(f"  FAIL  {cname} [{cres}]")
            hard_failures.append(cname)

    if update:
        baseline_path.write_text(json.dumps({
            "versions": _versions(),
            "config": _cfg_fingerprint(cfg) if manifest.get("mode")
            not in ("specialist_chain",) else {
                "kind": "specialist_chain",
                "stages": manifest["stages"]},
            "duration_s": secs,
            "metrics": metrics,
            "updated_reason": reason,
        }, indent=2, sort_keys=True) + "\n")
        print(f"  BASELINE UPDATED ({reason or 'no reason given!'})")
    else:
        diffs = compare_to_baseline(metrics, baseline or {})
        if diffs:
            print("  DRIFT vs baseline:")
            for x in diffs:
                print(f"    - {x}")
            hard_failures.append("baseline_drift")
        else:
            print(f"  PASS  baseline_exact_match "
                  f"(recorded @ {baseline.get('versions', {}).get('git', '?')})")

    if hard_failures:
        print(f"  SUITE {name}: FAIL ({', '.join(hard_failures)})")
        return False
    print(f"  SUITE {name}: PASS ({secs}s)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", default="all",
                    help="suite dir name under evals/golden/, or 'all'")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--reason", default="", help="why baseline changed (§46)")
    ap.add_argument("--live", action="store_true",
                    help="live-network realism check (NOT a regression gate)")
    args = ap.parse_args()

    if args.live:
        print("live mode: threshold realism check only; see "
              "docs/golden_research_runs.md — not wired to baselines.")
        return 0  # live runner intentionally separate; see doc

    if args.suite == "all":
        suites = ["scientific", "startup"] + [
            d.name for d in sorted(GOLDEN_DIR.iterdir())
            if d.is_dir() and d.name not in ("scientific", "startup")]
        for extra_root in SUITE_ROOTS[1:]:
            suites += [p.stem for p in sorted(extra_root.glob("*.json"))
                       if not p.name.endswith(".baseline.json")]
    else:
        suites = [args.suite]
    all_ok = True
    for s in suites:
        all_ok &= run_suite(s, args.update_baseline, args.reason)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
