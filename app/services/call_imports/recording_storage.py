"""Upload call-import recordings via a local file path (one S3 object, duration at ingest)."""

from __future__ import annotations

import os
import tempfile

from app.services.storage.s3_service import s3_service
from app.services.usage.llm_usage import probe_audio_seconds


def upload_local_recording_file(
    path: str,
    *,
    key: str,
    content_type: str,
    size_bytes: int | None = None,
) -> tuple[int, int]:
    """Upload from disk; return (size_bytes, duration_seconds)."""
    if size_bytes is None:
        size_bytes = os.path.getsize(path)
    duration = max(0, int(probe_audio_seconds(path) or 0))
    s3_service.upload_file_by_key_from_path(
        path, key, content_type=content_type or "audio/mpeg"
    )
    return int(size_bytes), duration


def persist_recording_bytes(
    audio_bytes: bytes,
    *,
    key: str,
    content_type: str,
) -> tuple[int, int]:
    """Write bytes to a temp file, probe duration, upload once."""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".audio")
    os.close(tmp_fd)
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(audio_bytes)
        return upload_local_recording_file(
            tmp_path,
            key=key,
            content_type=content_type,
            size_bytes=len(audio_bytes),
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
