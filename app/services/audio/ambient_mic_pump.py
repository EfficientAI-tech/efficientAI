"""Continuous ambient mic feed for evaluator WebRTC bridges."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from loguru import logger

from app.services.audio.ambient_mixer import AmbientBed

BYTES_PER_SAMPLE = 2
# Ambient fills the mic once speech has paused this long (between sentences
# of a streamed reply, or after it).
SPEECH_GAP_S = 0.06
MAX_CATCHUP_S = 0.5


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
        # Mic timeline: bytes sent vs. wall clock since the first send. The far
        # end builds the caller track from samples received, so a shortfall
        # (sleep overshoot, loop stalls) makes our speech drift later over the
        # call and eventually overlap the other side.
        self._t0: Optional[float] = None
        self._bytes_sent = 0
        self._last_speech_ts = 0.0
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

    async def _send(self, pcm: bytes, *, speech: bool = False) -> None:
        await self._send_callback(pcm)
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        self._bytes_sent += len(pcm)
        if speech:
            self._last_speech_ts = now

    def _deficit_bytes(self) -> int:
        """Bytes the mic stream is behind real time (>= 0)."""
        if self._t0 is None:
            return 0
        expected = int((time.monotonic() - self._t0) * self._sample_rate) * BYTES_PER_SAMPLE
        return max(0, expected - self._bytes_sent)

    async def _idle_loop(self):
        """Feed ambient bed on a wall-clock schedule, topping up any shortfall."""
        chunk_samples = self._chunk_samples()
        frame_bytes = chunk_samples * BYTES_PER_SAMPLE
        interval = self._chunk_duration_ms / 1000.0
        max_burst = int(MAX_CATCHUP_S * self._sample_rate) * BYTES_PER_SAMPLE
        try:
            next_tick = time.monotonic()
            while not self._stop.is_set():
                next_tick += interval
                speech_flowing = (
                    self._speaking and time.monotonic() - self._last_speech_ts < SPEECH_GAP_S
                )
                if not speech_flowing:
                    if self._t0 is None:
                        samples = chunk_samples
                    else:
                        deficit = self._deficit_bytes()
                        if deficit > max_burst:
                            # Long stall: bounded catch-up, then re-anchor.
                            self._bytes_sent += deficit - max_burst
                            deficit = max_burst
                        samples = (deficit // frame_bytes) * chunk_samples
                    if samples:
                        await self._send(self._bed.chunk_bytes(samples))
                delay = next_tick - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    next_tick = time.monotonic()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Ambient mic pump idle loop error: {}", exc)

    async def send_speech(
        self,
        audio_bytes: bytes,
        stream_chunks: Callable[..., Awaitable[Optional[int]]],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Optional[int]:
        self._speaking = True
        try:
            async def mixed_callback(chunk: bytes):
                mixed = self._bed.mix_speech(chunk)
                await self._send(mixed, speech=True)

            if cancel_event is None:
                return await stream_chunks(audio_bytes, mixed_callback, self._chunk_duration_ms)
            return await stream_chunks(
                audio_bytes,
                mixed_callback,
                self._chunk_duration_ms,
                cancel_event=cancel_event,
            )
        finally:
            self._speaking = False
            if self._mark_speech_done:
                self._mark_speech_done()
