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
    integration_plain_api_key,
)
from app.services.voice_providers.vapi import VapiVoiceProvider
from app.services.voice_providers.vapi_recording import extract_vapi_recording_url


class VapiHistoricalAdapter:
    def __init__(self, integration: Integration):
        self.integration = integration
        self._api_key = integration_plain_api_key(integration)
        self._provider = VapiVoiceProvider(self._api_key)

    def list_page(
        self,
        slice: TimeSlice,
        cursor: Optional[str],
        *,
        page_size: int = 100,
    ) -> Tuple[List[HistoricalListItem], Optional[str]]:
        bound = slice.slice_end.isoformat()
        seen_id = None
        if cursor and "|" in cursor:
            bound, seen_id = cursor.split("|", 1)
        elif cursor:
            bound = cursor
        params = {
            "limit": page_size,
            "createdAtGe": slice.slice_start.isoformat(),
            "createdAtLt": bound,
        }
        if slice.agent_id:
            params["assistantId"] = slice.agent_id

        url = f"{self._provider.api_url}/call"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            data = data.get("calls") or data.get("data") or []
        items: List[HistoricalListItem] = []
        last_created: Optional[str] = None
        last_id: Optional[str] = None
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
            if seen_id and str(call_id) == seen_id:
                continue
            recording_url = extract_vapi_recording_url(entry, stereo=True)
            items.append(
                HistoricalListItem(
                    conversation_id=str(call_id),
                    agent_id=entry.get("assistantId") or slice.agent_id,
                    started_at=started_at,
                    status=entry.get("status"),
                    has_audio=True if recording_url else None,
                    raw=entry,
                )
            )
            last_id = str(call_id)
        next_cursor = None
        if len(data) >= page_size and last_created and items:
            candidate = f"{last_created}|{items[-1].conversation_id}"
            if candidate != cursor:
                next_cursor = candidate
        elif len(data) >= page_size and last_created and last_id:
            candidate = f"{last_created}|{last_id}"
            if candidate != cursor:
                next_cursor = candidate
        return items, next_cursor

    def hydrate(self, item: HistoricalListItem) -> NormalizedCall:
        entry = item.raw if isinstance(item.raw, dict) else {}
        recording_url = extract_vapi_recording_url(entry, stereo=True) if entry else None
        transcript = entry.get("transcript") or ""
        if not recording_url and not transcript:
            fetched = self._provider.retrieve_call_metrics(item.conversation_id)
            if isinstance(fetched, dict):
                entry = fetched
                recording_url = extract_vapi_recording_url(entry, stereo=True)
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
