"""Workspace ambient noise library helpers."""

from __future__ import annotations

import re
from typing import Any, Optional
from uuid import UUID, uuid4

from app.services.audio.ambient_mixer import decode_audio_bytes_to_pcm_int16
from app.services.personas.persona_ambient_noise import (
    ALLOWED_AMBIENT_EXTENSIONS,
    MAX_AMBIENT_UPLOAD_BYTES,
    ambient_upload_size_error_message,
)


def sanitize_ambient_name(name: Optional[str], fallback: str) -> str:
    raw = (name or fallback or "Ambient bed").strip()
    cleaned = re.sub(r"\s+", " ", raw)
    return cleaned[:255] or "Ambient bed"


def ambient_library_s3_key(organization_id: Any, asset_id: Any, extension: str) -> str:
    from app.services.storage.s3_service import s3_service

    ext = extension.lower().lstrip(".")
    return (
        f"{s3_service.prefix}organizations/{organization_id}/ambient-library/"
        f"{asset_id}.{ext}"
    )


def validate_ambient_upload_bytes(file_bytes: bytes, *, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_AMBIENT_EXTENSIONS:
        raise ValueError(
            f"Unsupported ambient audio format. Allowed: {', '.join(sorted(ALLOWED_AMBIENT_EXTENSIONS))}"
        )
    if not file_bytes:
        raise ValueError("Uploaded file is empty")
    if len(file_bytes) > MAX_AMBIENT_UPLOAD_BYTES:
        raise ValueError(ambient_upload_size_error_message())
    try:
        decode_audio_bytes_to_pcm_int16(file_bytes, 16000)
    except Exception as exc:
        raise ValueError(f"Could not decode ambient audio file: {exc}") from exc
    return extension


def new_ambient_asset_id() -> UUID:
    return uuid4()
