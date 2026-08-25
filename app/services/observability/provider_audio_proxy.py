"""Provider-hosted audio proxy helpers for observability/playground playback."""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional
from uuid import UUID

from fastapi import HTTPException
from fastapi import status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import Agent, CallRecording, Integration
from app.services.observability.recording_url_safety import (
    assert_elevenlabs_recording_url,
    download_elevenlabs_recording_bytes,
)
from app.services.telephony.exotel_client import ExotelInvalidContentError


def resolve_elevenlabs_audio_url(call_data: Dict[str, Any]) -> Optional[str]:
    recording_urls = call_data.get("recording_urls")
    if isinstance(recording_urls, dict):
        conversation_audio = recording_urls.get("conversation_audio")
        if isinstance(conversation_audio, str) and conversation_audio.strip():
            return conversation_audio.strip()
    for key in ("recording_url", "recordingUrl"):
        value = call_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def stream_elevenlabs_audio_proxy(
    *,
    db: Session,
    organization_id: UUID,
    call_recording: CallRecording,
    call_data: Dict[str, Any],
    filename_prefix: str = "call",
) -> StreamingResponse:
    """Proxy ElevenLabs conversation audio by injecting provider auth header."""
    audio_url = resolve_elevenlabs_audio_url(call_data)
    if not audio_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recording URL available",
        )

    try:
        assert_elevenlabs_recording_url(audio_url)
    except ExotelInvalidContentError as exc:
        logger.warning(
            "Blocked ElevenLabs audio proxy for call_short_id={}: {}",
            call_recording.call_short_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recording URL is not allowed for provider proxy",
        ) from exc

    agent = db.query(Agent).filter(Agent.id == call_recording.agent_id).first()
    if not agent or not agent.voice_ai_integration_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent or integration not found",
        )

    integration = (
        db.query(Integration)
        .filter(
            Integration.id == agent.voice_ai_integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active == True,
        )
        .first()
    )
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found",
        )

    decrypted_key = decrypt_api_key(integration.api_key)
    try:
        audio_bytes, content_type = download_elevenlabs_recording_bytes(
            audio_url,
            api_key=decrypted_key,
        )
    except ExotelInvalidContentError as exc:
        logger.warning(
            "Blocked ElevenLabs audio download for call_short_id={}: {}",
            call_recording.call_short_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recording URL is not allowed for provider proxy",
        ) from exc
    except Exception as exc:
        logger.warning(
            "ElevenLabs audio fetch failed for call_short_id={}: {}",
            call_recording.call_short_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch ElevenLabs recording",
        ) from exc

    def _iter_chunks(data: bytes, chunk_size: int = 8192) -> Iterator[bytes]:
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    return StreamingResponse(
        _iter_chunks(audio_bytes),
        media_type=content_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="{filename_prefix}_{call_recording.call_short_id}.mp3"'
            ),
        },
    )
