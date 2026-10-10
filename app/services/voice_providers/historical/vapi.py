from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator, List, Optional, Tuple

import requests
from dateutil import parser as date_parser

from app.models.database import Integration
from app.services.voice_providers.historical.base import (
    HistoricalListItem,
    NormalizedCall,
    TimeSlice,
    build_canonical_recording_url,
)
from app.services.voice_providers.vapi import VapiVoiceProvider
from app.services.voice_providers.vapi_recording import extract_vapi_recording_url


class VapiHistoricalAdapter:
    def __init__(self, integration: Integration):
        self.integration = integration
        self._provider = VapiVoiceProvider(integration.api_key)

    def list_page(
        self,
        slice: TimeSlice,
        cursor: Optional[str],
        *,
        page_size: int = 100,
    ) -> Tuple[List[HistoricalListItem], Optional[str]]:
        params = {
            "limit": page_size,
            "createdAtGe": slice.slice_start.isoformat(),
            "createdAtLt": slice.slice_end.isoformat(),
        }
        if slice.agent_id:
            params["assistantId"] = slice.agent_id
        if cursor:
            params["createdAtLt"] = cursor

        url = f"{self._provider.api_url}/call"
        headers = {"Authorization": f"Bearer {self.integration.api_key}"}
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            data = data.get("calls") or data.get("data") or []
        items: List[HistoricalListItem] = []
        last_created: Optional[str] = None
        for entry in data:
            if not isinstance(entry, dict):
                continue
            call_id = entry.get("id")
            if not call_id:
                continue
            created = entry.get("createdAt")
            last_created = created
            started_at = None
            if created:
                try:
                    started_at = date_parser.isoparse(created)
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                except Exception:
                    started_at = None
            recording_url = extract_vapi_recording_url(entry, stereo=True)
            items.append(
                HistoricalListItem(
                    conversation_id=str(call_id),
                    agent_id=entry.get("assistantId") or slice.agent_id,
                    started_at=started_at,
                    status=entry.get("status"),
                    has_audio=bool(recording_url),
                    raw=entry,
                )
            )
        next_cursor = last_created if len(items) >= page_size and last_created else None
        return items, next_cursor

    def hydrate(self, item: HistoricalListItem) -> NormalizedCall:
        entry = item.raw or self._provider.retrieve_call_metrics(item.conversation_id)
        transcript = entry.get("transcript") or ""
        recording_url = extract_vapi_recording_url(entry, stereo=True)
        return NormalizedCall(
            conversation_id=item.conversation_id,
            transcript=transcript if isinstance(transcript, str) else str(transcript),
            raw_columns={
                "assistant_id": entry.get("assistantId"),
                "status": entry.get("status"),
                "ended_reason": entry.get("endedReason"),
                "cost": entry.get("cost"),
                "created_at": entry.get("createdAt"),
            },
            audio_url=recording_url,
            audio_content_type="audio/mpeg",
            use_provider_api_for_audio=False,
        )

    def open_audio_stream(self, call: NormalizedCall) -> Tuple[Iterator[bytes], str]:
        from app.services.telephony.recording_download import open_provider_recording_stream

        if not call.audio_url:
            raise ValueError("no audio url")
        _status, headers, stream = open_provider_recording_stream(
            call.audio_url,
            headers=None,
        )
        content_type = headers.get("content-type") or call.audio_content_type
        return stream, content_type
