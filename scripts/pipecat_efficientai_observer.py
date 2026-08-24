#!/usr/bin/env python3
"""Bridge Pipecat bots to EfficientAI live observability ingest.

Copy this file into your Pipecat bot project.

Environment:
  EFFICIENTAI_API_KEY
  EFFICIENTAI_WORKSPACE_ID
  EFFICIENTAI_BASE_URL=http://localhost:8000

Minimum event sequence:
  1. call.started
  2. turn.user / turn.assistant  (one or more — required for transcript + trace)
  3. call.ended

Recommended wiring (Pipecat 0.0.99+ turn events):

    observer = EfficientAILiveObserver(call_id=session_id, platform="pipecat")
    await observer.start_call()
    wire_turn_events(user_aggregator, assistant_aggregator, observer)
    ...
    await observer.end_call()

Alternative (frame tap — place once in pipeline, after STT and LLM):

    pipeline = Pipeline([..., observer.as_pipecat_processor(), ...])
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger("efficientai.pipecat_observer")


def _load_pipecat_modules():
    """Import frame/processor symbols from pipecat (external bots) or efficientai (fork)."""
    errors: list[str] = []
    for module_prefix in ("pipecat", "efficientai"):
        try:
            frames = __import__(f"{module_prefix}.frames.frames", fromlist=["frames"])
            processors = __import__(
                f"{module_prefix}.processors.frame_processor",
                fromlist=["frame_processor"],
            )
            return {
                "TranscriptionFrame": frames.TranscriptionFrame,
                "LLMTextFrame": frames.LLMTextFrame,
                "TTSTextFrame": frames.TTSTextFrame,
                "AggregatedTextFrame": getattr(frames, "AggregatedTextFrame", None),
                "LLMFullResponseEndFrame": frames.LLMFullResponseEndFrame,
                "TextFrame": getattr(frames, "TextFrame", None),
                "FrameDirection": processors.FrameDirection,
                "FrameProcessor": processors.FrameProcessor,
            }
        except ImportError as exc:
            errors.append(f"{module_prefix}: {exc}")
    raise ImportError(
        "Install pipecat-ai or efficientai to use Pipecat integration helpers. "
        + "; ".join(errors)
    )


class EfficientAILiveObserver:
    """HTTP client + Pipecat hooks for live observability."""

    def __init__(
        self,
        *,
        call_id: str,
        platform: str = "pipecat",
        agent_ref: Optional[str] = None,
        trace_id: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> None:
        self.call_id = call_id
        self.platform = platform
        self.agent_ref = agent_ref
        self.trace_id = trace_id
        self.base_url = (base_url or os.environ.get("EFFICIENTAI_BASE_URL") or "http://localhost:8000").rstrip("/")
        self.api_key = api_key or os.environ.get("EFFICIENTAI_API_KEY", "")
        self.workspace_id = workspace_id or os.environ.get("EFFICIENTAI_WORKSPACE_ID", "")
        self._seq = 0
        self.call_short_id: Optional[str] = None
        self._agent_buffer = ""
        self._turn_count = 0

    async def start_call(self) -> Optional[str]:
        ack = await self._post("call.started", {"startedAt": self._now_iso(), "status": "in_progress"})
        self.call_short_id = ack.get("call_short_id")
        if ack.get("trace_id"):
            self.trace_id = str(ack["trace_id"])
        logger.info("EfficientAI call started call_id=%s short_id=%s", self.call_id, self.call_short_id)
        return self.call_short_id

    async def emit_turn(self, role: str, content: str, *, latency: Optional[dict[str, Any]] = None) -> None:
        if not content.strip():
            return
        normalized = role.strip().lower()
        event_type = "turn.assistant" if normalized in {"assistant", "agent", "bot"} else "turn.user"
        payload: dict[str, Any] = {
            "content": content.strip(),
            "role": "assistant" if event_type == "turn.assistant" else "user",
        }
        if latency:
            payload["latency"] = latency
        await self._post(event_type, payload)
        self._turn_count += 1
        logger.info("EfficientAI turn emitted role=%s seq=%s chars=%s", payload["role"], self._seq, len(content))

    async def end_call(
        self,
        *,
        recording_url: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        if trace_id:
            self.trace_id = trace_id
        payload: dict[str, Any] = {"endedAt": self._now_iso(), "status": "ended"}
        if recording_url:
            payload["recording_url"] = recording_url
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        await self._post("call.ended", payload)
        if self._turn_count == 0:
            logger.warning(
                "EfficientAI call ended with 0 turns (call_id=%s). "
                "Wire wire_turn_events() or as_pipecat_processor() so transcript/trace populate.",
                self.call_id,
            )
        else:
            logger.info("EfficientAI call ended call_id=%s turns=%s", self.call_id, self._turn_count)

    async def _post(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("EFFICIENTAI_API_KEY is required")
        self._seq += 1
        body = {
            "event_id": f"pipecat-{self.call_id}-{self._seq}-{uuid.uuid4().hex[:8]}",
            "call_id": self.call_id,
            "event_type": event_type,
            "seq": self._seq,
            "event_ts": self._now_iso(),
            "platform": self.platform,
            "payload": payload,
        }
        if self.trace_id:
            body["trace_id"] = self.trace_id
        if self.agent_ref:
            body["agent_ref"] = self.agent_ref

        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if self.workspace_id:
            headers["X-Workspace-Id"] = self.workspace_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/observability/live/events",
                headers=headers,
                content=json.dumps(body),
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def as_pipecat_processor(self):
        """Return a FrameProcessor that emits turns from common Pipecat frame types."""
        mods = _load_pipecat_modules()
        TranscriptionFrame = mods["TranscriptionFrame"]
        LLMTextFrame = mods["LLMTextFrame"]
        TTSTextFrame = mods["TTSTextFrame"]
        AggregatedTextFrame = mods["AggregatedTextFrame"]
        LLMFullResponseEndFrame = mods["LLMFullResponseEndFrame"]
        TextFrame = mods["TextFrame"]
        FrameDirection = mods["FrameDirection"]
        FrameProcessor = mods["FrameProcessor"]

        agent_frame_types = tuple(
            cls
            for cls in (LLMTextFrame, TTSTextFrame, AggregatedTextFrame)
            if cls is not None
        )
        immediate_agent_types = tuple(
            cls for cls in (TTSTextFrame, AggregatedTextFrame) if cls is not None
        )
        observer = self

        class _Processor(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                try:
                    if isinstance(frame, TranscriptionFrame) and getattr(frame, "text", ""):
                        await observer.emit_turn("user", frame.text)
                    elif agent_frame_types and isinstance(frame, agent_frame_types) and getattr(frame, "text", ""):
                        if direction == FrameDirection.DOWNSTREAM:
                            if immediate_agent_types and isinstance(frame, immediate_agent_types):
                                await observer.emit_turn("agent", frame.text)
                            else:
                                observer._agent_buffer += frame.text
                    elif isinstance(frame, LLMFullResponseEndFrame) and observer._agent_buffer.strip():
                        await observer.emit_turn("agent", observer._agent_buffer.strip())
                        observer._agent_buffer = ""
                    elif (
                        TextFrame is not None
                        and isinstance(frame, TextFrame)
                        and not isinstance(frame, TranscriptionFrame)
                        and getattr(frame, "text", "")
                        and direction == FrameDirection.DOWNSTREAM
                        and frame.__class__.__name__ not in {"InterimTranscriptionFrame"}
                    ):
                        # Fallback for bots that only emit generic TextFrame downstream.
                        await observer.emit_turn("agent", frame.text)
                except Exception as exc:
                    logger.warning("EfficientAI frame emit failed: %s", exc)
                await self.push_frame(frame, direction)

        return _Processor()


def wire_turn_events(user_aggregator, assistant_aggregator, observer: EfficientAILiveObserver) -> None:
    """Wire Pipecat 0.0.99+ context aggregator turn events (recommended)."""

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def _on_user_turn_stopped(aggregator, strategy, message):
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            await observer.emit_turn("user", content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def _on_assistant_turn_stopped(aggregator, message, *_extra):
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            await observer.emit_turn("assistant", content)


def wire_transcript_processor(transcript_processor, observer: EfficientAILiveObserver) -> None:
    """Wire deprecated TranscriptProcessor.on_transcript_update (Pipecat < 0.0.99)."""

    @transcript_processor.event_handler("on_transcript_update")
    async def _on_transcript_update(processor, frame):
        messages = getattr(frame, "messages", None) or []
        for msg in messages:
            content = getattr(msg, "content", None)
            role = getattr(msg, "role", None) or "user"
            if isinstance(content, str) and content.strip():
                await observer.emit_turn(role, content)


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def _demo() -> None:
        obs = EfficientAILiveObserver(call_id=f"pipecat-demo-{uuid.uuid4().hex[:8]}")
        await obs.start_call()
        await obs.emit_turn("user", "Hello from external Pipecat bridge")
        await obs.emit_turn("assistant", "Hi there!", latency={"llm_ms": 320, "tts_ms": 180})
        await obs.end_call()
        print("done", obs.call_short_id)

    asyncio.run(_demo())
