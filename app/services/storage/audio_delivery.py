"""Shared helpers for streaming stored call/evaluation audio."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.exceptions import StorageError
from app.services.storage.blob_storage_service import blob_storage_service

_CONTENT_TYPE_BY_EXT = {
    "webm": "audio/webm",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
}


def content_type_for_audio_key(key: str, default: str = "audio/wav") -> str:
    extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return _CONTENT_TYPE_BY_EXT.get(extension, default)


def iter_storage_chunks_by_key(key: str, chunk_size: int = 8192) -> Iterator[bytes]:
    yield from blob_storage_service.iter_file_chunks_by_key(key, chunk_size)


def _open_storage_stream(key: str, chunk_size: int = 8192):
    """Validate key is readable and return a generator that replays the first chunk."""
    chunk_iter = iter_storage_chunks_by_key(key, chunk_size)
    try:
        first_chunk = next(chunk_iter)
    except StopIteration:
        return iter(())

    def stream() -> Iterator[bytes]:
        yield first_chunk
        yield from chunk_iter

    return stream()


def stream_audio_from_keys(
    keys: Iterable[str],
    *,
    filename: str,
    default_content_type: str = "audio/wav",
) -> StreamingResponse | None:
    if not blob_storage_service.is_enabled():
        return None

    for key in keys:
        normalized = (key or "").strip()
        if not normalized:
            continue
        try:
            stream = _open_storage_stream(normalized)
            content_type = content_type_for_audio_key(normalized, default_content_type)
            extension = normalized.rsplit(".", 1)[-1].lower() if "." in normalized else "wav"
            return StreamingResponse(
                stream,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'inline; filename="{filename}.{extension}"',
                },
            )
        except StorageError:
            continue
        except Exception:
            continue
    return None


def collect_evaluator_result_audio_keys(result: Any) -> list[str]:
    keys: list[str] = []
    audio_key = getattr(result, "audio_s3_key", None)
    if isinstance(audio_key, str) and audio_key.strip():
        keys.append(audio_key.strip())

    call_data = getattr(result, "call_data", None)
    if isinstance(call_data, dict):
        recording_key = call_data.get("recording_s3_key")
        if isinstance(recording_key, str):
            recording_key = recording_key.strip()
            if recording_key and recording_key not in keys:
                keys.append(recording_key)
    return keys


def collect_call_data_audio_keys(call_data: dict | None) -> list[str]:
    if not isinstance(call_data, dict):
        return []
    keys: list[str] = []
    for field in ("recording_s3_key", "audio_s3_key"):
        value = call_data.get(field)
        if isinstance(value, str):
            value = value.strip()
            if value and value not in keys:
                keys.append(value)
    return keys


def stream_audio_from_provider_url(
    url: str,
    *,
    filename: str,
    headers: Optional[Dict[str, str]] = None,
) -> StreamingResponse:
    """Fetch a provider/presigned recording URL server-side and stream to the client."""
    import requests as http_requests

    from app.services.telephony.exotel_client import ExotelInvalidContentError
    from app.services.telephony.recording_download import assert_safe_provider_recording_url

    try:
        assert_safe_provider_recording_url(str(url))
    except ExotelInvalidContentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    upstream = http_requests.get(url, headers=headers or {}, stream=True, timeout=60)
    if upstream.status_code != 200:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=f"Recording audio fetch failed ({upstream.status_code})",
        )
    content_type = upstream.headers.get("content-type", "audio/mpeg")
    return StreamingResponse(
        upstream.iter_content(chunk_size=8192),
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )
