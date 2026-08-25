# Service Boundaries (INV-008)

```
CLI ─┐
API ─┼→ Application services (services/*, specialists/*/service.py)
MCP ─┘        ↓
        Orchestrator / domain modules
              ↓
        Storage (Database, PlatformDB, graph)
```

Rules:
- API/MCP: zero direct construction of Repositories/ReasoningRepos/GraphStore;
  zero state-machine transitions. Enforced by scan test
  `TestServiceBoundaries::test_interfaces_do_not_touch_storage_directly`.
- CLI: same rule except the two read-handle loaders (_load2/_load3) feeding
  platform tooling (graph/literature). Tracked debt; do not add new sites.
- Reports are consumers, never producers: no pipeline execution, no primary
  writes (see docs/invariants.md INV-004).

Canonical operations (one path each): create/run/pause/resume projects,
ask/query, generate hypotheses (mode-aware), design methodology,
approve experiment, add result, startup discover/validate/diligence/
assumptions/next.
