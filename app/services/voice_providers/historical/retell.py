from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator, List, Optional, Tuple

import requests

from app.models.database import Integration
from app.services.voice_providers.historical.base import (
    HistoricalListItem,
    NormalizedCall,
    TimeSlice,
    integration_plain_api_key,
)
from app.services.voice_providers.retell import RetellVoiceProvider

RETELL_API_BASE = "https://api.retellai.com"
RETELL_LIST_CALLS_URL = f"{RETELL_API_BASE}/v3/list-calls"
RETELL_LIST_CHATS_URL = f"{RETELL_API_BASE}/v3/list-chats"


def _retell_request_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _paginated_rows(data: Any) -> List[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return (
            data.get("items")
            or data.get("calls")
            or data.get("chats")
            or []
        )
    return []


def _next_pagination_key(
    data: Any,
    cursor: Optional[str],
) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    next_key = data.get("pagination_key")
    if not next_key or next_key == cursor:
        return None
    return str(next_key)


class RetellHistoricalAdapter:
    def __init__(self, integration: Integration):
        self.integration = integration
        self._api_key = integration_plain_api_key(integration)
        self._provider = RetellVoiceProvider(self._api_key)

    def list_page(
        self,
        slice: TimeSlice,
        cursor: Optional[str],
        *,
        page_size: int = 100,
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
        if (slice.medium or "").strip().lower() == "chat":
            return self._list_chat_page(slice, cursor, page_size=page_size)

        if slice.agent_id:
            body["filter_criteria"]["agent_id"] = [slice.agent_id]
        if cursor:
            body["pagination_key"] = cursor

        response = requests.post(
            RETELL_LIST_CALLS_URL,
            headers=_retell_request_headers(self._api_key),
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        calls = _paginated_rows(data)
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
                    has_audio=(
                        False
                        if entry.get("opt_out_sensitive_data_storage")
                        else (True if recording else None)
                    ),
                    raw=entry,
                )
            )
        if not items:
            return [], None
        return items, _next_pagination_key(data, cursor)

    def _list_chat_page(
        self,
        slice: TimeSlice,
        cursor: Optional[str],
        *,
        page_size: int,
    ) -> Tuple[List[HistoricalListItem], Optional[str]]:
        body: dict = {
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
            RETELL_LIST_CHATS_URL,
            headers=_retell_request_headers(self._api_key),
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        chats = _paginated_rows(data)
        items: List[HistoricalListItem] = []
        for entry in chats:
            if not isinstance(entry, dict):
                continue
            chat_id = entry.get("chat_id") or entry.get("id")
            if not chat_id:
                continue
            start_ms = entry.get("start_timestamp")
            end_ms = entry.get("end_timestamp")
            started_at = None
            if start_ms is not None:
                started_at = datetime.fromtimestamp(int(start_ms) / 1000, tz=timezone.utc)
            duration = None
            if start_ms is not None and end_ms is not None:
                duration = max(0.0, (int(end_ms) - int(start_ms)) / 1000.0)
            items.append(
                HistoricalListItem(
                    conversation_id=str(chat_id),
                    agent_id=entry.get("agent_id") or slice.agent_id,
                    started_at=started_at,
                    duration_seconds=duration,
                    status=entry.get("chat_status") or entry.get("status"),
                    has_audio=None,
                    raw={**entry, "medium": "chat"},
                )
            )
        if not items:
            return [], None
        return items, _next_pagination_key(data, cursor)

    def hydrate(self, item: HistoricalListItem) -> NormalizedCall:
        entry = item.raw if isinstance(item.raw, dict) else {}
        if (entry.get("medium") or "").lower() == "chat" or entry.get("chat_id"):
            return self._hydrate_chat(item, entry)
        recording = (
            entry.get("recording_multi_channel_url") or entry.get("recording_url")
        )
        transcript = entry.get("transcript") or ""
        if not recording and not transcript:
            fetched = self._provider.retrieve_call_metrics(item.conversation_id)
            if isinstance(fetched, dict):
                entry = fetched
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

    def _hydrate_chat(self, item: HistoricalListItem, entry: dict) -> NormalizedCall:
        transcript = entry.get("transcript") or ""
        if not str(transcript).strip():
            response = requests.get(
                f"{RETELL_API_BASE}/get-chat/{item.conversation_id}",
                headers=_retell_request_headers(self._api_key),
                timeout=60,
            )
            response.raise_for_status()
            fetched = response.json()
            if isinstance(fetched, dict):
                entry = fetched
                transcript = entry.get("transcript") or ""
        if not isinstance(transcript, str):
            transcript = str(transcript)
        return NormalizedCall(
            conversation_id=item.conversation_id,
            transcript=transcript,
            raw_columns={
                "agent_id": entry.get("agent_id") or item.agent_id,
                "chat_status": entry.get("chat_status"),
                "medium": "chat",
                "start_timestamp": entry.get("start_timestamp"),
            },
            audio_url=None,
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
