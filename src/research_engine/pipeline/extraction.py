"""Content extraction: raw bytes -> normalized text -> deterministic chunks.

HTML: trafilatura main-content extraction (fallback to BeautifulSoup-free regex strip).
PDF:  pypdf with per-page text and page numbers preserved.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

from research_engine.core.config import AppConfig
from research_engine.models.document import Document, DocumentChunk

log = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    title: str
    text: str
    pages: list[tuple[int, str]]   # (page_number, page_text); empty for non-paginated


def parse_html(body: bytes) -> ParsedDocument:
    try:
        import trafilatura
        downloaded = body.decode("utf-8", errors="replace")
        text = trafilatura.extract(downloaded, include_comments=False,
                                   include_tables=True, favor_recall=True) or ""
        if not text:
            # last-resort: strip tags
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", downloaded,
                          flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", unescape_html(text)).strip()
        m = re.search(r"<title[^>]*>(.*?)</title>", downloaded, re.DOTALL | re.IGNORECASE)
        title = unescape_html(m.group(1)).strip() if m else ""
        return ParsedDocument(title=title, text=text, pages=[])
    except Exception as exc:
        log.warning("html parse failed: %s", exc)
        return ParsedDocument(title="", text="", pages=[])


def parse_pdf(body: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(body))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                pages.append((i, page.extract_text() or ""))
            except Exception:
                pages.append((i, ""))
        first_page_head = pages[0][1][:300] if pages else ""
        title_guess = first_page_head.split("\n")[0].strip()[:200]
        full_text = "\n\n".join(t for _, t in pages)
        return ParsedDocument(title=title_guess, text=full_text, pages=pages)
    except Exception as exc:
        raise ValueError(f"pdf parse failed: {exc}") from exc


def parse_plain(body: bytes) -> ParsedDocument:
    return ParsedDocument(title="", text=body.decode("utf-8", errors="replace"), pages=[])


def unescape_html(s: str) -> str:
    from html import unescape
    return unescape(s)


def extract_content(fc, cfg: AppConfig) -> ParsedDocument:
    """Dispatch on content type."""
    max_chars = cfg.resources.max_context_chars * 4  # generous cap per document
    if fc.is_pdf:
        parsed = parse_pdf(fc.body)
    elif fc.is_html:
        parsed = parse_html(fc.body)
    else:
        parsed = parse_plain(fc.body)
    if len(parsed.text) > max_chars:
        parsed.text = parsed.text[:max_chars]
    return parsed


# ---------------------------------------------------------------------------
# Deterministic chunking — never an LLM decision.
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(?:#{1,6}\s+.{3,120}|[A-Z][A-Z0-9 ,\-/&]{8,80})$")


def chunk_document(doc: Document, parsed: ParsedDocument, cfg: AppConfig) -> list[DocumentChunk]:
    """Split into heading-aware chunks with bounded size and small overlap."""
    size = cfg.resources.max_chunk_chars
    overlap = cfg.resources.chunk_overlap_chars
    chunks: list[DocumentChunk] = []

    def _emit(text_block: str, heading: str, page: int | None) -> None:
        text_block = text_block.strip()
        while text_block:
            piece = text_block[:size]
            chunks.append(DocumentChunk(
                project_id=doc.project_id, document_id=doc.id or "", sequence=len(chunks),
                text=piece, heading=heading[:200], page=page,
                char_start=0, char_end=len(piece),
            ))
            if len(text_block) <= size:
                break
            text_block = text_block[size - overlap:]

    if parsed.pages:
        current_heading = doc.title or ""
        for page_no, page_text in parsed.pages:
            for para in _split_paragraphs(page_text):
                if _HEADING_RE.match(para.strip()):
                    current_heading = para.strip()
                    continue
                _emit(para, current_heading, page_no)
    else:
        current_heading = doc.title or ""
        for para in _split_paragraphs(parsed.text):
            if para.startswith("#") or _HEADING_RE.match(para.strip()):
                current_heading = para.lstrip("#").strip()
                continue
            _emit(para, current_heading, None)
    return [c for c in chunks if len(c.text.split()) >= 20]  # drop trivial fragments


def _split_paragraphs(text: str) -> list[str]:
    paras = re.split(r"\n\s*\n|\r\n\s*\r\n", text)
    return [re.sub(r"[ \t]+", " ", p).strip() for p in paras if p.strip()]
