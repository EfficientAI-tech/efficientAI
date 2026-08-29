"""Pipecat frame processor that publishes live transcript turns."""

from __future__ import annotations

import time
from typing import Optional

from loguru import logger


def create_live_transcript_processor(
    call_short_id: Optional[str],
    call_start_time: Optional[float] = None,
    live_observability_emitter: Optional[Any] = None,
):
    """Return a FrameProcessor that publishes user/agent transcript turns."""
    if not call_short_id and live_observability_emitter is None:
        return None

    imports = None

    def _imports():
        nonlocal imports
        if imports is None:
            from efficientai.frames.frames import (
                AggregatedTextFrame,
                LLMFullResponseEndFrame,
                LLMTextFrame,
                TranscriptionFrame,
                TTSTextFrame,
            )
            from efficientai.processors.frame_processor import FrameDirection, FrameProcessor

            imports = {
                "LLMFullResponseEndFrame": LLMFullResponseEndFrame,
                "AggregatedTextFrame": AggregatedTextFrame,
                "LLMTextFrame": LLMTextFrame,
                "TranscriptionFrame": TranscriptionFrame,
                "TTSTextFrame": TTSTextFrame,
                "FrameDirection": FrameDirection,
                "FrameProcessor": FrameProcessor,
            }
        return imports

    imp = _imports()
    FrameProcessor = imp["FrameProcessor"]
    FrameDirection = imp["FrameDirection"]
    TranscriptionFrame = imp["TranscriptionFrame"]
    LLMTextFrame = imp["LLMTextFrame"]
    TTSTextFrame = imp["TTSTextFrame"]
    LLMFullResponseEndFrame = imp["LLMFullResponseEndFrame"]
    AggregatedTextFrame = imp["AggregatedTextFrame"]

    from app.services.telephony.call_recording_lifecycle import append_live_transcript_turn
    from app.services.telephony.live_transcript import publish_transcript_turn
    from app.database import SessionLocal

    class LiveTranscriptProcessor(FrameProcessor):
        def __init__(self):
            super().__init__()
            self._agent_buffer = ""

        def _persist_turn(self, role: str, content: str) -> None:
            start_time_sec = None
            if call_start_time is not None:
                start_time_sec = round(time.time() - call_start_time, 2)
            if call_short_id:
                publish_transcript_turn(call_short_id, role, content)
                db = SessionLocal()
                try:
                    append_live_transcript_turn(
                        db,
                        call_short_id=call_short_id,
                        role=role,
                        content=content,
                        start_time_sec=start_time_sec,
                    )
                    logger.debug("Live transcript saved call={} role={} text={}", call_short_id, role, content[:80])
                    # region agent log
                    from app.utils.debug_agent_log import agent_debug_log

                    agent_debug_log(
                        "live_transcript_processor.py:_persist_turn",
                        "transcript turn persisted",
                        {"call_short_id": call_short_id, "role": role, "content_len": len(content)},
                        "H2",
                    )
                    # endregion
                finally:
                    db.close()
            if live_observability_emitter is not None:
                try:
                    live_observability_emitter.emit_turn(
                        role,
                        content,
                        start_time=start_time_sec,
                    )
                except Exception as exc:
                    logger.warning(
                        "Live observability turn emit failed for call {}: {}",
                        call_short_id or getattr(live_observability_emitter, "provider_call_id", "?"),
                        exc,
                    )

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)

            try:
                if isinstance(frame, TranscriptionFrame) and frame.text:
                    self._persist_turn("user", frame.text)
                elif (
                    isinstance(frame, (LLMTextFrame, TTSTextFrame, AggregatedTextFrame))
                    and frame.text
                    and direction == FrameDirection.DOWNSTREAM
                ):
                    if isinstance(frame, (TTSTextFrame, AggregatedTextFrame)):
                        self._persist_turn("agent", frame.text)
                    else:
                        self._agent_buffer += frame.text
                elif isinstance(frame, LLMFullResponseEndFrame) and self._agent_buffer.strip():
                    self._persist_turn("agent", self._agent_buffer.strip())
                    self._agent_buffer = ""
            except Exception as exc:
                logger.warning("Live transcript publish failed for call {}: {}", call_short_id, exc)

            await self.push_frame(frame, direction)

    return LiveTranscriptProcessor()
