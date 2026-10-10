from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator, List, Optional, Tuple

import requests

from app.models.database import Integration
from app.services.voice_providers.historical.base import (
    HistoricalListItem,
    NormalizedCall,
    TimeSlice,
)
from app.services.voice_providers.retell import RetellVoiceProvider


class RetellHistoricalAdapter:
    def __init__(self, integration: Integration):
        self.integration = integration
        self._provider = RetellVoiceProvider(integration.api_key)

    def list_page(
        self,
        slice: TimeSlice,
        cursor: Optional[str],
        *,
        page_size: int = 1000,
    ) -> Tuple[List[HistoricalListItem], Optional[str]]:
        body = {
            "filter_criteria": {
                "start_timestamp": {
                    "lower_threshold": int(slice.slice_start.timestamp() * 1000),
                    "upper_threshold": int(slice.slice_end.timestamp() * 1000),
                },
            },
            "limit": min(page_size, 1000),
        }
        if slice.agent_id:
            body["filter_criteria"]["agent_id"] = [slice.agent_id]
        if cursor:
            body["pagination_key"] = cursor

        response = requests.post(
            "https://api.retellai.com/v2/list-calls",
            headers={"Authorization": f"Bearer {self.integration.api_key}"},
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        calls = data if isinstance(data, list) else data.get("calls") or []
        items: List[HistoricalListItem] = []
        for entry in calls:
            if not isinstance(entry, dict):
                continue
            call_id = entry.get("call_id")
            if not call_id:
                continue
            start_ms = entry.get("start_timestamp")
            started_at = None
            if start_ms is not None:
                started_at = datetime.fromtimestamp(int(start_ms) / 1000, tz=timezone.utc)
            recording = (
                entry.get("recording_multi_channel_url")
                or entry.get("recording_url")
            )
            items.append(
                HistoricalListItem(
                    conversation_id=str(call_id),
                    agent_id=entry.get("agent_id") or slice.agent_id,
                    started_at=started_at,
                    duration_seconds=(
                        (entry.get("duration_ms") or 0) / 1000.0
                        if entry.get("duration_ms") is not None
                        else None
                    ),
                    status=entry.get("call_status"),
                    has_audio=bool(recording)
                    and not entry.get("opt_out_sensitive_data_storage"),
                    raw=entry,
                )
            )
        next_key = None
        if isinstance(data, dict):
            next_key = data.get("pagination_key")
        return items, next_key if next_key else None

    def hydrate(self, item: HistoricalListItem) -> NormalizedCall:
        entry = item.raw or self._provider.retrieve_call_metrics(item.conversation_id)
        transcript = entry.get("transcript") or ""
        recording = (
            entry.get("recording_multi_channel_url")
            or entry.get("recording_url")
        )
        return NormalizedCall(
            conversation_id=item.conversation_id,
            transcript=transcript if isinstance(transcript, str) else str(transcript),
            raw_columns={
                "agent_id": entry.get("agent_id"),
                "call_status": entry.get("call_status"),
                "duration_ms": entry.get("duration_ms"),
                "start_timestamp": entry.get("start_timestamp"),
            },
            audio_url=recording,
            audio_content_type="audio/wav",
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
