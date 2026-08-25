"""Data repair for pre-fix duplication (audit BUG-02).

Deduplicates startup domain tables by NATURAL KEY, keeping the oldest row
as canonical, merging list/dict provenance into it (INVARIANT-003), and
deleting the remainder. Auditable: returns a per-table summary.

Usage:
    from research_engine.specialists.startup.data_repair import repair_project
    summary = repair_project(db)              # Database instance
    summary = repair_startup_kb(kb_db)       # market_kb.sqlite Database

CLI: `research repair-startup <project_id>` / `--all`
"""
from __future__ import annotations

from research_engine.specialists.startup.identity import (
    desc_fingerprint, norm_name, price_key)
from research_engine.specialists.startup.repos import StartupRepos


def _group_key(table: str, d: dict) -> tuple | None:
    """Natural key over the raw JSON dict of a row."""
    if table == "startup_markets":
        return ("m", (d.get("market_slug") or "").lower())
    if table == "market_sizes":
        return ("s", d.get("evidence_id") or "")
    if table == "startup_personas":
        return ("p", (d.get("segment_id") or "").lower())
    if table == "jtbd":
        return ("j", (d.get("segment_id") or "").lower())
    if table == "alternatives":
        return ("a", norm_name(d.get("name") or ""))
    if table == "competitor_profiles":
        return ("c", (d.get("name_lower") or norm_name(d.get("name") or "")))
    if table == "pricing_plans":
        return ("pr", (d.get("competitor_name") or "").lower(),
                price_key(d.get("price_raw", ""), d.get("currency", ""),
                          d.get("billing_period", "")))
    if table == "distribution_channels":
        return ("d", (d.get("name") or "").lower())
    if table == "tech_shifts":
        return ("t", desc_fingerprint(d.get("description") or ""))
    return None


_MERGE_LISTS = {
    "Market": ["boundaries", "exclusions", "related_markets", "segments",
               "drivers", "constraints", "technology_drivers",
               "definition_gaps", "evidence_ids"],
    "Persona": ["responsibilities", "pain_points", "existing_tools",
                "evidence_ids"],
    "JobToBeDone": ["workflow_steps", "pain_ids", "evidence_ids"],
    "CurrentAlternative": ["used_by_segments", "evidence_ids"],
    "CompetitorProfile": ["features", "integrations", "distribution_channels",
                          "strengths", "weaknesses", "recent_changes",
                          "evidence_ids"],
    "TechnologyShift": ["evidence_ids"],
    "DistributionChannel": ["used_by"],
}
_MODEL_BY_TABLE = {
    "startup_markets": "Market",
    "startup_personas": "Persona",
    "jtbd": "JobToBeDone",
    "alternatives": "CurrentAlternative",
    "competitor_profiles": "CompetitorProfile",
    "tech_shifts": "TechnologyShift",
    "distribution_channels": "DistributionChannel",
}


def _dedupe_table(repos: StartupRepos, db, table: str) -> dict:
    # ids are sequential (ent_000001-style): id order == insertion order,
    # so the oldest row of each duplicate group sorts first
    raw = db.execute(f"SELECT id, project_id, data FROM {table} ORDER BY id")
    groups: dict[tuple, list] = {}
    for r in raw:
        import json as _json
        d = _json.loads(r["data"])
        k = _group_key(table, d)
        if k is None:
            continue
        groups.setdefault((r["project_id"],) + tuple(k), []).append((r["id"], d))
    removed = 0
    merged_into = 0
    model_name = _MODEL_BY_TABLE.get(table)
    repo = getattr(repos, {
        "startup_markets": "markets", "startup_personas": "personas",
        "jtbd": "jtbd", "alternatives": "alternatives",
        "competitor_profiles": "competitor_profiles",
        "tech_shifts": "tech_shifts",
        "distribution_channels": "distribution_channels",
    }.get(table, ""), None)
    for _, members in groups.items():
        if len(members) <= 1:
            continue
        keep_id, keep_data = members[0]
        if repo is not None and model_name:
            canonical = repo.model.model_validate(keep_data)
            for dup_id, dup_data in members[1:]:
                incoming = repo.model.model_validate(dup_data)
                for field in _MERGE_LISTS.get(model_name, []):
                    have = list(getattr(canonical, field, []) or [])
                    for item in (getattr(incoming, field, []) or []):
                        if item not in have:
                            have.append(item)
                    setattr(canonical, field, have)
                if model_name == "DistributionChannel" and \
                        incoming.evidence_class == "observed":
                    canonical.evidence_class = "observed"
                if model_name == "CompetitorProfile":
                    ce = dict(getattr(canonical, "channel_evidence", {}) or {})
                    ce.update(getattr(incoming, "channel_evidence", {}) or {})
                    canonical.channel_evidence = ce
            repos and repo.save(canonical)
        for dup_id, _ in members[1:]:
            db.delete(table, dup_id)
            removed += 1
        merged_into += 1
    total = len(raw)
    return {"table": table, "before": total, "removed": removed,
            "duplicate_groups": merged_into, "after": total - removed}


def repair_project(db) -> dict:
    """Repair one project Database. Returns auditable summary."""
    repos = StartupRepos(db)
    tables = ["startup_markets", "market_sizes", "startup_personas", "jtbd",
              "alternatives", "competitor_profiles", "pricing_plans",
              "distribution_channels", "tech_shifts"]
    summary = {"tables": [], "indexes_completed": False,
               "legacy_unlinked_conflicts_marked": 0}
    for t in tables:
        summary["tables"].append(_dedupe_table(repos, db, t))
    # INVARIANT-009 legacy sweep: contradictions with no claim AND no
    # evidence links are malformed historical rows — marked, never fabricated
    import json as _json
    marked = 0
    for r in db.execute("SELECT id, data FROM contradictions"):
        d = _json.loads(r["data"])
        linked = bool(d.get("claim_a_id") or d.get("claim_b_id")
                      or d.get("evidence_a_ids") or d.get("evidence_b_ids"))
        if not linked and d.get("conflict_type", "") != "LEGACY_UNLINKED":
            d["conflict_type"] = "LEGACY_UNLINKED"
            d.setdefault("explanation", "")
            d["explanation"] = ("[legacy unlinked conflict] "
                                + d.get("explanation", ""))[:500]
            db.upsert("contradictions", r["id"], r["project_id"], d,
                      {"resolved": 1 if d.get("resolved") else 0})
            marked += 1
    summary["legacy_unlinked_conflicts_marked"] = marked

    # after dedupe, complete any unique indexes that previously failed
    pending = list(getattr(db, "skipped_unique_indexes", []))
    still_pending: list[str] = []
    completed = 0
    for stmt in pending:
        try:
            with db._conn() as c:
                c.execute(stmt)
            completed += 1
        except Exception:
            still_pending.append(stmt)
    db.skipped_unique_indexes = still_pending
    summary["indexes_completed"] = completed
    summary["indexes_still_pending"] = len(still_pending)
    return summary
