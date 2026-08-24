"""Graph builder: derives the research graph from stored claims/evidence/sources.

Runs after each research cycle. Deterministic; never invents relationships —
edges come from co-occurrence in evidence, explicit metadata (papers, benchmarks),
or LLM-proposed links validated against entity existence.
"""
from __future__ import annotations

import logging
import re

from research_engine.models.enums import EvidenceStatus
from research_engine.storage.graph_store import GraphEntity, GraphStore, Relationship
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

# capitalized multi-word phrases & known proper nouns are candidate concepts
_CANDIDATE_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:[- ][A-Z][a-zA-Z0-9]+){0,3})\b")
_NOISE = {
    "The", "This", "These", "Those", "We", "Our", "It", "Its", "In", "On", "For",
    "Results", "Table", "Figure", "Section", "Abstract", "Introduction", "Conclusion",
    "Method", "Methods", "Dataset", "Benchmark", "Experiment", "Experiments", "Related Work",
}


class GraphBuilder:
    def __init__(self, repos: Repositories, graph: GraphStore):
        self.repos = repos
        self.graph = graph

    def rebuild(self, project_id: str) -> dict:
        stats = {"entities": 0, "relationships": 0}
        evidence = [e for e in self.repos.evidence.all(project_id)
                    if e.status != EvidenceStatus.REJECTED]
        sources = {s.id: s for s in self.repos.sources.all(project_id)}

        for ev in evidence:
            # source node per accepted source
            src = sources.get(ev.source_id)
            if src is not None:
                type_ = ("paper" if src.source_type.value == "research_paper" else "source")
                s_ent = self.graph.upsert_entity(GraphEntity(
                    project_id=project_id, type=type_,
                    name=src.title or src.canonical_url,
                    attributes={"url": src.url, "tier": src.source_tier,
                                "published": src.publication_date,
                                "citations": src.citation_count,
                                "venue": src.publisher, "doi": src.doi}))
                # evidence -> source provenance edge
                self.graph.add_relationship(Relationship(
                    project_id=project_id, source_id=ev.id, target_id=s_ent.id,
                    relationship_type="extracted_from", confidence=1.0,
                    evidence_ids=[ev.id]))
                stats["entities"] += 1
                stats["relationships"] += 1
                # paper metadata edges: uses-dataset / benchmarks-method from tags
                self._link_paper_metadata(project_id, s_ent.id, ev)
                stats["relationships"] += self._link_concepts(project_id, ev, s_ent.id)

        # claim <-> evidence edges already live in Claim.supported_by, but mirror them
        for c in self.repos.claims.all(project_id):
            for eid in c.supported_by:
                self.graph.add_relationship(Relationship(
                    project_id=project_id, source_id=c.id, target_id=eid,
                    relationship_type="supports_claim", confidence=c.confidence,
                    evidence_ids=[eid]))
                stats["relationships"] += 1

        # existing contradictions as edges
        for con in self.repos.contradictions.all(project_id):
            self.graph.add_relationship(Relationship(
                project_id=project_id, source_id=con.claim_a_id,
                target_id=con.claim_b_id, relationship_type="contradicts",
                confidence=0.8, notes=con.explanation[:200]))
            stats["relationships"] += 1
        return stats

    def _link_paper_metadata(self, project_id, paper_ent_id, ev) -> int:
        n = 0
        attrs = {}
        # benchmark/dataset mentions recorded by the extractor in tags/numbers context
        for tag in ev.tags:
            tl = tag.lower()
            if any(k in tl for k in ("dataset", "benchmark", "corpus")):
                ent = self.graph.upsert_entity(GraphEntity(
                    project_id=project_id, type="benchmark", name=tag))
                self.graph.add_relationship(Relationship(
                    project_id=project_id, source_id=paper_ent_id, target_id=ent.id,
                    relationship_type="evaluated_on",
                    evidence_ids=[ev.id], confidence=ev.confidence))
                n += 1
        return n

    def _link_concepts(self, project_id, ev, source_ent_id) -> int:
        """Link capitalized candidate concepts mentioned in the claim text."""
        seen: set[str] = set()
        n = 0
        for m in _CANDIDATE_RE.finditer(ev.claim_text + " " + " ".join(ev.entities)):
            cand = m.group(1)
            if cand in _NOISE or cand.lower() in seen or len(cand.split()) > 4:
                continue
            seen.add(cand.lower())
            if len(cand) < 4:
                continue
            ent = self.graph.upsert_entity(GraphEntity(
                project_id=project_id, type="concept", name=cand))
            rel = self.graph.find_relationship(project_id, source_ent_id, ent.id,
                                               "mentions") 
            if rel is None:
                self.graph.add_relationship(Relationship(
                    project_id=project_id, source_id=source_ent_id, target_id=ent.id,
                    relationship_type="mentions", evidence_ids=[ev.id],
                    confidence=ev.confidence))
            else:
                rel.evidence_ids = list(set(rel.evidence_ids + [ev.id]))
                self.graph.add_relationship(rel)
            n += 1
        return n
