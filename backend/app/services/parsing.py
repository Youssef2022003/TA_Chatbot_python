"""PDF -> text/markdown. Docling primary (best free scientific parser: layout,
tables, formulas -> LaTeX), PyMuPDF fallback for fast digital text (handoff §5).

Returns (text, is_markdown). When markdown, the chunker uses ATX headings / pipe
tables for structure; otherwise it uses heuristics. Pages are joined with form-feed
(\\f) so the chunker can recover page numbers, matching v1.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings

log = logging.getLogger("physicsta.parsing")


def _has_text(s: str) -> bool:
    return bool(s) and len(s.replace(" ", "").replace("\n", "").replace("\f", "")) > 20


async def extract_document(file_path: str, file_name: str) -> tuple[str, bool]:
    # 1. Mistral OCR (cloud, free tier) — best for physics: Markdown + LaTeX, fast,
    # one server-side call for the whole PDF, real per-page \f boundaries.
    if settings.mistral_api_key:
        try:
            md = await asyncio.to_thread(_mistral_ocr_markdown, file_path, file_name)
            if _has_text(md):
                log.info("Extracted via Mistral OCR (markdown): %d chars", len(md))
                return md, True
            log.warning("Mistral OCR returned little/no text — falling back")
        except Exception as e:  # noqa: BLE001
            log.warning("Mistral OCR failed (%s) — falling back", e)

    # 2. Docling (local) — structured markdown, OCRs scanned pages (slow on CPU).
    if settings.use_docling:
        try:
            md = await asyncio.to_thread(_docling_markdown, file_path)
            if _has_text(md):
                log.info("Extracted via Docling (markdown): %d chars", len(md))
                return md, True
            log.warning("Docling returned little/no text — falling back to PyMuPDF")
        except Exception as e:  # noqa: BLE001
            log.warning("Docling failed (%s) — falling back to PyMuPDF", e)

    # 3. PyMuPDF — fast digital text (no OCR; fails on scanned PDFs).
    text = await asyncio.to_thread(_pymupdf_text, file_path)
    if len(text.replace(" ", "").replace("\n", "").replace("\f", "")) < 20:
        raise ValueError(
            "No extractable text found. The PDF may be empty or an unsupported scan. "
            "Enable Docling/OCR (USE_DOCLING=true) for scanned documents."
        )
    log.info("Extracted via PyMuPDF (plain): %d chars", len(text))
    return text, False


def _mistral_ocr_markdown(file_path: str, file_name: str) -> str:
    """Mistral OCR (cloud) -> per-page Markdown with LaTeX equations + tables.

    Uploads the PDF, OCRs it in one server-side call, joins page markdowns with \\f
    so the chunker recovers real page numbers, then deletes the uploaded file. Far
    better on physics notation than local OCR, and fast (handoff §5; v1 parity).
    """
    from mistralai import Mistral

    client = Mistral(api_key=settings.mistral_api_key)
    with open(file_path, "rb") as fh:
        content = fh.read()

    uploaded = client.files.upload(file={"file_name": file_name, "content": content}, purpose="ocr")
    try:
        signed = client.files.get_signed_url(file_id=uploaded.id)
        resp = client.ocr.process(
            model=settings.mistral_ocr_model,
            document={"type": "document_url", "document_url": signed.url},
        )
        pages = [(getattr(p, "markdown", "") or "") for p in (resp.pages or [])]
        return "\f".join(pages)
    finally:
        try:
            client.files.delete(file_id=uploaded.id)
        except Exception:  # noqa: BLE001 - cleanup best-effort
            pass


def _docling_markdown(file_path: str) -> str:
    """Docling -> structured Markdown (headings/tables/LaTeX), processed in page
    batches so peak memory stays bounded on large scanned books (the std::bad_alloc
    fix). Pages are joined with \\f so the chunker recovers real page numbers; a
    page that still fails OCR is skipped, not fatal.
    """
    import gc

    import fitz  # PyMuPDF — just for the page count
    from docling.document_converter import DocumentConverter  # lazy, heavy

    with fitz.open(file_path) as doc:
        n_pages = doc.page_count

    converter = DocumentConverter()
    batch = max(1, settings.docling_page_batch)
    pages_md: list[str] = []
    for start in range(1, n_pages + 1, batch):
        end = min(start + batch - 1, n_pages)
        try:
            result = converter.convert(file_path, page_range=(start, end))
            pages_md.append(result.document.export_to_markdown())
        except Exception as e:  # noqa: BLE001 - one bad page must not sink the doc
            log.warning("Docling failed on pages %d-%d (%s) — skipping", start, end, e)
            pages_md.append("")
        finally:
            gc.collect()
    return "\f".join(pages_md)


def _pymupdf_text(file_path: str) -> str:
    """Fast digital-text extraction. Pages joined with \\f for page-number tracking."""
    import fitz  # PyMuPDF

    parts: list[str] = []
    with fitz.open(file_path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\f".join(parts)
