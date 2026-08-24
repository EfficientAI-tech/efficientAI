"""Provider-hosted audio proxy helpers for observability/playground playback."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

import requests as http_requests
from fastapi import HTTPException
from fastapi import status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import Agent, CallRecording, Integration


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
    upstream = http_requests.get(
        audio_url,
        headers={"xi-api-key": decrypted_key},
        stream=True,
        timeout=60,
    )
    if upstream.status_code != 200:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=f"ElevenLabs audio fetch failed ({upstream.status_code})",
        )

    content_type = upstream.headers.get("content-type", "audio/mpeg")
    return StreamingResponse(
        upstream.iter_content(chunk_size=8192),
        media_type=content_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="{filename_prefix}_{call_recording.call_short_id}.mp3"'
            ),
        },
    )
