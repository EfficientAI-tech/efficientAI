"""Measure remote-agent (SUT) response latency on telephony evaluator calls."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from loguru import logger

from efficientai.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    UserStartedSpeakingFrame,
)
from efficientai.observers.base_observer import BaseObserver, FramePushed
from efficientai.processors.frame_processor import FrameDirection


class SutLatencyObserver(BaseObserver):
    """Track caller bot stop → remote user speech start as SUT response latency."""

    def __init__(self) -> None:
        super().__init__()
        self._processed_frames: set[int] = set()
        self._bot_stopped_at: float | None = None
        self._bot_speaking = False
        self._turn_number = 0
        self._turns: List[Dict[str, Any]] = []

    async def on_push_frame(self, data: FramePushed) -> None:
        if data.direction != FrameDirection.DOWNSTREAM:
            return
        frame_id = getattr(data.frame, "id", None)
        if frame_id is not None and frame_id in self._processed_frames:
            return
        if frame_id is not None:
            self._processed_frames.add(frame_id)

        now = time.time()
        frame = data.frame

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._bot_stopped_at = now
        elif isinstance(frame, UserStartedSpeakingFrame):
            if self._bot_stopped_at is None:
                return
            latency_ms = (now - self._bot_stopped_at) * 1000.0
            self._turn_number += 1
            talk_over = self._bot_speaking
            self._turns.append(
                {
                    "turn_number": self._turn_number,
                    "sut_response_latency_ms": round(latency_ms, 1),
                    "caller_stream_complete_at": self._bot_stopped_at,
                    "sut_speech_start_at": now,
                    "talk_over": talk_over,
                }
            )
            logger.debug(
                "SUT turn {} response latency {:.0f}ms talk_over={}",
                self._turn_number,
                latency_ms,
                talk_over,
            )
            self._bot_stopped_at = None
        elif isinstance(frame, (EndFrame, CancelFrame)):
            logger.info(
                "SutLatencyObserver captured {} turns (avg latency {:.0f}ms)",
                len(self._turns),
                self.average_latency_ms or 0,
            )

    def get_turns(self) -> List[Dict[str, Any]]:
        return list(self._turns)

    @property
    def average_latency_ms(self) -> float | None:
        values = [
            t["sut_response_latency_ms"]
            for t in self._turns
            if t.get("sut_response_latency_ms") is not None
        ]
        if not values:
            return None
        return sum(values) / len(values)
