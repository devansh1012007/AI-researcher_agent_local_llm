#!/usr/bin/env python3
"""Phase 6 adaptive-vs-baseline benchmark (spec §64-§69, §98, §100).

Deterministic, fully OFFLINE. Compares shipped-baseline behavior against
adaptive-policy behavior on fixed labeled tasks and verifies results
against a checked-in baseline (golden-style exact match).

What is measured (and printed as the §100 table):
  1. routing accuracy + unnecessary calls   (§65)  — labeled train/test
     tasks; 'training' records observed outcomes into an isolated store
     (simulated observations, clearly not production data), then both
     policies are scored on the held-out test split.
  2. query-strategy tie-break utility       (§66)
  3. dynamic budget quality-per-query       (§68)
  4. critic recall on injected defects      (§69)

Exit code 0 iff all gates pass AND metrics match the recorded baseline.
--update-baseline re-records after REVIEWED changes only.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

ADAPTIVE_DIR = ROOT / "evals" / "adaptive"
BASELINE_PATH = ADAPTIVE_DIR / "baseline_metrics.json"

def _load_split(name: str) -> list[dict]:
    path = ADAPTIVE_DIR / name / "routing_tasks.json"
    return json.loads(path.read_text())


TRAIN_TASKS = _load_split("train")
TEST_TASKS = _load_split("test")


def _store(tmp: Path):
    from research_engine.storage.platform_db import PlatformDB
    return PlatformDB(str(tmp))


def _simulate_training(db) -> None:
    """Record OBSERVED outcomes for train tasks into the isolated store.
    Reliable specialists succeed; we deliberately give 'competitive' a
    failing history so v2's reliability floor has something real to use."""
    for t in TRAIN_TASKS:
        for sid in t["optimal"]:
            ok = sid != "competitive"
            for _ in range(6):
                db.record_specialist_perf(sid, "1.0", "generic", ok=ok,
                                          latency_s=0.5 if ok else 9.0)


def bench_routing(db) -> dict:
    from research_engine.adaptive.routing_v2 import route_v2
    from research_engine.specialists.routing import route

    def score(fn):
        hits, extra = 0, 0
        for t in TEST_TASKS:
            sel = fn(t["q"])
            ids = [s.specialist_id for s in sel]
            if ids and ids[0] == t["optimal"][0]:
                hits += 1
            extra += max(0, len(ids) - len(t["optimal"]))
        return hits, extra

    v1_hits, v1_extra = score(lambda q: route(q))
    v2_hits, v2_extra = score(
        lambda q: route_v2(q, None, db=db,
                           task_features={"research_type": "generic"})[0])
    return {
        "v1_accuracy": round(v1_hits / len(TEST_TASKS), 3),
        "v2_accuracy": round(v2_hits / len(TEST_TASKS), 3),
        "v1_unnecessary": v1_extra,
        "v2_unnecessary": v2_extra,
    }


def bench_query_strategy() -> float:
    """Utility tie-break picks the historically better family."""
    import tempfile
    from research_engine.adaptive.store import platform_store
    d = tempfile.mkdtemp()
    db = platform_store(Path(d))
    for _ in range(12):
        db.record_query_family("counterevidence", "academic", queries=5,
                               useful_results=4, new_evidence=3,
                               new_claims=1, gaps_resolved=1)
        db.record_query_family("recent_research", "academic", queries=5,
                               useful_results=1, new_evidence=0,
                               new_claims=0, gaps_resolved=0)
    rows = {r["family"]: r["avg_utility"]
            for r in db.list_query_family_perf("academic")}
    return 1.0 if rows.get("counterevidence", 0) > \
        rows.get("recent_research", 0) else 0.0


