"""Blob key helpers for knowledge base uploads."""

from __future__ import annotations

from typing import Any
from uuid import UUID


ALLOWED_KB_EXTENSIONS = frozenset({"pdf", "txt", "md", "docx"})
MAX_KB_UPLOAD_BYTES = 25 * 1024 * 1024


def knowledge_document_blob_key(
    organization_id: Any,
    workspace_id: Any,
    knowledge_base_id: Any,
    document_id: Any,
    extension: str,
) -> str:
    from app.services.storage.s3_service import s3_service

    ext = extension.lower().lstrip(".")
    return (
        f"{s3_service.prefix}organizations/{organization_id}/workspaces/{workspace_id}/"
        f"knowledge-bases/{knowledge_base_id}/documents/{document_id}.{ext}"
    )


def validate_kb_upload_filename(filename: str) -> tuple[str, str]:
    name = (filename or "").strip()
    if not name or "." not in name:
        raise ValueError("Filename must include an extension")
    ext = name.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_KB_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_KB_EXTENSIONS))}"
        )
    content_types = {
        "pdf": "application/pdf",
        "txt": "text/plain",
        "md": "text/markdown",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return ext, content_types.get(ext, "application/octet-stream")
