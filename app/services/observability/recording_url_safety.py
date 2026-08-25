"""SSRF-safe recording URL validation for observability provider downloads."""

from __future__ import annotations

import re
from typing import List, Tuple
from urllib.parse import urlparse

import httpx

from app.services.telephony.exotel_client import ExotelInvalidContentError
from app.services.telephony.recording_download import assert_recording_url_safe

_ELEVENLABS_HOST_SUFFIXES: List[str] = ["elevenlabs.io"]
_CONVERSATION_ID_RE = re.compile(r"^conv_[A-Za-z0-9_]+$")


def build_elevenlabs_conversation_audio_url(conversation_id: str) -> str:
    """Build a trusted ElevenLabs conversation audio URL from a provider call id."""
    normalized = str(conversation_id or "").strip()
    if not _CONVERSATION_ID_RE.fullmatch(normalized):
        raise ExotelInvalidContentError(
            "ElevenLabs conversation id contains unexpected characters"
        )
    return f"https://api.elevenlabs.io/v1/convai/conversations/{normalized}/audio"


def assert_elevenlabs_recording_url(recording_url: str) -> None:
    """Reject non-ElevenLabs destinations before attaching provider credentials."""
    assert_recording_url_safe(
        recording_url,
        user_supplied=False,
        allowed_suffixes=_ELEVENLABS_HOST_SUFFIXES,
    )
    parsed = urlparse(recording_url.strip())
    path = parsed.path or ""
    if not path.startswith("/v1/convai/conversations/") or not path.endswith("/audio"):
        raise ExotelInvalidContentError(
            "ElevenLabs recording URL path is not an allowed conversation audio endpoint"
        )


def download_elevenlabs_recording_bytes(
    recording_url: str,
    *,
    api_key: str,
    timeout_seconds: float = 120.0,
) -> Tuple[bytes, str]:
    """Download ElevenLabs audio only after host/path validation."""
    assert_elevenlabs_recording_url(recording_url)

    def _validate_redirect(request: httpx.Request) -> None:
        assert_recording_url_safe(
            str(request.url),
            user_supplied=False,
            allowed_suffixes=_ELEVENLABS_HOST_SUFFIXES,
        )
        parsed = urlparse(str(request.url))
        path = parsed.path or ""
        if not path.startswith("/v1/convai/conversations/") or not path.endswith("/audio"):
            raise ExotelInvalidContentError(
                "ElevenLabs recording redirect target is not an allowed audio endpoint"
            )

    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        event_hooks={"request": [_validate_redirect]},
    ) as client:
        response = client.get(recording_url, headers={"xi-api-key": api_key})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "audio/mpeg")
        return response.content, content_type
