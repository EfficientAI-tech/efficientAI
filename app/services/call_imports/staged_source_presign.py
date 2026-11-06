"""Presigned PUT for staged CSV/Excel call-import sources."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status


def validate_staged_source_file(
    filename: str,
    size_bytes: int,
    *,
    file_format,
    max_upload_bytes: int,
) -> str:
    fmt = file_format(filename)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format for staged import.",
        )
    if size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="size_bytes must be positive.",
        )
    if size_bytes > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {max_upload_bytes} bytes",
        )
    return fmt


def build_staged_source_presign(
    *,
    organization_id: UUID,
    call_import_id: UUID,
    fmt: str,
    content_type: str,
    source_s3_key: Callable[[UUID, UUID, str], str],
    generate_presigned_put_url_by_key,
    expiration: int = 3600,
) -> Tuple[str, str]:
    key = source_s3_key(organization_id, call_import_id, fmt)
    upload_url = generate_presigned_put_url_by_key(
        key,
        content_type=content_type,
        expiration=expiration,
    )
    return key, upload_url


def load_staged_source_bytes(
    *,
    source_s3_key: str,
    expected_size: Optional[int],
    head_object_by_key,
    download_file_by_key,
) -> bytes:
    meta = head_object_by_key(source_s3_key)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Staged source file was not found in storage.",
        )
    stored_size = int(meta.get("ContentLength") or 0)
    if stored_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Staged source file is empty.",
        )
    if expected_size is not None and expected_size > 0 and stored_size != expected_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Staged file size does not match the declared upload size. "
                "Retry the upload."
            ),
        )
    return download_file_by_key(source_s3_key)


def sheets_snapshot_from_bytes(
    file_bytes: bytes,
    fmt: str,
    filename: Optional[str],
    *,
    build_available_sheets,
) -> List[Dict[str, Any]]:
    sheets = build_available_sheets(file_bytes, fmt, filename)
    return [sheet.model_dump() for sheet in sheets]
