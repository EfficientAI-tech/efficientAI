from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator, List, Optional, Tuple

import requests
from loguru import logger

from app.models.database import Integration
from app.services.voice_providers.elevenlabs import ElevenLabsVoiceProvider
from app.services.voice_providers.elevenlabs_api_url import elevenlabs_api_v1_base
from app.services.voice_providers.historical.base import (
    HistoricalListItem,
    NormalizedCall,
    TimeSlice,
    build_canonical_recording_url,
    integration_plain_api_key,
)


class ElevenLabsHistoricalAdapter:
    def __init__(self, integration: Integration):
        self.integration = integration
        self._api_key = integration_plain_api_key(integration)
        self.api_url = elevenlabs_api_v1_base(integration.api_base_url)
        self._provider = ElevenLabsVoiceProvider(
            self._api_key,
            base_url=integration.api_base_url,
        )

    def list_page(
        self,
        slice: TimeSlice,
        cursor: Optional[str],
        *,
        page_size: int = 100,
    ) -> Tuple[List[HistoricalListItem], Optional[str]]:
        params = {
            "page_size": page_size,
            "call_start_after_unix": int(slice.slice_start.timestamp()),
            "call_start_before_unix": int(slice.slice_end.timestamp()),
        }
        if cursor:
            params["cursor"] = cursor
        if slice.agent_id:
            params["agent_id"] = slice.agent_id

        url = f"{self.api_url}/convai/conversations"
        headers = {"xi-api-key": self._api_key}
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        conversations = data.get("conversations") or []
        items: List[HistoricalListItem] = []
        for entry in conversations:
            if not isinstance(entry, dict):
                continue
            conv_id = entry.get("conversation_id") or entry.get("id")
            if not conv_id:
                continue
            meta = entry.get("metadata") or {}
            started = meta.get("start_time_unix_secs")
            started_at = None
            if started is not None:
                started_at = datetime.fromtimestamp(int(started), tz=timezone.utc)
            items.append(
                HistoricalListItem(
                    conversation_id=str(conv_id),
                    agent_id=entry.get("agent_id") or slice.agent_id,
                    started_at=started_at,
                    duration_seconds=meta.get("call_duration_secs"),
                    status=entry.get("status"),
                    has_audio=bool(entry.get("has_audio", True)),
                    raw=entry,
                )
            )
        next_cursor = data.get("next_cursor") or data.get("cursor")
        if next_cursor and not items:
            return [], None
        return items, next_cursor if next_cursor else None

    @staticmethod
    def _segments_from_metrics(metrics: dict) -> list:
        segments = []
        for entry in metrics.get("transcript_object") or []:
            if not isinstance(entry, dict):
                continue
            text = (entry.get("text") or entry.get("message") or "").strip()
            if not text:
                continue
            speaker_raw = (entry.get("speaker") or entry.get("role") or "unknown").lower()
            if speaker_raw in ("agent", "ai", "assistant"):
                speaker = "agent"
            elif speaker_raw in ("user", "human", "customer"):
                speaker = "user"
            else:
                speaker = speaker_raw
            start = float(entry.get("start") or entry.get("time_in_call_secs") or 0)
            end = float(entry.get("end") or start)
            segments.append(
                {
                    "speaker": speaker,
                    "text": text,
                    "start": start,
                    "end": end,
                }
            )
        return segments

    def hydrate(self, item: HistoricalListItem) -> NormalizedCall:
        metrics = self._provider.retrieve_call_metrics(item.conversation_id)
        transcript = metrics.get("transcript") or ""
        segments = self._segments_from_metrics(metrics)
        raw_columns = {
            "agent_id": metrics.get("agent_id") or item.agent_id,
            "duration_seconds": metrics.get("duration_seconds"),
            "start_timestamp": metrics.get("start_timestamp"),
            "end_timestamp": metrics.get("end_timestamp"),
            "ended_reason": metrics.get("ended_reason"),
            "cost": metrics.get("cost"),
            "call_status": metrics.get("call_status"),
        }
        return NormalizedCall(
            conversation_id=item.conversation_id,
            transcript=transcript,
            raw_columns=raw_columns,
            recording_date=None,
            audio_url=f"{self.api_url}/convai/conversations/{item.conversation_id}/audio",
            audio_content_type="audio/mpeg",
            use_provider_api_for_audio=True,
            diarised_segments=segments or None,
        )

    def open_audio_stream(self, call: NormalizedCall) -> Tuple[Iterator[bytes], str]:
        if not call.audio_url:
            raise ValueError("no audio url")
        headers = {"xi-api-key": self._api_key}
        response = requests.get(call.audio_url, headers=headers, stream=True, timeout=120)
        response.raise_for_status()

        def _iter() -> Iterator[bytes]:
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
            finally:
                response.close()

        content_type = response.headers.get("Content-Type") or call.audio_content_type
        return _iter(), content_type
