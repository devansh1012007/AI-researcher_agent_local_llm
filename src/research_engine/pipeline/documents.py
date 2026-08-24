"""Document processing: fetch -> parse -> chunk -> persist.

Failure isolation: a bad document is marked FAILED and the pipeline continues.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from research_engine.core.config import AppConfig
from research_engine.core.ids import content_hash
from research_engine.models.document import Document
from research_engine.models.enums import ContentStatus, SourceType
from research_engine.pipeline.extraction import extract_content, chunk_document
from research_engine.pipeline.fetching import DocumentFetcher
from research_engine.storage.repositories import Repositories
from research_engine.storage.workspace import Workspace

log = logging.getLogger(__name__)


class DocumentProcessor:
    def __init__(self, cfg: AppConfig, repos: Repositories, workspace: Workspace,
                 fetcher: DocumentFetcher | None = None,
                 transport=None):
        self.cfg = cfg
        self.repos = repos
        self.ws = workspace
        self.fetcher = fetcher or DocumentFetcher(cfg, transport=transport)
        self._dedup_lock = threading.Lock()  # serialize content-hash dedup across workers

    def process_sources(self, project_id: str, sources: list,
                        budget_left: int) -> list[Document]:
        """Fetch+parse up to budget_left sources. Returns successfully created documents."""
        accepted: list = []
        for s in sources:
            # skip obviously hostile/low-value URLs
            if _is_blocked_url(s.url):
                s.content_status = ContentStatus.BLOCKED.value
                s.rejected_reason = "blocked url pattern"
                self.repos.sources.save(s)
        candidates = [s for s in sources if s.content_status == ContentStatus.DISCOVERED.value]
        candidates.sort(key=lambda s: s.source_tier)  # best tiers first
        results: list[Document] = []
        with ThreadPoolExecutor(max_workers=self.cfg.resources.max_parallel_fetches) as pool:
            futures = {pool.submit(self._process_one, project_id, s): s
                       for s in candidates[:max(0, budget_left)]}
            for fut in as_completed(futures):
                try:
                    doc = fut.result()
                    if doc is not None:
                        results.append(doc)
                except Exception as exc:
                    log.exception("document processing crashed (isolated): %s", exc)
        return results

    def _process_one(self, project_id: str, source) -> Document | None:
        ext = "pdf" if source.source_type == SourceType.RESEARCH_PAPER else "html"
        raw_path = self.ws.raw_file_for(source.id, ext)
        fc = self.fetcher.fetch(source.url)
        source.http_status = fc.status
        if not fc.ok:
            source.content_status = ContentStatus.FAILED.value
            source.rejected_reason = fc.error or f"http {fc.status}"
            self.repos.sources.save(source)
            log.info("source failed: %s (%s)", source.url[:80], source.rejected_reason)
            return None
        if fc.is_pdf:
            raw_path = self.ws.raw_file_for(source.id, "pdf")
        self.fetcher.download_to(source.url, raw_path)
        self.repos.documents  # touch for clarity
        doc = Document(project_id=project_id, source_id=source.id, url=source.url,
                       content_type="pdf" if fc.is_pdf else ("html" if fc.is_html else "text"),
                       content_status=ContentStatus.FETCHED.value)
        doc.ensure_id()
        try:
            parsed = extract_content(fc, self.cfg)
        except ValueError as exc:
            source.content_status = ContentStatus.FAILED.value
            source.rejected_reason = str(exc)
            self.repos.sources.save(source)
            return None
        chash = content_hash(parsed.text)
        with self._dedup_lock:
            dup_doc = next(iter(self.repos.documents.all(project_id, "content_hash=?", (chash,))), None)
            if dup_doc is not None:
                # content dedup: syndicated copy of an already-stored document
                source.content_status = ContentStatus.DUPLICATE.value
                source.rejected_reason = f"duplicate content of {dup_doc.id}"
                self.repos.sources.save(source)
                return None
            doc.title = (parsed.title or source.title)[:300]
            doc.text = parsed.text
            doc.content_hash = chash
            doc.raw_content_path = str(raw_path)
            doc.word_count = len(parsed.text.split())
            doc.page_count = len(parsed.pages)
            doc.content_status = ContentStatus.PARSED.value
            self.repos.documents.save(doc)

        chunks = chunk_document(doc, parsed, self.cfg)
        for c in chunks:
            c.project_id = project_id
            c.document_id = doc.id
            c.ensure_id()
            self.repos.chunks.save(c)

        source.content_status = ContentStatus.PARSED.value
        source.content_hash = chash
        source.title = source.title or doc.title
        self.repos.sources.save(source)
        return doc


_BLOCKED_URL_PATTERNS = (
    "facebook.com", "instagram.com", "twitter.com/x.com", "x.com/", "tiktok.com",
    "linkedin.com", "paywall", "sciencedirect.com/science/article/pii" # often paywalled; still allowed via doi
)


def _is_blocked_url(url: str) -> bool:
    u = url.lower()
    return any(p in u for p in (
        "facebook.com", "instagram.com", "tiktok.com", "linkedin.com/login",
    ))
