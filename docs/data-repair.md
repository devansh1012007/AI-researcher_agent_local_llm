# Data Repair

Tool: `research_engine.specialists.startup.data_repair.repair_project(db)`
CLI: `research repair-startup <project_id>` / run per workspace DB.

What it does (auditable summary returned):
1. Deduplicates startup tables by NATURAL KEY (docs/entity-identity.md):
   oldest row canonical, list provenance unioned, duplicates deleted.
2. Marks fully-unlinked historical conflicts `LEGACY_UNLINKED` (INV-009);
   never fabricates relationships.
3. Completes unique natural-key indexes skipped on polluted DBs.

Summary fields: per-table before/after/removed/duplicate_groups,
legacy_unlinked_conflicts_marked, indexes_completed, indexes_still_pending.

Run once per affected workspace after upgrading past the stabilization fix.
Fresh workspaces need nothing (indexes exist from creation).
