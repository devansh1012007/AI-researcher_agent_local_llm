# Research Watchers (Living Research)

Spec #17-20/#131-133: scheduled monitoring that updates knowledge
incrementally instead of rerunning projects.

## Model

```json
{"watch_id": "wch_...", "project_id": "proj_...", 
 "query": "new papers about local VLA robotics",
 "source_scope": ["web", "openalex"], "frequency_hours": 24,
 "change_policy": "content_hash", "action": "incremental_update"}
```

## Tick semantics (#19/#20)

1. search scoped providers (provider failure tolerated individually)
2. diff against remembered source hashes → new / changed / unchanged
3. SOURCE_UPDATED events with affected claim summaries (#132)
4. incremental extraction ONLY over new+changed documents (bounded batch)
5. backoff on persistent emptiness — consecutive empty ticks are tracked so
   watchers never hammer or loop forever (#165)

## Scheduling

Watchers run as BACKGROUND-priority `watcher_tick` jobs through the same
persistent scheduler; due computation uses last_run_at + frequency_hours.

## CLI

```bash
research watch-add <proj> "monitor query" --every-hours 12 --scope web,openalex
research watch-list [--project <pid>]
research watch-run <watcher_id>       # tick now
```

Events emitted feed the notification backbone (#21/#133): NEW_EVIDENCE,
SOURCE_UPDATED, HIGH_PRIORITY_GAP_FOUND etc. persist in platform_events for
future UIs.
