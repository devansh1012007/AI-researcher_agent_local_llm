# Data Repair

Tool: `research_engine.specialists.startup.data_repair.repair_project(db)`
CLI: `research repair-startup <project_id>` / run per workspace DB.

What it does (auditable summary returned):
1. Deduplicates startup tables by NATURAL KEY (docs/entity-identity.md):
   the row with the EARLIEST payload `created_at` is canonical, list
   provenance unioned, duplicates deleted.
2. Marks fully-unlinked historical conflicts `LEGACY_UNLINKED` (INV-009);
   never fabricates relationships.
3. Completes unique natural-key indexes skipped on polluted DBs.

## Which row survives a duplicate group

The survivor is the row with the **earliest payload `created_at`** — NOT
the row whose id sorts first. Entity ids are ULIDs now and rows written
before that change keep their old `<prefix>_%06d` counter ids, so SQLite
BINARY order is not creation order (`cpx_200000` sorts after
`cpx_01M5...`); ordering by id would keep the newer row and DELETE the
genuinely oldest one.

`created_at` lives inside the row's JSON payload and is parsed, never
compared as text (`storage/database.py::parse_payload_timestamp` is the
one canonical parser): pydantic omits the fractional part when the
microseconds are exactly 0, so `'...:00Z' < '...:00.500000Z'` is false as
a string comparison but true chronologically.

A row whose `created_at` is missing or unparseable has an **unknown
age**: it never displaces a row with a known age (it sorts last, and the
id breaks the tie). Such rows are counted per table as
`rows_unknown_age`, so the repair stays auditable.

Summary fields: per-table before/after/removed/duplicate_groups/
rows_unknown_age, legacy_unlinked_conflicts_marked, indexes_completed,
indexes_still_pending.

Run once per affected workspace after upgrading past the stabilization fix.
Fresh workspaces need nothing (indexes exist from creation).
