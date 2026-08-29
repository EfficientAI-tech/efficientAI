"""Bridge ElevenLabs monitor websocket events into EfficientAI live ingest."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

import httpx
from loguru import logger

try:
    import websockets
except Exception:  # pragma: no cover - optional dependency
    websockets = None


class ElevenLabsMonitorBridge:
    """Stream ElevenLabs monitor events into /observability/live/events."""

    def __init__(
        self,
        *,
        conversation_id: str,
        elevenlabs_api_key: str,
        efficientai_api_key: str,
        workspace_id: Optional[str] = None,
        efficientai_base_url: str = "http://localhost:8000",
        provider_platform: str = "elevenlabs",
    ) -> None:
        self.conversation_id = conversation_id
        self.elevenlabs_api_key = elevenlabs_api_key
        self.efficientai_api_key = efficientai_api_key
        self.workspace_id = workspace_id
        self.efficientai_base_url = efficientai_base_url.rstrip("/")
        self.provider_platform = provider_platform
        self.trace_id: Optional[str] = None
        self._seq = 0
        self._started = False
        self._ended = False

    async def run(self) -> None:
        if websockets is None:
            raise RuntimeError("websockets is required. Install with: pip install websockets")

        if not self._started:
            await self._post_event("call.started", {"startedAt": self._now_iso(), "status": "in_progress"})
            self._started = True

        monitor_url = (
            "wss://api.elevenlabs.io/v1/convai/conversations/"
            f"{self.conversation_id}/monitor"
        )
        logger.info("Connecting ElevenLabs monitor websocket for conversation={}", self.conversation_id)
        headers = {"xi-api-key": self.elevenlabs_api_key}

        connect_kwargs = {"max_size": 16 * 1024 * 1024}
        try:
            async with websockets.connect(
                monitor_url,
                additional_headers=headers,
                **connect_kwargs,
            ) as ws:
                await self._recv_loop(ws)
        except TypeError:
            async with websockets.connect(
                monitor_url,
                extra_headers=headers,
                **connect_kwargs,
            ) as ws:
                await self._recv_loop(ws)
        finally:
            if not self._ended:
                await self._post_event("call.ended", {"endedAt": self._now_iso(), "status": "ended"})
                self._ended = True

    async def _recv_loop(self, ws: Any) -> None:
        async for raw in ws:
            try:
                event = json.loads(raw)
            except Exception:
                continue
            await self._handle_event(event)

    async def _handle_event(self, event: Dict[str, Any]) -> None:
        event_type = str(event.get("type") or "").strip()

        if event_type == "user_transcript":
            evt = event.get("user_transcription_event") or {}
            text = evt.get("user_transcript")
            if isinstance(text, str) and text.strip():
                await self._post_event(
                    "turn.user",
                    {"content": text.strip(), "role": "user"},
                )
            return

        if event_type == "agent_response":
            evt = event.get("agent_response_event") or {}
            text = evt.get("agent_response")
            if isinstance(text, str) and text.strip():
                await self._post_event(
                    "turn.assistant",
                    {"content": text.strip(), "role": "assistant"},
                )
            return

        if event_type == "agent_response_correction":
            evt = event.get("agent_response_correction_event") or {}
            text = evt.get("corrected_agent_response")
            if isinstance(text, str) and text.strip():
                await self._post_event(
                    "turn.assistant",
                    {
                        "content": text.strip(),
                        "role": "assistant",
                        "replace_last_by_role": True,
                    },
                )
            return

        if event_type in {"conversation_ended", "call_ended"}:
            await self._post_event("call.ended", {"endedAt": self._now_iso(), "status": "ended"})
            self._ended = True
            return

    async def _post_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._seq += 1
        body: Dict[str, Any] = {
            "event_id": f"el-monitor-{self.conversation_id}-{self._seq}-{uuid.uuid4().hex[:8]}",
            "call_id": self.conversation_id,
            "event_type": event_type,
            "seq": self._seq,
            "event_ts": self._now_iso(),
            "platform": self.provider_platform,
            "payload": payload,
        }
        if self.trace_id:
            body["trace_id"] = self.trace_id

        headers = {
            "X-API-Key": self.efficientai_api_key,
            "Content-Type": "application/json",
        }
        if self.workspace_id:
            headers["X-Workspace-Id"] = self.workspace_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.efficientai_base_url}/api/v1/observability/live/events",
                headers=headers,
                content=json.dumps(body),
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("trace_id") and not self.trace_id:
                self.trace_id = str(data["trace_id"])
            return data

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
