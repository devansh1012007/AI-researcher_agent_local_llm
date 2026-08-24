"""Research snapshots and diffs (spec #51/#52).

A snapshot is a consistent copy of the project DB plus a manifest. A diff
compares two snapshots (or live state vs snapshot) and reports what changed:
added claims/evidence, resolved gaps, new contradictions, invalidated claims,
and whether research quality improved.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories

MANIFEST = "snapshot_manifest.json"


@dataclass
class SnapshotManifest:
    snapshot_id: str
    project_id: str
    created_at: str = ""
    iteration: int = 0
    counts: dict = field(default_factory=dict)
    engine_version: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, default=str)


class SnapshotManager:
    def __init__(self, workspace):
        self.ws = workspace
        self.snap_dir = self.ws.root / "snapshots"
        self.snap_dir.mkdir(parents=True, exist_ok=True)

    def create(self, repos: Repositories, project_id: str, label: str = "") -> SnapshotManifest:
        n = len(list(self.snap_dir.glob("snapshot_*")))
        snap_id = f"snapshot_{n + 1:03d}" + (f"_{label}" if label else "")
        dest = self.snap_dir / snap_id
        dest.mkdir(exist_ok=True)
        # consistent copy via sqlite backup API
        src = sqlite3.connect(str(self.ws.db_path))
        dst = sqlite3.connect(str(dest / "db.sqlite"))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        manifest = SnapshotManifest(
            snapshot_id=snap_id, project_id=project_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            iteration=self._current_iteration(repos, project_id),
            counts=self._counts(repos, project_id),
            engine_version="0.2.0")
        (dest / MANIFEST).write_text(manifest.to_json())
        return manifest

    @staticmethod
    def _current_iteration(repos: Repositories, project_id: str) -> int:
        p = repos.projects.get(project_id)
        return p.current_iteration if p else 0

    @staticmethod
    def _counts(repos: Repositories, project_id: str) -> dict:
        from research_engine.models.enums import EvidenceStatus
        return {
            "evidence": repos.evidence.count(project_id),
            "evidence_accepted": repos.evidence.count(project_id, "status!='REJECTED'"),
            "claims": repos.claims.count(project_id),
            "gaps_open": repos.gaps.count(project_id, "resolved=0"),
            "gaps_resolved": repos.gaps.count(project_id, "resolved=1"),
            "contradictions": repos.contradictions.count(project_id),
            "sources_parsed": repos.sources.count(project_id, "status='PARSED'"),
            "queries_executed": repos.queries.count(project_id, "executed=1"),
        }

    def list_snapshots(self) -> list[SnapshotManifest]:
        out = []
        for d in sorted(self.snap_dir.glob("snapshot_*")):
            mf = d / MANIFEST
            if mf.exists():
                data = json.loads(mf.read_text())
                out.append(SnapshotManifest(**data))
        return out


def diff_states(repos: Repositories, project_id: str,
                before_counts: dict, after_counts: dict | None = None,
                before_claim_ids: set[str] | None = None,
                after_claim_ids: set[str] | None = None,
                before_gap_ids: set[str] | None = None) -> dict:
    """Research diff between two states (usually consecutive iterations)."""
    after_counts = after_counts or SnapshotManager._counts(repos, project_id)
    added_claims = removed_claims = []
    if before_claim_ids is not None and after_claim_ids is not None:
        added_claims = sorted(after_claim_ids - before_claim_ids)
        removed_claims = sorted(before_claim_ids - after_claim_ids)
    gaps_resolved_delta = (after_counts.get("gaps_resolved", 0)
                           - before_counts.get("gaps_resolved", 0))
    contradictions_new = (after_counts.get("contradictions", 0)
                          - before_counts.get("contradictions", 0))
    evidence_added = (after_counts.get("evidence", 0) - before_counts.get("evidence", 0))
    claims_added = (after_counts.get("claims", 0) - before_counts.get("claims", 0))

    # research gain (spec #88): supported claims + resolved gaps - noise penalties
    gain = (claims_added + gaps_resolved_delta * 2
            + max(0, after_counts.get("evidence_accepted", 0)
                  - before_counts.get("evidence_accepted", 0)))
    efficiency_note = ""
    if evidence_added > 0:
        ratio = claims_added / max(1, evidence_added)
        efficiency_note = f"{ratio:.2f} new claims per evidence item"

    return {
        "added": {"claims": claims_added, "evidence": evidence_added},
        "resolved": {"gaps": max(0, gaps_resolved_delta)},
        "new_contradictions": max(0, contradictions_new),
        "invalidated_claims": len(removed_claims) if removed_claims else 0,
        "research_gain": gain,
        "efficiency": efficiency_note,
        "quality_direction": ("improved" if gain >= 5 else
                              "unchanged" if gain >= 1 else "decreased"),
    }


def iteration_diff(repos: Repositories, project_id: str, it_a: int, it_b: int) -> dict:
    """Diff between iterations using metrics snapshots."""

    def ids_at(table: str, it: int) -> set[str]:
        rows = repos.db.execute(
            f"SELECT id FROM {table} WHERE project_id=? AND iteration<=?", (project_id, it))
        return {r["id"] for r in rows}

    before = SnapshotManager._counts(repos, project_id)
    metrics_a = [m for m in repos.metrics.all(project_id) if m.iteration == min(it_a, it_b)]
    metrics_b = [m for m in repos.metrics.all(project_id) if m.iteration == max(it_a, it_b)]
    base = {"evidence": metrics_a[0].evidence_created if metrics_a else 0,
            "evidence_accepted": (metrics_a[0].evidence_created - metrics_a[0].evidence_rejected)
            if metrics_a else 0,
            "claims": metrics_a[0].unique_claims if metrics_a else 0,
            "gaps_open": metrics_a[0].gaps_open if metrics_a else 0,
            "gaps_resolved": metrics_a[0].gaps_resolved if metrics_a else 0,
            "contradictions": metrics_a[0].contradictions if metrics_a else 0}
    after = {"evidence": metrics_b[0].evidence_created if metrics_b else before["evidence"],
             "evidence_accepted": ((metrics_b[0].evidence_created - metrics_b[0].evidence_rejected)
                                   if metrics_b else before["evidence_accepted"]),
             "claims": metrics_b[0].unique_claims if metrics_b else before["claims"],
             "gaps_open": metrics_b[0].gaps_open if metrics_b else before["gaps_open"],
             "gaps_resolved": metrics_b[0].gaps_resolved if metrics_b else before["gaps_resolved"],
             "contradictions": metrics_b[0].contradictions if metrics_b else before["contradictions"]}
    return diff_states(repos, project_id, base, after)


class SourceUpdateDetector:
    """Detects content changes at a known URL without overwriting history (#98/#99)."""

    def __init__(self, repos: Repositories):
        self.repos = repos

    def check(self, source_id: str, new_content_hash: str, observed_at: str) -> dict:
        src = self.repos.sources.get(source_id)
        if src is None:
            return {"changed": False, "reason": "unknown source"}
        old_hash = src.content_hash
        if not old_hash:
            return {"changed": False, "reason": "no baseline hash"}
        if old_hash == new_content_hash:
            return {"changed": False}
        event = {
            "source_id": source_id, "url": src.url,
            "old_hash": old_hash[:12], "new_hash": new_content_hash[:12],
            "observed_at": observed_at,
            "note": "source version changed; prior document retained",
        }
        # temporal observation appended, never overwritten (spec #99)
        with self.repos.db._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO source_versions(id, project_id, source_id,"
                " observed_at, data) VALUES(?,?,?,?,?)",
                (f"sv_{observed_at}_{source_id}", src.project_id, source_id,
                 observed_at, json.dumps(event)))
        return {"changed": True, **event}
