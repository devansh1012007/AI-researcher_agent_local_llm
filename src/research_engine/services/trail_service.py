"""Unified Source Trail service, Markdown renderer, and W3C PROV-JSON exporter (Phase 6).

Enforces INV-033:
- Joins the full lineage chain: SearchQuery (with leg_outcomes & dropped_legs) ->
  SearchResult -> Source -> Document -> DocumentChunk -> Evidence -> Claim -> Report.
- Surfaces the Negative Trail: rejected evidence, failed/blocked/duplicate sources,
  failed or unconfigured query legs, dropped route legs, and single-source claims.
- Exports W3C PROV-JSON to exports/trail.prov.json.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from research_engine.models.enums import EvidenceStatus
from research_engine.storage.repositories import Repositories
from research_engine.storage.workspace import Workspace


class TrailService:
    def __init__(self, repos: Repositories, ws: Workspace | None = None, project: Any = None):
        self.repos = repos
        self.ws = ws
        self.project = project

    @classmethod
    def from_repos(cls, repos: Repositories, ws: Workspace | None = None, project: Any = None) -> "TrailService":
        if project is None and ws is not None:
            pid = ws.root.name
            project = repos.projects.get(pid)
        return cls(repos=repos, ws=ws, project=project)

    def _pid(self, project_id: str | None = None) -> str:
        if project_id:
            return project_id
        if self.project is not None:
            return self.project.id
        if self.ws is not None:
            return self.ws.root.name
        raise ValueError("project_id is required")

    def build_trail(self, project_id: str | None = None) -> dict[str, Any]:
        pid = self._pid(project_id)
        proj = self.project or self.repos.projects.get(pid)
        queries = self.repos.queries.all(pid)
        sources = self.repos.sources.all(pid)
        documents = self.repos.documents.all(pid)
        chunks = self.repos.chunks.all(pid)
        evidence = self.repos.evidence.all(pid)
        claims = self.repos.claims.all(pid)
        questions = self.repos.questions.all(pid) if hasattr(self.repos, "questions") else []
        reports = self.repos.reports.all(pid)

        q_by_id = {q.id: q for q in queries}
        src_by_id = {s.id: s for s in sources}
        doc_by_id = {d.id: d for d in documents}
        chk_by_id = {c.id: c for c in chunks}
        ev_by_id = {e.id: e for e in evidence}

        accepted_ev = [e for e in evidence if e.status != EvidenceStatus.REJECTED]
        rejected_ev = [e for e in evidence if e.status == EvidenceStatus.REJECTED]

        # Build claim lineage entries
        claim_trails: list[dict[str, Any]] = []
        single_source_claims: list[dict[str, Any]] = []
        for c in claims:
            sup_items: list[dict[str, Any]] = []
            distinct_sources: set[str] = set()
            for eid in c.supported_by:
                ev = ev_by_id.get(eid)
                if ev is None:
                    continue
                if ev.status != EvidenceStatus.REJECTED and ev.source_id:
                    distinct_sources.add(ev.source_id)
                src = src_by_id.get(ev.source_id)
                doc = doc_by_id.get(ev.document_id)
                chk = chk_by_id.get(ev.chunk_id)
                orig_qids = list(src.query_ids) if src else []
                sup_items.append(
                    {
                        "evidence_id": ev.id,
                        "status": ev.status.value if hasattr(ev.status, "value") else str(ev.status),
                        "quote": ev.quote,
                        "location": ev.location,
                        "extracted_by": ev.extracted_by,
                        "attributes": ev.attributes,
                        "chunk_id": chk.id if chk else ev.chunk_id,
                        "document_id": doc.id if doc else ev.document_id,
                        "source_id": src.id if src else ev.source_id,
                        "source_url": src.canonical_url if src else ev.source_url,
                        "source_tier": src.source_tier if src else ev.source_tier,
                        "query_ids": orig_qids,
                    }
                )
            entry = {
                "claim_id": c.id,
                "text": c.text,
                "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind),
                "confidence": c.confidence,
                "branch": c.branch,
                "distinct_source_count": len(distinct_sources),
                "evidence_chain": sup_items,
            }
            claim_trails.append(entry)
            if len(distinct_sources) < 2:
                single_source_claims.append(
                    {
                        "claim_id": c.id,
                        "text": c.text,
                        "confidence": c.confidence,
                        "distinct_source_count": len(distinct_sources),
                        "source_ids": sorted(distinct_sources),
                    }
                )

        # Negative trail
        failed_sources = [
            {
                "source_id": s.id,
                "url": s.url,
                "status": s.content_status,
                "reason": s.rejected_reason or "fetch/parse failed",
                "query_ids": list(s.query_ids),
            }
            for s in sources
            if s.content_status in ("FAILED", "BLOCKED", "DUPLICATE")
        ]

        failed_queries: list[dict[str, Any]] = []
        dropped_route_legs: list[dict[str, Any]] = []
        for q in queries:
            non_hit_legs = [
                lo for lo in (q.leg_outcomes or [])
                if lo.get("status") in ("failed", "unconfigured", "optional_unconfigured")
            ]
            if q.failed or non_hit_legs:
                failed_queries.append(
                    {
                        "query_id": q.id,
                        "text": q.text,
                        "failed": q.failed,
                        "failure_reason": q.failure_reason,
                        "leg_outcomes": list(q.leg_outcomes or []),
                    }
                )
            if q.dropped_legs:
                dropped_route_legs.append(
                    {
                        "query_id": q.id,
                        "text": q.text,
                        "dropped_legs": list(q.dropped_legs),
                    }
                )

        rejected_evidence_list = [
            {
                "evidence_id": e.id,
                "claim_text": e.claim_text,
                "quote": e.quote,
                "source_id": e.source_id,
                "source_url": e.source_url,
                "validation_notes": e.validation_notes,
                "support_verdict": e.support_verdict,
                "extracted_by": e.extracted_by,
            }
            for e in rejected_ev
        ]

        return {
            "project_id": pid,
            "mode": proj.mode if proj else "",
            "summary": {
                "queries_total": len(queries),
                "queries_executed": sum(1 for q in queries if q.executed),
                "sources_total": len(sources),
                "sources_parsed": sum(1 for s in sources if s.content_status == "PARSED"),
                "sources_failed_or_blocked": len(failed_sources),
                "documents_total": len(documents),
                "chunks_total": len(chunks),
                "evidence_accepted": len(accepted_ev),
                "evidence_rejected": len(rejected_ev),
                "claims_total": len(claims),
                "single_source_claims": len(single_source_claims),
                "questions_total": len(questions),
                "reports_total": len(reports),
            },
            "claims": claim_trails,
            "sources": [
                {
                    "source_id": s.id,
                    "url": s.url,
                    "canonical_url": s.canonical_url,
                    "title": s.title,
                    "domain": s.domain,
                    "source_type": s.source_type.value if hasattr(s.source_type, "value") else str(s.source_type),
                    "source_tier": s.source_tier,
                    "content_status": s.content_status,
                    "query_ids": list(s.query_ids),
                    "evidence_ids": [e.id for e in evidence if e.source_id == s.id],
                }
                for s in sources
            ],
            "queries": [
                {
                    "query_id": q.id,
                    "text": q.text,
                    "branch": q.branch,
                    "kind": q.kind,
                    "executed": q.executed,
                    "results_count": q.results_count,
                    "useful_results": q.useful_results,
                    "failed": q.failed,
                    "leg_outcomes": list(q.leg_outcomes or []),
                    "dropped_legs": list(q.dropped_legs or []),
                }
                for q in queries
            ],
            "negative_trail": {
                "rejected_evidence": rejected_evidence_list,
                "failed_or_blocked_sources": failed_sources,
                "failed_queries": failed_queries,
                "dropped_route_legs": dropped_route_legs,
                "single_source_claims": single_source_claims,
            },
        }

    def trail_for_claim(self, claim_id: str, project_id: str | None = None) -> dict[str, Any]:
        trail = self.build_trail(project_id)
        for c in trail["claims"]:
            if c["claim_id"] == claim_id:
                return c
        raise KeyError(f"claim not found in trail: {claim_id}")

    def trail_for_source(self, source_id: str, project_id: str | None = None) -> dict[str, Any]:
        pid = self._pid(project_id)
        src = self.repos.sources.get(source_id)
        if src is None or src.project_id != pid:
            raise KeyError(f"source not found in trail: {source_id}")
        docs = [d for d in self.repos.documents.all(pid) if d.source_id == source_id]
        doc_ids = {d.id for d in docs}
        chunks = [c for c in self.repos.chunks.all(pid) if c.document_id in doc_ids]
        evs = [e for e in self.repos.evidence.all(pid) if e.source_id == source_id]
        ev_ids = {e.id for e in evs}
        claims = [
            c for c in self.repos.claims.all(pid)
            if any(eid in ev_ids for eid in c.supported_by)
        ]
        queries = [q for q in self.repos.queries.all(pid) if q.id in (src.query_ids or [])]
        return {
            "source_id": src.id,
            "url": src.url,
            "canonical_url": src.canonical_url,
            "title": src.title,
            "domain": src.domain,
            "source_type": src.source_type.value if hasattr(src.source_type, "value") else str(src.source_type),
            "source_tier": src.source_tier,
            "content_status": src.content_status,
            "rejected_reason": src.rejected_reason,
            "queries": [
                {
                    "query_id": q.id,
                    "text": q.text,
                    "leg_outcomes": list(q.leg_outcomes or []),
                    "dropped_legs": list(q.dropped_legs or []),
                }
                for q in queries
            ],
            "documents": [{"document_id": d.id, "word_count": d.word_count, "status": d.content_status} for d in docs],
            "chunks_count": len(chunks),
            "evidence": [
                {
                    "evidence_id": e.id,
                    "claim_text": e.claim_text,
                    "quote": e.quote,
                    "status": e.status.value if hasattr(e.status, "value") else str(e.status),
                    "validation_notes": e.validation_notes,
                    "extracted_by": e.extracted_by,
                    "attributes": e.attributes,
                }
                for e in evs
            ],
            "claims": [{"claim_id": c.id, "text": c.text, "confidence": c.confidence} for c in claims],
        }

    def render_markdown(self, project_id: str | None = None) -> str:
        t = self.build_trail(project_id)
        s = t["summary"]
        neg = t["negative_trail"]
        lines = [
            f"# Source Trail & Provenance Audit — `{t['project_id']}`",
            "",
            f"*Generated {datetime.now(timezone.utc).isoformat()}* · mode `{t['mode']}`",
            "",
            "## Summary",
            f"- Queries executed: **{s['queries_executed']}** / {s['queries_total']}",
            f"- Sources parsed: **{s['sources_parsed']}** / {s['sources_total']} (failed/blocked/duplicate: **{s['sources_failed_or_blocked']}**)",
            f"- Documents & chunks: **{s['documents_total']}** docs · **{s['chunks_total']}** chunks",
            f"- Evidence: **{s['evidence_accepted']}** accepted · **{s['evidence_rejected']}** rejected",
            f"- Claims: **{s['claims_total']}** total · **{s['single_source_claims']}** single-source",
            "",
            "## Claim → Evidence → Source Lineage",
            "",
        ]
        if t["claims"]:
            lines += [
                "| claim | confidence | evidence | source | chunk/loc | queries | extracted by |",
                "|---|---|---|---|---|---|---|",
            ]
            for c in t["claims"][:60]:
                if not c["evidence_chain"]:
                    lines.append(
                        f"| `{c['claim_id']}` {c['text'][:60]} | {c['confidence']:.2f} | (none) | - | - | - | - |"
                    )
                for ev in c["evidence_chain"]:
                    q_str = ",".join(ev["query_ids"]) or "-"
                    lines.append(
                        f"| `{c['claim_id']}` {c['text'][:55]} | {c['confidence']:.2f} "
                        f"| `{ev['evidence_id']}` | `{ev['source_id']}` ({ev['source_url'][:45]}) "
                        f"| `{ev['chunk_id']}` ({ev['location']}) | `{q_str}` | {ev['extracted_by'] or '-'} |"
                    )
            lines.append("")
        else:
            lines.append("_(no claims recorded)_\n")

        lines += [
            "## Negative Trail (What Was Rejected, Blocked, or Dropped)",
            "",
            f"### Rejected Evidence ({len(neg['rejected_evidence'])})",
        ]
        if neg["rejected_evidence"]:
            for r in neg["rejected_evidence"][:40]:
                lines.append(
                    f"- `{r['evidence_id']}` (source `{r['source_id']}`): {r['claim_text'][:90]} "
                    f"— **{r['validation_notes']}** (support={r['support_verdict'] or 'n/a'})"
                )
        else:
            lines.append("- None")

        lines += ["", f"### Failed / Blocked / Duplicate Sources ({len(neg['failed_or_blocked_sources'])})"]
        if neg["failed_or_blocked_sources"]:
            for fs in neg["failed_or_blocked_sources"][:40]:
                lines.append(f"- `{fs['source_id']}` [{fs['status']}] {fs['url'][:80]} — {fs['reason']}")
        else:
            lines.append("- None")

        lines += ["", f"### Failed or Unconfigured Query Legs ({len(neg['failed_queries'])})"]
        if neg["failed_queries"]:
            for fq in neg["failed_queries"][:40]:
                legs = ", ".join(f"{lo.get('leg')}:{lo.get('status')}" for lo in fq["leg_outcomes"])
                lines.append(f"- `{fq['query_id']}` \"{fq['text'][:70]}\" — legs: {legs}")
        else:
            lines.append("- None")

        lines += ["", f"### Dropped Route Legs ({len(neg['dropped_route_legs'])})"]
        if neg["dropped_route_legs"]:
            for dl in neg["dropped_route_legs"][:40]:
                lines.append(
                    f"- `{dl['query_id']}` \"{dl['text'][:70]}\" — dropped: {', '.join(dl['dropped_legs'])}"
                )
        else:
            lines.append("- None")

        lines += ["", f"### Single-Source Claims ({len(neg['single_source_claims'])})"]
        if neg["single_source_claims"]:
            for sc in neg["single_source_claims"][:40]:
                lines.append(
                    f"- `{sc['claim_id']}` (sources={sc['distinct_source_count']}): {sc['text'][:100]}"
                )
        else:
            lines.append("- None")

        lines.append("")
        return "\n".join(lines)

    def export_prov_json(self, project_id: str | None = None) -> dict[str, Any]:
        """Build a valid W3C PROV-JSON document representing the project's full provenance graph."""
        pid = self._pid(project_id)
        queries = self.repos.queries.all(pid)
        sources = self.repos.sources.all(pid)
        documents = self.repos.documents.all(pid)
        chunks = self.repos.chunks.all(pid)
        evidence = self.repos.evidence.all(pid)
        claims = self.repos.claims.all(pid)
        reports = self.repos.reports.all(pid)

        entities: dict[str, Any] = {}
        activities: dict[str, Any] = {}
        agents: dict[str, Any] = {
            "gar:harness": {"prov:type": "prov:SoftwareAgent", "gar:project_id": pid}
        }
        was_generated_by: dict[str, Any] = {}
        was_derived_from: dict[str, Any] = {}
        was_attributed_to: dict[str, Any] = {}
        used: dict[str, Any] = {}

        for q in queries:
            qid = f"gar:{q.id}"
            act_id = f"gar:search_{q.id}"
            entities[qid] = {
                "prov:type": "gar:SearchQuery",
                "gar:text": q.text,
                "gar:executed": q.executed,
                "gar:dropped_legs": list(q.dropped_legs or []),
            }
            activities[act_id] = {
                "prov:type": "gar:SearchActivity",
                "gar:iteration": q.iteration,
            }
            used[f"_:u_{q.id}"] = {"prov:activity": act_id, "prov:entity": qid}

        for s in sources:
            sid = f"gar:{s.id}"
            entities[sid] = {
                "prov:type": "gar:Source",
                "gar:url": s.canonical_url or s.url,
                "gar:tier": s.source_tier,
                "gar:status": s.content_status,
            }
            for q_ref in s.query_ids or []:
                was_derived_from[f"_:d_{s.id}_{q_ref}"] = {
                    "prov:generatedEntity": sid,
                    "prov:usedEntity": f"gar:{q_ref}",
                }

        for d in documents:
            did = f"gar:{d.id}"
            entities[did] = {
                "prov:type": "gar:Document",
                "gar:source_id": d.source_id,
                "gar:word_count": d.word_count,
            }
            if d.source_id:
                was_derived_from[f"_:d_{d.id}_{d.source_id}"] = {
                    "prov:generatedEntity": did,
                    "prov:usedEntity": f"gar:{d.source_id}",
                }

        for chk in chunks:
            cid = f"gar:{chk.id}"
            entities[cid] = {
                "prov:type": "gar:DocumentChunk",
                "gar:document_id": chk.document_id,
                "gar:sequence": chk.sequence,
            }
            if chk.document_id:
                was_derived_from[f"_:d_{chk.id}_{chk.document_id}"] = {
                    "prov:generatedEntity": cid,
                    "prov:usedEntity": f"gar:{chk.document_id}",
                }

        for ev in evidence:
            eid = f"gar:{ev.id}"
            entities[eid] = {
                "prov:type": "gar:Evidence",
                "gar:status": ev.status.value if hasattr(ev.status, "value") else str(ev.status),
                "gar:claim_text": ev.claim_text,
                "gar:support_verdict": ev.support_verdict,
                "gar:attributes": ev.attributes,
            }
            agent_key = f"gar:agent_{ev.extracted_by or 'default'}"
            agents[agent_key] = {
                "prov:type": "prov:SoftwareAgent",
                "gar:extractor": ev.extracted_by or "default",
            }
            was_attributed_to[f"_:a_{ev.id}"] = {
                "prov:entity": eid,
                "prov:agent": agent_key,
            }
            if ev.chunk_id:
                was_derived_from[f"_:d_{ev.id}_{ev.chunk_id}"] = {
                    "prov:generatedEntity": eid,
                    "prov:usedEntity": f"gar:{ev.chunk_id}",
                }
            elif ev.source_id:
                was_derived_from[f"_:d_{ev.id}_{ev.source_id}"] = {
                    "prov:generatedEntity": eid,
                    "prov:usedEntity": f"gar:{ev.source_id}",
                }

        for clm in claims:
            clid = f"gar:{clm.id}"
            entities[clid] = {
                "prov:type": "gar:Claim",
                "gar:text": clm.text,
                "gar:confidence": clm.confidence,
            }
            for sup_ev in clm.supported_by:
                was_derived_from[f"_:d_{clm.id}_{sup_ev}"] = {
                    "prov:generatedEntity": clid,
                    "prov:usedEntity": f"gar:{sup_ev}",
                }

        for rep in reports:
            rid = f"gar:{rep.id}"
            entities[rid] = {
                "prov:type": "gar:Report",
                "gar:path": rep.path,
                "gar:kind": rep.kind,
            }
            was_generated_by[f"_:g_{rep.id}"] = {
                "prov:entity": rid,
                "prov:activity": "gar:synthesis",
            }
        if reports:
            activities["gar:synthesis"] = {"prov:type": "gar:SynthesisActivity"}

        return {
            "prefix": {
                "prov": "http://www.w3.org/ns/prov#",
                "gar": "https://gar.local/ns#",
            },
            "entity": entities,
            "activity": activities,
            "agent": agents,
            "wasGeneratedBy": was_generated_by,
            "wasDerivedFrom": was_derived_from,
            "wasAttributedTo": was_attributed_to,
            "used": used,
        }
