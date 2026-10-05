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


async def _wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate() and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_provider_stop_flush_survives_awaiting_on_flush():
    """Regression: the flush must not cancel its own provider-stop task."""
    completed: list[str] = []

    async def on_flush(text: str) -> None:
        await asyncio.sleep(0.05)  # simulates LLM + TTS
        completed.append(text)

    vad = FakeVAD([VADState.QUIET])
    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.05,
        flush_on_vad_quiet=False,
        vad_analyzer=vad,
    )
    await gate.start()

    await gate.hold_transcript("ElevenLabs turn")
    await gate.on_provider_stop_talking()
    await _wait_for(lambda: completed)

    assert completed == ["ElevenLabs turn"]
    await gate.stop()


@pytest.mark.asyncio
async def test_start_talking_does_not_cancel_in_flight_flush():
    started = asyncio.Event()
    completed: list[str] = []

    async def on_flush(text: str) -> None:
        started.set()
        await asyncio.sleep(0.1)
        completed.append(text)

    vad = FakeVAD([VADState.QUIET])
    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.05,
        flush_on_vad_quiet=False,
        vad_analyzer=vad,
    )
    await gate.start()

    await gate.hold_transcript("First turn")
    await gate.on_provider_stop_talking()
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await gate.on_production_start_talking()
    await _wait_for(lambda: completed)

    assert completed == ["First turn"]
    await gate.stop()


@pytest.mark.asyncio
async def test_transcript_deferred_during_flush_is_retried():
    started = asyncio.Event()
    completed: list[str] = []

    async def on_flush(text: str) -> None:
        started.set()
        await asyncio.sleep(0.05)
        completed.append(text)

    vad = FakeVAD([VADState.QUIET])
    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.02,
        flush_on_vad_quiet=False,
        vad_analyzer=vad,
    )
    await gate.start()

    await gate.hold_transcript("First turn")
    await gate.on_provider_stop_talking()
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await gate.hold_transcript("Second turn")
    await gate.on_provider_stop_talking()
    await _wait_for(lambda: len(completed) >= 2)

    assert completed == ["First turn", "Second turn"]
    await gate.stop()


@pytest.mark.asyncio
async def test_late_text_timeout_flush_survives_awaiting_on_flush():
    completed: list[str] = []

    async def on_flush(text: str) -> None:
        await asyncio.sleep(0.05)
        completed.append(text)

    vad = FakeVAD([VADState.SPEAKING, VADState.QUIET])
    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.05,
        late_text_wait_secs=0.1,
        vad_analyzer=vad,
    )
    await gate.start()

    await gate.ingest_audio(_pcm_chunk())
    await gate.ingest_audio(_pcm_chunk())
    # Held without cancelling the late-text task so its timeout performs the flush.
    gate._held_transcript = "Late text"
    await _wait_for(lambda: completed)

    assert completed == ["Late text"]
    await gate.stop()


@pytest.mark.asyncio
async def test_hold_while_speaking_defers_flush_until_agent_stops():
    """Agent resumes during the stop fallback window: no reply over its speech."""
    flushed: list[str] = []
    talking = {"value": False}

    async def on_flush(text: str) -> None:
        flushed.append(text)

    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.05,
        flush_on_vad_quiet=False,
        vad_analyzer=FakeVAD([VADState.QUIET]),
        hold_while_speaking=True,
        speaking_probe=lambda: talking["value"],
    )
    await gate.start()

    await gate.hold_transcript("First half.")
    await gate.on_provider_stop_talking()
    talking["value"] = True  # agent resumes before the fallback fires
    await asyncio.sleep(0.15)
    assert flushed == []

    await gate.hold_transcript("Second half.")
    talking["value"] = False
    await gate.on_provider_stop_talking()
    await _wait_for(lambda: flushed)
    assert flushed == ["First half. Second half."]

    await gate.stop()


@pytest.mark.asyncio
async def test_hold_while_speaking_rearms_on_vad_quiet():
    flushed: list[str] = []

    async def on_flush(text: str) -> None:
        flushed.append(text)

    vad = FakeVAD([VADState.SPEAKING, VADState.SPEAKING, VADState.QUIET])
    gate = ProductionTurnGate(
        on_flush=on_flush,
        stop_secs=0.05,
        flush_on_vad_quiet=False,
        vad_analyzer=vad,
        hold_while_speaking=True,
    )
    await gate.start()

    await gate.ingest_audio(_pcm_chunk())  # VAD speaking
    await gate.hold_transcript("Still talking")
    await gate.on_provider_stop_talking()
    await asyncio.sleep(0.1)
    assert flushed == []  # deferred: VAD hears speech

    await gate.ingest_audio(_pcm_chunk())
    await gate.ingest_audio(_pcm_chunk())  # VAD quiet re-arms the flush
    await _wait_for(lambda: flushed)
    assert flushed == ["Still talking"]

    await gate.stop()


@pytest.mark.asyncio
async def test_on_production_speech_fires_once_per_vad_rising_edge():
    edges: list[int] = []

    async def on_flush(text: str) -> None:
        pass

    async def on_speech() -> None:
        edges.append(1)

    vad = FakeVAD(
        [VADState.STARTING, VADState.SPEAKING, VADState.SPEAKING, VADState.QUIET, VADState.SPEAKING]
    )
    gate = ProductionTurnGate(on_flush=on_flush, vad_analyzer=vad, on_production_speech=on_speech)
    await gate.start()

    for _ in range(3):
        await gate.ingest_audio(_pcm_chunk())
    assert edges == [1]
    assert gate.production_speaking

    await gate.ingest_audio(_pcm_chunk())
    assert not gate.production_speaking
    await gate.ingest_audio(_pcm_chunk())
    assert edges == [1, 1]

    await gate.stop()
