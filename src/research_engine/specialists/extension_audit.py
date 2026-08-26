"""INV-014 specialist persistence auditors (detector seam).

# Decision: auditors/detectors, not runtime blockers inside repos.save.
# Why: blocking validation at the write seam would change behavior of live
# flows (e.g. experiment-result ingestion, gate finding F-03) during a
# report-only review phase; the invariant suite and golden runs consume
# these auditors instead, so future-specialist mistakes are still CAUGHT.
# Constraint: when F-03's provenance carve-out is settled upstream,
# promote ungrounded_evidence() to enforcement at the canonical write seam
# and flip tests/invariants/test_extension_contract.py to hard assertions.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

# Provenance kinds allowed to bypass claim-support verification today.
# Keep this list explicit and tiny; every entry needs an invariants-doc note.
GROUNDED_EXEMPT_SOURCE_TYPES = ("experiment_result",)

# Statuses that mean "this evidence feeds synthesis" (post-gate family).
_SYNTHESIS_STATUSES = {"SUPPORTED", "WEAKLY_SUPPORTED"}


def store_fingerprint(paths) -> str:
    """Content hash over authoritative stores (project db, KB, ...).

    SQLite files are hashed LOGICALLY (schema + every row, stable order) —
    byte-hashing is wrong under WAL, where committed rows live in `-wal`
    until checkpoint and a real write can leave the main file untouched.
    Missing files hash as a stable sentinel so 'file appeared' is detected.
    Used by report-purity checks and golden-run regression comparisons."""
    h = hashlib.sha256()
    for p in paths:
        p = pathlib.Path(p)
        if not p.exists():
            h.update(b"<missing>")
        elif p.read_bytes()[:16] == b"SQLite format 3\x00":
            h.update(_logical_dump_hash(p).encode())
        else:
            h.update(p.read_bytes())
    return h.hexdigest()


def _logical_dump_hash(path: pathlib.Path) -> str:
    import sqlite3
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        h = hashlib.sha256()
        for t in sorted(tables):
            cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
            h.update(repr([c[1] for c in cols]).encode())
            order = "rowid" if any(c[5] == 0 for c in cols) else \
                ", ".join(c[1] for c in cols)
            try:
                rows = conn.execute(
                    f'SELECT * FROM "{t}" ORDER BY {order}').fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(f'SELECT * FROM "{t}"').fetchall()
                rows.sort(key=repr)
            for row in rows:
                h.update(repr(row).encode())
        return h.hexdigest()
    finally:
        conn.close()


def ungrounded_evidence(db, project_id: str | None = None) -> list[dict]:
    """Return evidence rows that violate the grounding contract (INV-005).

    A row violates when it feeds synthesis (SUPPORTED / WEAKLY_SUPPORTED)
    but carries no support verdict and no explicitly allowlisted provenance;
    or when any non-REJECTED row has an empty quote (quote-existence gate).
    REJECTED rows are the audit trail and are never violations."""
    out = []
    for row in _scan(db, "evidence", project_id):
        data = row["data"]
        status = str(data.get("status", ""))
        quote = str(data.get("quote", "") or "")
        verdict = str(data.get("support_verdict", "") or "")
        stype = str(data.get("source_type", "") or "")
        if status == "REJECTED":
            continue
        why = []
        if not quote.strip():
            why.append("empty quote")
        if status in _SYNTHESIS_STATUSES and not verdict.strip() \
                and stype not in GROUNDED_EXEMPT_SOURCE_TYPES:
            why.append(f"{status} without support_verdict "
                       f"(source_type={stype or '?'})")
        if why:
            out.append({"id": row["id"], "project_id": row["project_id"],
                        "status": status, "reasons": why})
    return out


def validate_score_schema(score_breakdown: dict) -> list[str]:
    """Scores without semantics are forbidden (gate §34 / INV-010).

    Canonical breakdown (opportunities.score_rubric): schema_version=2 with
    parallel dicts factors/{reasons,labels,weights} keyed by rubric dimension,
    plus total + gate verdict."""
    problems = []
    if not score_breakdown:
        return ["empty score_breakdown (opaque score)"]
    version = score_breakdown.get("schema_version")
    if version != 2:
        problems.append(f"schema_version={version!r} (expected 2)")
    factors = score_breakdown.get("factors")
    if not isinstance(factors, dict) or not factors:
        problems.append("no named rubric factors")
        return problems
    reasons = score_breakdown.get("reasons", {})
    if not isinstance(reasons, dict):
        problems.append("reasons is not a mapping")
    else:
        for name in factors:
            if not str(reasons.get(name, "") or "").strip():
                problems.append(f"factor {name!r} lacks reason")
    return problems


def _scan(db, table: str, project_id: str | None) -> list[dict]:
    sql = f"SELECT id, project_id, data FROM {table}"
    params: tuple = ()
    if project_id:
        sql += " WHERE project_id=?"
        params = (project_id,)
    with db._conn() as c:  # noqa: SLF001 - audit tooling reads across projects
        return [{"id": r["id"], "project_id": r["project_id"],
                 "data": json.loads(r["data"])}
                for r in c.execute(sql, params).fetchall()]
