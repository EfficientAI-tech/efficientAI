"""Build API payloads for in-app knowledge document viewing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.knowledge_bases.extract import extract_text_from_bytes
from app.services.storage.blob_storage_service import blob_storage_service


def _extension(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return "txt"
    return filename.rsplit(".", 1)[-1].lower()


def build_document_view_payload(
    *,
    original_filename: Optional[str],
    content_type: Optional[str],
    blob_key: str,
) -> Dict[str, Any]:
    ext = _extension(original_filename)
    file_bytes = blob_storage_service.download_file_by_key(blob_key)
    ct = (content_type or "").lower()

    if ext in ("txt", "md") or ct.startswith("text/"):
        text = file_bytes.decode("utf-8", errors="replace")
        return {
            "view_mode": "text",
            "original_filename": original_filename,
            "content_type": content_type or "text/plain",
            "text_content": text,
            "pages": None,
        }

    if ext == "pdf" or ct == "application/pdf":
        pages_raw = extract_text_from_bytes(file_bytes, extension="pdf")
        pages: List[Dict[str, Any]] = []
        for page_num, page_text in pages_raw:
            pages.append({"page": page_num, "text": page_text})
        return {
            "view_mode": "pdf",
            "original_filename": original_filename,
            "content_type": content_type or "application/pdf",
            "text_content": None,
            "pages": pages,
            "page_count": len(pages),
        }

    if ext == "docx":
        pages_raw = extract_text_from_bytes(file_bytes, extension="docx")
        combined = "\n\n".join(t for _, t in pages_raw if t)
        return {
            "view_mode": "docx",
            "original_filename": original_filename,
            "content_type": content_type
            or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text_content": combined,
            "pages": None,
        }

    return {
        "view_mode": "binary",
        "original_filename": original_filename,
        "content_type": content_type or "application/octet-stream",
        "text_content": None,
        "pages": None,
    }
