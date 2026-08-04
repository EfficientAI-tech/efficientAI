"""End live telephony calls when no voice activity is detected for a configured duration."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from efficientai.frames.frames import (
    BotSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    OutputAudioRawFrame,
    StartFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    VADUserStartedSpeakingFrame,
)
from efficientai.processors.frame_processor import FrameDirection, FrameProcessor
from loguru import logger

CALL_SILENCE_HANGUP_SECS = 15.0
DEFAULT_SILENCE_HANGUP_SECS = 15
MAX_SILENCE_HANGUP_SECS = 600


def resolve_agent_silence_hangup_secs(agent: object | None) -> float | None:
    """
    Seconds of no voice activity before ending a live call.

    Returns None when hangup is disabled (0). Uses agent setting or default 15s.
    """
    if agent is None:
        return float(DEFAULT_SILENCE_HANGUP_SECS)
    raw = getattr(agent, "silence_hangup_secs", None)
    if raw is None:
        return float(DEFAULT_SILENCE_HANGUP_SECS)
    try:
        secs = int(raw)
    except (TypeError, ValueError):
        return float(DEFAULT_SILENCE_HANGUP_SECS)
    if secs <= 0:
        return None
    return float(min(max(secs, 1), MAX_SILENCE_HANGUP_SECS))


class CallSilenceHangupProcessor(FrameProcessor):
    """Hang up when neither party produces voice activity for ``timeout_secs`` from connect."""

    def __init__(
        self,
        *,
        timeout_secs: float = CALL_SILENCE_HANGUP_SECS,
        on_hangup: Optional[Callable[[], Awaitable[None]]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._timeout_secs = timeout_secs
        self._on_hangup = on_hangup
        self._watch_task: Optional[asyncio.Task] = None
        self._last_activity = time.monotonic()
        self._hangup_sent = False

    def _touch_activity(self) -> None:
        self._last_activity = time.monotonic()

    def _ensure_watch_task(self) -> None:
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = self.create_task(self._watch_loop())

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            if self._hangup_sent:
                return
            elapsed = time.monotonic() - self._last_activity
            if elapsed >= self._timeout_secs:
                await self._trigger_hangup()
                return

    async def _trigger_hangup(self) -> None:
        if self._hangup_sent:
            return
        self._hangup_sent = True
        logger.info(
            "Call silence hangup: no voice activity for {:.0f}s — ending call",
            self._timeout_secs,
        )
        if self._on_hangup:
            await self._on_hangup()
        await self.push_frame(EndFrame(), FrameDirection.DOWNSTREAM)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._watch_task and not self._watch_task.done():
                await self.cancel_task(self._watch_task)
            self._watch_task = None
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, StartFrame):
            self._touch_activity()
            self._ensure_watch_task()

        if isinstance(
            frame,
            (
                UserStartedSpeakingFrame,
                VADUserStartedSpeakingFrame,
                BotSpeakingFrame,
                OutputAudioRawFrame,
                TTSAudioRawFrame,
            ),
        ):
            self._touch_activity()

        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        if self._watch_task and not self._watch_task.done():
            await self.cancel_task(self._watch_task)
        self._watch_task = None
        await super().cleanup()
