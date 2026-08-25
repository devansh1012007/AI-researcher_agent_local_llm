# Backup & Restore

## Commands (spec #59/#86-89)

```bash
research backup <project_id> out.tar.gz     # verified archive
research verify-archive out.tar.gz          # integrity check w/o restoring
research restore out.tar.gz [--overwrite]   # verify FIRST, then materialize
research export-bundle <project_id> bundle.tar.gz   # portable bundle (#87/#140)
```

## Archive layout

```
gar-archive/
  manifest.json            # engine version + sha256 of EVERY file
  projects/<id>/           # db.sqlite, project.json, reports/, raw/,
                           # exports/, events.jsonl, experiments/
  platform.sqlite          # optional (--include-platform jobs/watchers)
```

## Guarantees

- **verify-before-touch**: restore validates every sha256 before writing any
  destination file; a single mismatch aborts cleanly (#89).
- **path traversal rejected**: archive members with absolute paths or `..`
  are refused (#146).
- **no silent evidence deletion**: restore refuses existing destinations
  unless `--overwrite`; cleanup policies elsewhere distinguish rebuildable
  cache from evidence (#60/#61).
- portability: archives move between machines; imports validate structure
  first (#88).
