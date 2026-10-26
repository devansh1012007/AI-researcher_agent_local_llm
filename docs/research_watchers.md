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

1. search scoped providers — the web leg runs through the shared provider registry (`web_provider: none` unregisters the WEB provider only, so the web leg is skipped); the academic leg runs against the configured academic providers (default `openalex`, `crossref`, and `arxiv` via `search.academic_providers`). Both legs use the same provider registry and must be registered to run (unconfigured legs are reported as gaps, not failures).
2. diff against remembered source hashes → new / changed / unchanged
3. `SourceUpdated` events with affected claim summaries (#132)
4. incremental extraction ONLY over new+changed documents (bounded batch)
5. backoff on persistent emptiness — consecutive empty ticks are tracked so
   watchers never hammer or loop forever (#165)

### Failure reporting (INV-012)

A tick records the two provider states in SEPARATE lists, and the summary
says which happened:

| summary key | meaning |
|---|---|
| `status` | `DEGRADED` when a provider FAILED, `OK` otherwise |
| `failures` | the providers that raised, with the exception (`"web: SearchProviderError: ..."`) — present only when there is at least one |
| `unconfigured` | the providers that were never registered (`web_provider: none`, or an academic provider the operator did not enable) — present only when there is at least one |

An unconfigured provider is NOT a failure: an offline install must not be
reported as an outage. The status is derived from the recorded failures, never
from the message text.

The distinction is enforced at the point where it is known (the provider
lookup), and it is pinned by a test that asserts the CLASSIFICATION — an
offline install must leave `web` in the unconfigured list and NO failures.
Asserting only "no hits" would prove nothing: a blocked outbound call
produces the same empty hit list, so the tick would look healthy either way.

Behaviour change: the academic leg used to call `reg.academic`, an attribute
the registry does not have, so the exception was swallowed and the leg NEVER
ran. It now runs, so a tick issues more provider calls than before: one
academic query per academic provider named IN THE SCOPE, or — when the scope
names no academic provider — one per CONFIGURED academic provider
(`search.academic_providers`, default `openalex`, `crossref`, `arxiv`),
because the provider list comes from the configuration and not only from the
watcher's scope. The web query is added when the web provider is registered.
That is intentional: the leg was supposed to run.

Consequence for an offline install: `web_provider: none` alone does NOT make
the tick silent — the three default academic providers still answer it. A
fully offline tick needs `search.academic_providers: []` as well; the
providers that are not registered are then reported as unconfigured.

## Scheduling

Watchers run as BACKGROUND-priority `watcher_tick` jobs through the same
persistent scheduler; due computation uses last_run_at + frequency_hours.

## CLI

```bash
research watch-add <proj> "monitor query" --every-hours 12 --scope web,openalex
research watch-list [--project <pid>]
research watch-run <watcher_id>       # tick now
```

Events emitted feed the notification backbone (#21/#133). The watcher
publishes two of the canonical event types (`platform/events.py` `EVENT_TYPES`
is the authoritative list):

- `SourceUpdated` — for each newly discovered URL (`kind: "new_source"`) and
  for each changed source (`kind: "SOURCE_UPDATED"`, with the affected claim
  summaries). A newly discovered URL publishes `SourceUpdated`, NOT
  `EvidenceCreated`: no evidence exists until the document is fetched and
  extracted.
- `WatcherTriggered` — when the tick found something new or changed; the
  payload carries the tick summary.
