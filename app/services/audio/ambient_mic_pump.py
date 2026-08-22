"""Continuous ambient mic feed for evaluator WebRTC bridges."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from loguru import logger

from app.services.audio.ambient_mixer import AmbientBed


class AmbientMicPump:
    """
    Streams continuous ambient-only PCM while idle and mixed speech while active.

    Replaces ElevenLabs' zero-silence loop when a persona has background noise.
    """

    def __init__(
        self,
        bed: AmbientBed,
        *,
        sample_rate: int,
        chunk_duration_ms: int = 20,
        send_callback: Callable[[bytes], Awaitable[None]],
        mark_speech_done: Optional[Callable[[], None]] = None,
    ):
        self._bed = bed
        self._sample_rate = sample_rate
        self._chunk_duration_ms = chunk_duration_ms
        self._send_callback = send_callback
        self._mark_speech_done = mark_speech_done
        self._speaking = False
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    @property
    def chunk_duration_ms(self) -> int:
        return self._chunk_duration_ms

    def _chunk_samples(self) -> int:
        return max(1, (self._sample_rate * self._chunk_duration_ms) // 1000)

    async def start(self):
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._idle_loop())
        logger.info(
            "Ambient mic pump started (sample_rate={}, chunk_ms={})",
            self._sample_rate,
            self._chunk_duration_ms,
        )

    async def stop(self):
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def _idle_loop(self):
        chunk_samples = self._chunk_samples()
        interval = self._chunk_duration_ms / 1000.0
        try:
            while not self._stop.is_set():
                if self._speaking:
                    await asyncio.sleep(0.01)
                    continue
                await self._send_callback(self._bed.chunk_bytes(chunk_samples))
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Ambient mic pump idle loop error: {}", exc)

    async def send_speech(
        self,
        audio_bytes: bytes,
        stream_chunks: Callable[[bytes, Callable[[bytes], Awaitable[None]], int], Awaitable[None]],
    ):
        self._speaking = True
        try:
            async def mixed_callback(chunk: bytes):
                mixed = self._bed.mix_speech(chunk)
                await self._send_callback(mixed)

            await stream_chunks(audio_bytes, mixed_callback, self._chunk_duration_ms)
        finally:
            self._speaking = False
            if self._mark_speech_done:
                self._mark_speech_done()
