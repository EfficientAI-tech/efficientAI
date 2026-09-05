"""Unit tests for ProductionTurnGate."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from app.services.audio.ambient_mixer import resample_mono_int16
from app.services.webrtc_bridge.production_turn_gate import (
    SILERO_FRAME_BYTES,
    ProductionTurnGate,
    _resample_pcm_bytes,
)
from efficientai.audio.vad.vad_analyzer import VADState


class FakeVAD:
    """Deterministic VAD stub for turn-gate tests."""

    def __init__(self, states: list[VADState]) -> None:
        self.sample_rate = 16_000
        self._states = list(states)
        self._index = 0
        self.chunks_analyzed = 0

    def set_sample_rate(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate

    async def analyze_audio(self, buffer: bytes) -> VADState:
        self.chunks_analyzed += 1
        if self._index < len(self._states):
            state = self._states[self._index]
            self._index += 1
            return state
        return self._states[-1] if self._states else VADState.QUIET


def _pcm_chunk() -> bytes:
    return b"\x01\x00" * (SILERO_FRAME_BYTES // 2)


@pytest.mark.asyncio
async def test_text_held_until_vad_quiet():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD(
        [
            VADState.STARTING,
            VADState.SPEAKING,
            VADState.STOPPING,
            VADState.QUIET,
        ]
    )
    gate = ProductionTurnGate(on_flush=on_flush, stop_secs=0.1, vad_analyzer=vad)
    await gate.start()

    await gate.hold_transcript("Hello from production agent")
    await gate.ingest_audio(_pcm_chunk())
    assert flushed == []

    await gate.ingest_audio(_pcm_chunk())
    await gate.ingest_audio(_pcm_chunk())
    await gate.ingest_audio(_pcm_chunk())

    await asyncio.sleep(0.05)
    assert flushed == ["Hello from production agent"]

    await gate.stop()


@pytest.mark.asyncio
async def test_silence_pump_reaches_quiet_without_more_pcm():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD([VADState.SPEAKING, VADState.STOPPING, VADState.QUIET])
    gate = ProductionTurnGate(on_flush=on_flush, stop_secs=0.05, vad_analyzer=vad)
    await gate.start()

    await gate.hold_transcript("Done speaking")
    await gate.ingest_audio(_pcm_chunk())
    await gate.ingest_audio(_pcm_chunk())

    deadline = asyncio.get_event_loop().time() + 1.0
    while not flushed and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)

    assert flushed == ["Done speaking"]
    assert vad.chunks_analyzed >= 3

    await gate.stop()


@pytest.mark.asyncio
async def test_vad_quiet_ignored_when_flush_on_vad_quiet_disabled():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD([VADState.SPEAKING, VADState.QUIET])
    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.05,
        flush_on_vad_quiet=False,
        vad_analyzer=vad,
    )
    await gate.start()

    await gate.hold_transcript("ElevenLabs turn")
    await gate.ingest_audio(_pcm_chunk())
    await gate.ingest_audio(_pcm_chunk())
    await asyncio.sleep(0.05)

    assert flushed == []

    await gate.on_provider_stop_talking()
    deadline = asyncio.get_event_loop().time() + 0.5
    while not flushed and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)

    assert flushed == ["ElevenLabs turn"]
    await gate.stop()


@pytest.mark.asyncio
async def test_provider_stop_flushes_even_when_vad_saw_speech():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD([VADState.SPEAKING, VADState.SPEAKING, VADState.SPEAKING])
    gate = ProductionTurnGate(on_flush=on_flush, stop_secs=0.05, vad_analyzer=vad)
    await gate.start()

    await gate.hold_transcript("Vapi turn with continuous PCM")
    await gate.ingest_audio(_pcm_chunk())
    await gate.on_provider_stop_talking()

    deadline = asyncio.get_event_loop().time() + 0.5
    while not flushed and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)

    assert flushed == ["Vapi turn with continuous PCM"]
    await gate.stop()


@pytest.mark.asyncio
async def test_provider_stop_fallback_when_vad_never_saw_speech():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD([VADState.QUIET, VADState.QUIET])
    gate = ProductionTurnGate(on_flush=on_flush, stop_secs=0.05, vad_analyzer=vad)
    await gate.start()

    await gate.hold_transcript("Quiet production TTS")
    await gate.on_provider_stop_talking()

    deadline = asyncio.get_event_loop().time() + 0.5
    while not flushed and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)

    assert flushed == ["Quiet production TTS"]
    await gate.stop()


@pytest.mark.asyncio
async def test_late_transcript_after_vad_quiet_still_flushes():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD([VADState.SPEAKING, VADState.QUIET])
    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.05,
        late_text_wait_secs=0.2,
        vad_analyzer=vad,
    )
    await gate.start()

    await gate.ingest_audio(_pcm_chunk())
    await gate.ingest_audio(_pcm_chunk())
    await asyncio.sleep(0.02)

    await gate.hold_transcript("Text arrived late")
    await asyncio.sleep(0.05)

    assert flushed == ["Text arrived late"]
    await gate.stop()


@pytest.mark.asyncio
async def test_resample_24khz_pcm_bytes():
    src = np.ones(960, dtype=np.int16).tobytes()  # 40ms at 24 kHz
    resampled = _resample_pcm_bytes(src, 24_000)
    assert len(resampled) == 1280  # 40ms at 16 kHz (640 samples)


@pytest.mark.asyncio
async def test_resample_24khz_before_analyze():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD([VADState.SPEAKING, VADState.QUIET])
    gate = ProductionTurnGate(on_flush=on_flush, stop_secs=0.05, vad_analyzer=vad)
    await gate.start()

    src = np.ones(960, dtype=np.int16).tobytes()  # 40ms at 24 kHz

    await gate.hold_transcript("Resampled turn")
    await gate.ingest_audio(src, source_rate=24_000)
    await gate.on_provider_stop_talking()

    deadline = asyncio.get_event_loop().time() + 1.0
    while not flushed and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)

    assert flushed == ["Resampled turn"]
    assert vad.chunks_analyzed >= 1
    await gate.stop()


def test_resample_mono_int16_helper():
    src = np.arange(240, dtype=np.int16)
    out = resample_mono_int16(src, 24_000, 16_000)
    assert len(out) == 160