def bench_budget() -> dict:
    """§47/§48: budget FOLLOWS marginal gain — more while rising (bounded),
    strictly less once returns diminish. Raw totals are the wrong metric;
    behavior shape is the claim."""
    from research_engine.adaptive.budget import scale_iteration_budget
    base = 8
    hard_cap = 10
    seq = [4, 8, 12, 6, 1, 0]          # rising then diminishing gains
    spend = [scale_iteration_budget(base, seq[:i + 1], policy_enabled=True,
                                    hard_cap=hard_cap) for i in range(len(seq))]
    rising = spend[:3]
    falling = spend[3:]
    return {
        "spend": spend,
        # every allocation stays inside the configured envelope
        "all_bounded": int(all(1 <= s <= hard_cap for s in spend)),
        # rising phase may widen up to the cap...
        "rising_uses_budget": int(max(rising) >= base),
        # ...but the tail must TAPER below fixed-width spend
        "falling_tapers": int(max(falling) < base),
    }


def bench_critic() -> dict:
    """Known-defect recall (§69): inject dangling citation + unsupported
    FACT claim; STANDARD critic must catch both."""
    from unittest.mock import MagicMock
    from research_engine.adaptive.critic import critique_run

    class Claim:
        def __init__(self, cid, sup):
            self.id = cid
            self.supported_by = sup
            self.kind = type("K", (), {"value": "FACT"})()
            self.contradicted_by = []

    class Ev:
        def __init__(self, eid):
            self.id = eid
            self.source_tier = 1
            self.status = type("S", (), {"value": "EXTRACTED"})()
            self.source_url = ""
            self.claim_text = "x"
            self.numbers = []
            self.quote = ""
            self.chunk_id = ""

    orch = MagicMock()
    orch.repos.claims.all.return_value = [
        Claim("clm_1", ["ev_1"]),
        Claim("clm_defect_dangling", ["ev_missing"]),
        Claim("clm_defect_unsup", []),
    ]
    orch.repos.evidence.all.return_value = [Ev("ev_1")]
    orch.repos.evidence.get.return_value = None
    orch.repos.gaps.all.return_value = []
    orch.repos.contradictions.all.return_value = []
    orch.repos.chunks.get.return_value = None
    orch.repos.sources.all.return_value = []
    rev = critique_run(orch, "p", level="STANDARD")
    kinds = {f["kind"] for f in rev["findings"]}
    caught = sum(1 for k in ("missing_cited_evidence",
                             "unsupported_fact_claim") if k in kinds)
    return {"injected_defects": 2, "caught": caught,
            "recall": round(caught / 2, 2)}


GATES = {
    "v2_accuracy_gte_v1": lambda m: m["routing"]["v2_accuracy"]
        >= m["routing"]["v1_accuracy"],
    "v2_unnecessary_lte_v1": lambda m: m["routing"]["v2_unnecessary"]
        <= m["routing"]["v1_unnecessary"],
    "query_tiebreak_works": lambda m: m["query_strategy"] == 1.0,
    "budget_all_bounded": lambda m: bool(m["budget"]["all_bounded"]),
    "budget_rising_uses_budget": lambda m:
        bool(m["budget"]["rising_uses_budget"]),
    "budget_falling_tapers": lambda m: bool(m["budget"]["falling_tapers"]),
    "critic_recall": lambda m: m["critic"]["recall"] >= 0.75,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--reason", default="")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="gar_adaptive_bench_"))
    db = _store(tmp)
    _simulate_training(db)
    metrics = {
        "routing": bench_routing(db),
        "query_strategy": bench_query_strategy(),
        "budget": bench_budget(),
        "critic": bench_critic(),
    }

    print(json.dumps(metrics, indent=2))
    failures = [name for name, gate in GATES.items() if not gate(metrics)]
    for name in GATES:
        status = "PASS" if name not in failures else "FAIL"
        print(f"  {status}  {name}")

    if args.update_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(
            {"metrics": metrics, "reason": args.reason}, indent=2,
            sort_keys=True))
        print(f"baseline recorded @ {BASELINE_PATH}")
        return 0 if not failures else 1

    if BASELINE_PATH.exists():
        recorded = json.loads(BASELINE_PATH.read_text())["metrics"]
        if json.loads(json.dumps(recorded, sort_keys=True)) != \
                json.loads(json.dumps(metrics, sort_keys=True)):
            print("  FAIL  baseline_exact_match (metrics drifted)")
            failures.append("baseline_exact_match")
        else:
            print("  PASS  baseline_exact_match")
    print(f"\n=== adaptive benchmark :: "
          f"{'PASS' if not failures else 'FAIL ' + ','.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
