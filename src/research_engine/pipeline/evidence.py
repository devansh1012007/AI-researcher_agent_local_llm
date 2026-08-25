"""Evidence extraction + validation + multi-level deduplication.

Anti-hallucination core:
- LLM proposes evidence; the harness verifies quotes against chunk text.
- Evidence failing quote verification is REJECTED and counted, never silently kept.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from research_engine.core.config import AppConfig
from research_engine.models.document import DocumentChunk
from research_engine.models.enums import ClaimKind, EvidenceStatus, SourceType
from research_engine.models.evidence import Claim, Evidence, NumericFact
from research_engine.pipeline.claim_support import (
    status_for_support as _status_for_support)
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class _NumberOut(BaseModel):
    metric: str = ""
    value_raw: str = ""
    unit: str = ""
    currency: str = ""
    period: str = ""
    context: str = ""


class _EvidenceOut(BaseModel):
    claim: str = ""
    quote: str = ""
    confidence: float = 0.5
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    kind: str = "FACT"
    numbers: list[_NumberOut] = Field(default_factory=list)


class ExtractionOutput(BaseModel):
    evidence: list[_EvidenceOut] = Field(default_factory=list)


# -- quote verification (deterministic) --------------------------------------

def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote: str, chunk_text: str, min_ratio: float = 0.88) -> tuple[bool, str]:
    """Quote must appear in the chunk (normalized) or be a near-exact match.

    Supports multi-part quotes joined by '...'; each part must be verifiable.
    """
    if not quote.strip():
        return False, "empty quote"
    if len(_norm(quote)) < 15:
        return False, "quote too short"
    t = _norm(chunk_text)
    tw = t.split()
    parts = [p for p in re.split(r"\.\.\.|…", quote) if len(_norm(p)) >= 15] or [quote]
    matched_exact = True
    best_overall = 1.0
    for p in parts:
        pn = _norm(p)
        if pn in t:
            continue
        matched_exact = False
        pw = pn.split()
        n = len(pw)
        best = 0.0
        step = max(5, n // 4)
        end = max(1, len(tw) - min(n, len(tw)) + 1)
        for start in range(0, end, step):
            window = " ".join(tw[start : start + n + 8])
            ratio = SequenceMatcher(None, pn, window).ratio()
            best = max(best, ratio)
            if best >= min_ratio:
                break
        best_overall = min(best_overall, best)
    if matched_exact:
        return True, "exact"
    if best_overall >= min_ratio:
        return True, f"fuzzy {best_overall:.2f}"
    return False, f"quote not found in chunk (best similarity {best_overall:.2f})"


# -- claim dedup --------------------------------------------------------------

def claim_dedup_key(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2]
    return " ".join(sorted(set(words)))


def claims_equivalent(a: str, b: str, threshold: float = 0.86) -> bool:
    ka, kb = claim_dedup_key(a), claim_dedup_key(b)
    if ka == kb:
        return True
    return SequenceMatcher(None, ka, kb).ratio() >= threshold


# -- worker -------------------------------------------------------------------

class EvidenceWorker:
    def __init__(self, cfg: AppConfig, provider: LLMProvider, repos: Repositories):
        self.cfg = cfg
        self.provider = provider
        self.repos = repos

    def extract_from_documents(self, project_id: str, documents: list,
                               questions: str, branch_by_doc=None, iteration: int = 0
                               ) -> tuple[list[Evidence], int]:
        """Extract evidence from document chunks (LLM-bound; serialized).

        Returns (new_evidence, llm_calls_used).
        """
        schema_hint = ("claim, quote(exact), confidence, entities, tags, "
                       "kind(FACT|INFERENCE|ASSUMPTION), numbers[{metric,value_raw,unit,currency,period,context}]")
        created: list[Evidence] = []
        rejected = 0
        for doc in documents:
            source = self.repos.sources.get(doc.source_id)
            chunks = self.repos.chunks.for_document(project_id, doc.id)
            for chunk in chunks:
                evs, rej = self._extract_chunk(project_id, doc.id, source, chunk,
                                               questions, schema_hint, iteration)
                created.extend(evs)
                rejected += rej
        return created, rejected

    def _extract_chunk(self, project_id, document_id, source, chunk: DocumentChunk,
                       questions: str, schema_hint: str, iteration: int):
        spec = get_prompt("evidence_extractor")
        location = f"page {chunk.page}" if chunk.page else (chunk.heading or "document body")
        user = spec.render(source_title=(source.title if source else "")[:200],
                           location=location, page=str(chunk.page or ""),
                           questions=questions[:1500], schema_hint=schema_hint,
                           chunk_text=chunk.text)
        out, errors = self.provider.structured(spec.system, user, ExtractionOutput)
        created, rejected = [], 0
        if out is None:
            log.warning("extraction failed for %s: %s", chunk.id, errors[-1:])
            return created, rejected
        for item in out.evidence:
            ok, why = verify_quote(item.quote, chunk.text)
            status = EvidenceStatus.EXTRACTED if ok else EvidenceStatus.REJECTED
            # INVARIANT-005: quote existence is necessary, not sufficient.
            # Verify the claim text is actually supported by the quoted
            # passage before it can enter grounded synthesis.
            support = None
            if ok:
                from research_engine.pipeline.claim_support import (
                    verify_claim_support as _vcs)
                support = _vcs(item.claim, item.quote)
                status = _status_for_support(status, support.verdict)
            ev = Evidence(
                project_id=project_id,
                claim_text=item.claim.strip(),
                quote=item.quote.strip(),
                source_id=source.id if source else "",
                document_id=document_id,
                chunk_id=chunk.id,
                location=f"{location}; chunk {chunk.sequence}",
                source_url=source.canonical_url if source else "",
                source_title=(source.title if source else "")[:300],
                source_type=source.source_type if source else SourceType.OTHER,
                source_tier=source.source_tier if source else 5,
                published_date=source.publication_date if source else None,
                retrieved_at=source.retrieval_date if source else "",
                entities=[e[:100] for e in item.entities[:10]],
                numbers=[NumericFact(metric=n.metric, value_raw=n.value_raw, unit=n.unit,
                                     currency=n.currency, period=n.period, context=n.context,
                                     project_id=project_id) for n in item.numbers[:6]],
                tags=[t[:40] for t in item.tags[:8]],
                confidence=min(max(item.confidence, 0.0), 1.0),
                status=status,
                kind=_safe_kind(item.kind),
                iteration=iteration,
                validation_notes=why,
                support_verdict=(support.verdict if support else ""),
                support_score=(support.score if support else -1.0),
                support_reasons=(support.reasons[:5] if support else []),
            )
            if not ev.claim_text:
                continue
            if status == EvidenceStatus.REJECTED:
                rejected += 1
                reason = ("quote unverifiable" if not ok
                          else f"unsupported claim ({ev.support_verdict})")
                log.info("rejected evidence (%s): %s...", reason,
                         ev.claim_text[:60])
                # store rejected items too — audit trail requires seeing what was thrown away
            ev.ensure_id()
            self.repos.evidence.save(ev)
            created.append(ev)
        return created, rejected

    def consolidate_claims(self, project_id: str, new_evidence: list[Evidence],
                           iteration: int) -> tuple[int, int]:
        """Attach evidence to claims (creating/deduping claims). Returns (new_claims, dup_claims)."""
        existing_claims = self.repos.claims.all(project_id)
        new_count, dup_count = 0, 0
        for ev in new_evidence:
            if ev.status == EvidenceStatus.REJECTED:
                continue
            match = next((c for c in existing_claims
                          if claims_equivalent(c.text, ev.claim_text)), None)
            if match is None:
                match = Claim(project_id=project_id, text=ev.claim_text, kind=ev.kind,
                              branch=ev.branch, dedup_key=claim_dedup_key(ev.claim_text),
                              iteration=iteration)
                match.ensure_id()
                self.repos.claims.save(match)
                existing_claims.append(match)
                new_count += 1
            elif ev.kind == ClaimKind.FACT and match.kind != ClaimKind.FACT:
                pass  # never upgrade inference/assumption claims to fact silently
            if ev.id not in match.supported_by:
                match.supported_by.append(ev.id)
                self.repos.claims.save(match)
            ev.supports = [match.id]
            self.repos.evidence.save(ev)
        # recompute claim confidences from supporting evidence quality
        all_ev = {e.id: e for e in self.repos.evidence.all(project_id)}
        tier_weight = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4, 5: 0.25}
        for c in existing_claims:
            sup = [all_ev[eid] for eid in c.supported_by if eid in all_ev]
            if not sup:
                c.confidence = 0.0
            else:
                base = max(tier_weight.get(e.source_tier, 0.25) * e.confidence for e in sup)
                corr = min(1.0, base * (1 + 0.12 * (len(sup) - 1)))
                contra = len([e for e in sup if e.status == EvidenceStatus.CONTRADICTED])
                c.confidence = round(max(0.0, corr - 0.15 * contra), 3)
            self.repos.claims.save(c)
        return new_count, dup_count


def _safe_kind(k: str) -> ClaimKind:
    return {"FACT": ClaimKind.FACT, "INFERENCE": ClaimKind.INFERENCE,
            "ASSUMPTION": ClaimKind.ASSUMPTION}.get((k or "").upper(), ClaimKind.FACT)
