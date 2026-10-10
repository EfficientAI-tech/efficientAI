"""Shared types and adapter registry for platform historical imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Protocol, Tuple

from app.core.encryption import decrypt_api_key
from app.models.database import Integration


def integration_plain_api_key(integration: Integration) -> str:
    return decrypt_api_key(integration.api_key)


class SkipReason(str, Enum):
    IN_PROGRESS = "in_progress"
    NO_AUDIO = "no_audio"
    TOO_SHORT = "too_short"
    FILTERED_STATUS = "filtered_status"
    DUPLICATE = "duplicate"
    PROVIDER_REDACTED = "provider_redacted"


@dataclass
class TimeSlice:
    slice_id: int
    slice_start: datetime
    slice_end: datetime
    agent_id: Optional[str] = None


@dataclass
class HistoricalListItem:
    conversation_id: str
    agent_id: Optional[str] = None
    started_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    status: Optional[str] = None
    has_audio: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedCall:
    conversation_id: str
    transcript: str
    raw_columns: Dict[str, Any]
    recording_date: Optional[Any] = None
    audio_url: Optional[str] = None
    audio_content_type: str = "audio/mpeg"
    use_provider_api_for_audio: bool = False
    diarised_segments: Optional[List[Dict[str, Any]]] = None


class HistoricalProviderAdapter(Protocol):
    def list_page(
        self,
        slice: TimeSlice,
        cursor: Optional[str],
        *,
        page_size: int = 100,
    ) -> Tuple[List[HistoricalListItem], Optional[str]]: ...

    def hydrate(self, item: HistoricalListItem) -> NormalizedCall: ...

    def open_audio_stream(
        self,
        call: NormalizedCall,
    ) -> Tuple[Iterator[bytes], str]: ...


def build_canonical_recording_url(provider: str, conversation_id: str) -> str:
    key = (provider or "").strip().lower()
    return f"{key}://conversations/{conversation_id}"


def parse_canonical_recording_url(url: str) -> Tuple[str, str]:
    raw = (url or "").strip()
    if "://" not in raw:
        raise ValueError("invalid canonical platform recording url")
    scheme, rest = raw.split("://", 1)
    prefix = "conversations/"
    if not rest.startswith(prefix):
        raise ValueError("invalid canonical platform recording url")
    return scheme.lower(), rest[len(prefix) :]


def get_historical_adapter(integration: Integration) -> HistoricalProviderAdapter:
    platform = (integration.platform or "").strip().lower()
    if platform == "elevenlabs":
        from app.services.voice_providers.historical.elevenlabs import (
            ElevenLabsHistoricalAdapter,
        )

        return ElevenLabsHistoricalAdapter(integration)
    if platform == "vapi":
        from app.services.voice_providers.historical.vapi import VapiHistoricalAdapter

        return VapiHistoricalAdapter(integration)
    if platform == "retell":
        from app.services.voice_providers.historical.retell import RetellHistoricalAdapter

        return RetellHistoricalAdapter(integration)
    raise ValueError(f"Unsupported platform for historical import: {platform}")
