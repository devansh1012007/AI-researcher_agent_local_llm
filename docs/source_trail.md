# Transparent Source Trails & Provenance (`source_trail.md` & PROV-JSON)

GAR tracks the full forward and backward provenance chain for every research project through `TrailService` (`src/research_engine/services/trail_service.py`), enforcing **`INV-033`**.

## 1. End-to-End Provenance Chain

Every synthesized finding traces through six persisted entities:

```text
SearchQuery (with leg_outcomes & dropped_legs)
  └──► SearchResult
         └──► Source (canonical_url, source_type, source_tier, content_status)
                └──► Document (cleaned text, content_hash, word_count)
                       └──► DocumentChunk (sequence, page/heading location)
                              └──► Evidence (quote, claim_text, support_verdict, extracted_by, attributes)
                                     └──► Claim (supported_by, contradicted_by, confidence)
```

User answers from the Ask-the-User subsystem (`Phase 5`, `INV-032`) are also recorded in the trail as first-hand `Source` and `Evidence` records with `SourceType.USER_OBSERVATION` at `source_tier=2` (never tier 1) and `extracted_by="user_input"`.

## 2. The Negative Trail (`INV-033`)

To prevent silent survivorship bias, `TrailService.build_trail()` and `reports/source_trail.md` explicitly surface what the engine **rejected, failed to fetch, or dropped**:

1. **Rejected Evidence (`rejected_evidence`)**: Every `Evidence` item marked `REJECTED` by quote verification or claim-support verification (`INV-005`), including the failed quote, `validation_notes`, and `support_verdict`.
2. **Failed, Blocked, or Duplicate Sources (`failed_or_blocked_sources`)**: Sources with `content_status` in `FAILED`, `BLOCKED` (e.g., SSRF/egress policy blocks), or `DUPLICATE`, along with `rejected_reason`.
3. **Failed or Unconfigured Query Legs (`failed_queries`)**: Queries where a provider raised an error (`failed: true`) or where a route leg reported `failed`, `unconfigured`, or `optional_unconfigured` in `leg_outcomes` (`INV-012`, `INV-029`).
4. **Dropped Route Legs (`dropped_route_legs`)**: Planner-requested source preferences outside the closed leg vocabulary or truncated by the 4-leg cap (`_MAX_LEGS`).
5. **Single-Source Claims (`single_source_claims`)**: Material claims supported by fewer than 2 distinct `source_id`s.

## 3. Generated Artifacts

During report synthesis (`ReportGenerator.generate_all`), GAR automatically writes:
- `reports/source_trail.md`: Human-readable Markdown provenance table + Negative Trail audit.
- `exports/trail.prov.json`: Standard **W3C PROV-JSON** graph containing `entity`, `activity`, `agent` (`extracted_by`), `wasGeneratedBy`, `wasDerivedFrom`, `wasAttributedTo`, and `used` relations.

## 4. CLI, REST API & MCP Usage

```bash
# Full project trail JSON
research trail <project_id>

# Lineage for a single claim or single source
research trail <project_id> --claim <claim_id>
research trail <project_id> --source <source_id>

# Export W3C PROV-JSON to <workspace>/exports/trail.prov.json
research trail <project_id> --export prov
```

- **REST API**: `GET /projects/{project_id}/trail` (optional query params `?claim_id=...` or `?source_id=...`)
- **MCP Tool**: `get_source_trail` (`{"project_id": "...", "claim_id": "...", "source_id": "..."}`)
