"""VAD-gated turn-taking for synthetic evaluator WebRTC bridges.

Holds production-agent transcripts until Silero VAD confirms inbound audio
has gone quiet, preventing the test agent from speaking over production TTS.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional, Protocol

import numpy as np
from loguru import logger

from app.services.audio.ambient_mixer import resample_mono_int16

TARGET_SAMPLE_RATE = 16_000
# Silero requires 512 samples (16 kHz) or 256 samples (8 kHz) per frame.
SILERO_FRAME_BYTES = 512 * 2
SILENCE_PUMP_INTERVAL_S = 0.032


class VADAnalyzerProtocol(Protocol):
    """Minimal VAD interface used by ProductionTurnGate."""

    sample_rate: int

    async def analyze_audio(self, buffer: bytes):
        ...


def _default_vad_analyzer(*, stop_secs: float) -> VADAnalyzerProtocol:
    from efficientai.audio.vad.silero import SileroVADAnalyzer
    from efficientai.audio.vad.vad_analyzer import VADParams, VADState

    _ = VADState  # re-export guard for type checkers
    return SileroVADAnalyzer(
        sample_rate=TARGET_SAMPLE_RATE,
        params=VADParams(start_secs=0.2, stop_secs=stop_secs),
    )


def _resample_pcm_bytes(pcm: bytes, source_rate: int) -> bytes:
    if source_rate == TARGET_SAMPLE_RATE or not pcm:
        return pcm
    audio = np.frombuffer(pcm, dtype=np.int16)
    resampled = resample_mono_int16(audio, source_rate, TARGET_SAMPLE_RATE)
    return resampled.tobytes()


class ProductionTurnGate:
    """Gate production-agent transcripts on inbound audio silence."""

    def __init__(
        self,
        *,
        on_flush: Callable[[str], Awaitable[None]],
        stop_secs: float = 1.0,
        late_text_wait_secs: float = 1.5,
        flush_on_vad_quiet: bool = True,
        vad_analyzer: Optional[VADAnalyzerProtocol] = None,
    ) -> None:
        self._on_flush = on_flush
        self._stop_secs = stop_secs
        self._late_text_wait_secs = late_text_wait_secs
        self._flush_on_vad_quiet = flush_on_vad_quiet
        self._vad = vad_analyzer or _default_vad_analyzer(stop_secs=stop_secs)

        self._held_transcript = ""
        self._previous_vad_state = None
        self._saw_speech_this_turn = False
        self._outbound_active = False
        self._flush_in_progress = False

        self._last_real_audio_ts = 0.0
        self._silence_pump_task: Optional[asyncio.Task] = None
        self._provider_stop_task: Optional[asyncio.Task] = None
        self._late_text_task: Optional[asyncio.Task] = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if hasattr(self._vad, "set_sample_rate"):
            self._vad.set_sample_rate(TARGET_SAMPLE_RATE)
        self._silence_pump_task = asyncio.create_task(
            self._silence_pump_loop(),
            name="production-turn-gate-silence-pump",
        )

    async def stop(self) -> None:
        self._started = False
        for task in (self._silence_pump_task, self._provider_stop_task, self._late_text_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._silence_pump_task = None
        self._provider_stop_task = None
        self._late_text_task = None

    def set_outbound_active(self, active: bool) -> None:
        self._outbound_active = active

    async def hold_transcript(self, text: str) -> None:
        """Accumulate provider text; never invoke the test agent directly."""
        cleaned = (text or "").strip()
        if not cleaned:
            return

        if self._held_transcript:
            if cleaned not in self._held_transcript:
                self._held_transcript = f"{self._held_transcript} {cleaned}".strip()
        else:
            self._held_transcript = cleaned

        logger.debug(
            f"[TurnGate] Held transcript ({len(self._held_transcript)} chars): "
            f"{self._held_transcript[:80]}..."
        )

        if self._late_text_task and not self._late_text_task.done():
            self._late_text_task.cancel()
            self._late_text_task = None
            if self._flush_on_vad_quiet:
                await self._try_flush("late-text")

    async def ingest_audio(self, pcm: bytes, *, source_rate: int = TARGET_SAMPLE_RATE) -> None:
        if not pcm:
            return
        self._last_real_audio_ts = time.monotonic()
        prepared = _resample_pcm_bytes(pcm, source_rate)
        await self._analyze_and_update(prepared)

    async def on_production_start_talking(self) -> None:
        """Reset per-turn counters when the provider signals speech start."""
        self._cancel_provider_stop_fallback()
        self._saw_speech_this_turn = False

    async def on_provider_stop_talking(self) -> None:
        """Provider thinks the agent stopped; use as fallback if VAD never saw speech."""
        if self._provider_stop_task and not self._provider_stop_task.done():
            return
        self._provider_stop_task = asyncio.create_task(
            self._provider_stop_fallback(),
            name="production-turn-gate-provider-stop",
        )

    async def _silence_pump_loop(self) -> None:
        """Feed zero frames when providers stop sending PCM mid-utterance (ElevenLabs)."""
        silence_chunk = b"\x00" * SILERO_FRAME_BYTES
        try:
            while self._started:
                await asyncio.sleep(SILENCE_PUMP_INTERVAL_S)
                if self._last_real_audio_ts == 0:
                    continue
                elapsed = time.monotonic() - self._last_real_audio_ts
                if elapsed >= SILENCE_PUMP_INTERVAL_S:
                    await self._analyze_and_update(silence_chunk)
        except asyncio.CancelledError:
            pass

    async def _analyze_and_update(self, pcm: bytes) -> None:
        from efficientai.audio.vad.vad_analyzer import VADState

        if self._previous_vad_state is None:
            self._previous_vad_state = VADState.QUIET

        # Feed the analyzer in Silero frame increments.
        offset = 0
        current_state = self._previous_vad_state
        while offset < len(pcm):
            chunk = pcm[offset : offset + SILERO_FRAME_BYTES]
            offset += SILERO_FRAME_BYTES
            if len(chunk) < SILERO_FRAME_BYTES:
                chunk = chunk + b"\x00" * (SILERO_FRAME_BYTES - len(chunk))
            current_state = await self._vad.analyze_audio(chunk)

        previous = self._previous_vad_state
        self._previous_vad_state = current_state

        if current_state == VADState.SPEAKING:
            self._saw_speech_this_turn = True
            self._cancel_late_text_wait()

        if previous in (VADState.SPEAKING, VADState.STOPPING) and current_state == VADState.QUIET:
            await self._on_vad_quiet()

    async def _on_vad_quiet(self) -> None:
        if self._flush_on_vad_quiet and self._held_transcript.strip():
            await self._try_flush("vad-quiet")
        elif self._flush_on_vad_quiet:
            self._schedule_late_text_wait()
        else:
            logger.debug("[TurnGate] VAD quiet ignored — waiting for provider stop signal")

    def _schedule_late_text_wait(self) -> None:
        if self._late_text_task and not self._late_text_task.done():
            return

        async def _wait() -> None:
            try:
                await asyncio.sleep(self._late_text_wait_secs)
                if self._held_transcript.strip():
                    await self._try_flush("late-text-timeout")
                else:
                    logger.debug("[TurnGate] VAD quiet with no held text — skipping empty turn")
                    self._reset_turn_state()
            except asyncio.CancelledError:
                pass

        self._late_text_task = asyncio.create_task(_wait(), name="production-turn-gate-late-text")

    def _cancel_late_text_wait(self) -> None:
        if self._late_text_task and not self._late_text_task.done():
            self._late_text_task.cancel()
        self._late_text_task = None

    def _cancel_provider_stop_fallback(self) -> None:
        if self._provider_stop_task and not self._provider_stop_task.done():
            self._provider_stop_task.cancel()
        self._provider_stop_task = None

    async def _provider_stop_fallback(self) -> None:
        """Flush after provider stop once trailing TTS has had time to finish.

        Vapi/Daily may keep delivering PCM frames after the agent stops, so VAD
        never reaches QUIET. Provider stop is the reliable end-of-turn signal
        for those platforms when we already hold a transcript.
        """
        try:
            await asyncio.sleep(self._stop_secs)
            if not self._held_transcript.strip():
                return
            await self._try_flush("provider-stop-fallback")
        except asyncio.CancelledError:
            pass

    async def _try_flush(self, reason: str) -> None:
        if self._flush_in_progress or self._outbound_active:
            logger.debug(f"[TurnGate] Deferring flush ({reason}) — outbound active or flush in progress")
            return

        text = self._held_transcript.strip()
        if not text:
            return

        self._flush_in_progress = True
        self._held_transcript = ""
        self._cancel_late_text_wait()
        self._cancel_provider_stop_fallback()

        logger.info(f"[TurnGate] Flushing held transcript ({reason}, {len(text)} chars)")
        try:
            await self._on_flush(text)
        finally:
            self._flush_in_progress = False
            self._reset_turn_state()

    def _reset_turn_state(self) -> None:
        self._saw_speech_this_turn = False
        self._last_real_audio_ts = 0.0
