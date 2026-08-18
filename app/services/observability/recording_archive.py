"""Download hosted-provider call recordings into S3 for observability playback."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

import httpx
from loguru import logger

from app.services.audio.voice_quality_service import get_recording_url
from app.services.storage.s3_service import s3_service


def resolve_observability_recording_url(
    call_data: Dict[str, Any],
    provider_platform: str,
) -> Optional[str]:
    """Resolve a downloadable recording URL from normalized provider call_data."""
    platform = (provider_platform or call_data.get("provider_platform") or "").strip().lower()
    url = get_recording_url(call_data, platform)
    if url:
        return str(url).strip() or None

    if platform == "elevenlabs":
        recording_urls = call_data.get("recording_urls")
        if isinstance(recording_urls, dict):
            conversation_audio = recording_urls.get("conversation_audio")
            if isinstance(conversation_audio, str) and conversation_audio.strip():
                return conversation_audio.strip()

        raw_data = call_data.get("raw_data")
        if isinstance(raw_data, dict) and raw_data.get("has_audio"):
            conversation_id = (
                call_data.get("conversation_id")
                or call_data.get("call_id")
                or raw_data.get("conversation_id")
            )
            if conversation_id:
                return f"https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}/audio"

    if platform == "retell":
        multi_channel = call_data.get("recording_multi_channel_url")
        if isinstance(multi_channel, str) and multi_channel.strip():
            return multi_channel.strip()

    return None


def _download_recording_bytes(
    recording_url: str,
    *,
    provider_platform: str,
    provider_api_key: Optional[str] = None,
) -> Tuple[bytes, str]:
    headers: Dict[str, str] = {}
    platform = provider_platform.strip().lower()
    if platform == "elevenlabs" and provider_api_key:
        headers["xi-api-key"] = provider_api_key

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(recording_url, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "audio/mpeg")
        return response.content, content_type


def _extension_for_content_type(content_type: str) -> str:
    lowered = (content_type or "").lower()
    if "wav" in lowered:
        return "wav"
    if "ogg" in lowered:
        return "ogg"
    if "webm" in lowered:
        return "webm"
    if "mpeg" in lowered or "mp3" in lowered:
        return "mp3"
    return "mp3"


def build_observability_recording_s3_key(
    *,
    organization_id: UUID,
    call_short_id: str,
    extension: str,
) -> str:
    normalized_ext = extension.lstrip(".") or "mp3"
    return (
        f"{s3_service.prefix}organizations/{organization_id}/observability/"
        f"{call_short_id}/{uuid.uuid4()}.{normalized_ext}"
    )


def archive_observability_recording_to_s3(
    *,
    call_data: Dict[str, Any],
    provider_platform: str,
    organization_id: UUID,
    call_short_id: str,
    provider_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure call_data contains recording_s3_key by archiving provider audio when possible."""
    if not isinstance(call_data, dict):
        return call_data

    if call_data.get("recording_s3_key"):
        return call_data

    if not s3_service.is_enabled():
        return call_data

    recording_url = resolve_observability_recording_url(call_data, provider_platform)
    if not recording_url:
        return call_data

    try:
        audio_bytes, content_type = _download_recording_bytes(
            recording_url,
            provider_platform=provider_platform,
            provider_api_key=provider_api_key,
        )
    except Exception as exc:
        logger.warning(
            "Observability recording download failed for call_short_id={}: {}",
            call_short_id,
            exc,
        )
        return call_data

    if not audio_bytes:
        return call_data

    extension = _extension_for_content_type(content_type)
    s3_key = build_observability_recording_s3_key(
        organization_id=organization_id,
        call_short_id=call_short_id,
        extension=extension,
    )

    try:
        s3_service.upload_file_by_key(audio_bytes, s3_key, content_type=content_type)
    except Exception as exc:
        logger.warning(
            "Observability recording S3 upload failed for call_short_id={}: {}",
            call_short_id,
            exc,
        )
        return call_data

    updated = dict(call_data)
    updated["recording_s3_key"] = s3_key
    updated.setdefault("recording_url", recording_url)
    updated["recording_source"] = "provider_archive"
    return updated
