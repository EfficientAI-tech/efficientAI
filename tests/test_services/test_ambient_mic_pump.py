"""AmbientMicPump must keep the caller mic stream on real time."""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from app.services.audio.ambient_mic_pump import BYTES_PER_SAMPLE, AmbientMicPump
from app.services.audio.ambient_mixer import AmbientBed

RATE = 16000


def _pump(sent: list[bytes]) -> AmbientMicPump:
    async def send(pcm: bytes) -> None:
        sent.append(pcm)

    bed = AmbientBed(np.full(RATE, 100, dtype=np.int16))
    return AmbientMicPump(bed, sample_rate=RATE, chunk_duration_ms=20, send_callback=send)


def _seconds(sent: list[bytes]) -> float:
    return sum(len(c) for c in sent) / BYTES_PER_SAMPLE / RATE


@pytest.mark.asyncio
async def test_idle_ambient_keeps_up_with_wall_clock():
    sent: list[bytes] = []
    pump = _pump(sent)
    start = time.monotonic()
    await pump.start()
    await asyncio.sleep(1.0)
    await pump.stop()
    assert _seconds(sent) == pytest.approx(time.monotonic() - start, abs=0.06)


@pytest.mark.asyncio
async def test_ambient_fills_event_loop_stall():
    sent: list[bytes] = []
    pump = _pump(sent)
    await pump.start()
    await asyncio.sleep(0.2)
    time.sleep(0.3)  # blocking call on the loop
    await asyncio.sleep(0.2)
    await pump.stop()
    assert _seconds(sent) == pytest.approx(0.7, abs=0.08)


@pytest.mark.asyncio
async def test_speech_replaces_ambient_and_timeline_stays_on_clock():
    sent: list[bytes] = []
    pump = _pump(sent)
    await pump.start()
    await asyncio.sleep(0.1)

    async def stream_chunks(audio, callback, chunk_ms, cancel_event=None):
        frame = len(audio) // 25
        for i in range(25):  # 0.5 s, paced with per-chunk sleeps (overshoots)
            await callback(audio[i * frame:(i + 1) * frame])
            await asyncio.sleep(0.02)
        return len(audio)

    speech = b"\x10\x00" * (RATE // 2)
    await pump.send_speech(speech, stream_chunks)
    await asyncio.sleep(0.2)
    await pump.stop()

    # No ambient was sent on top of speech (total would exceed wall time), and
    # any shortfall during speech was topped up afterwards.
    assert _seconds(sent) == pytest.approx(0.1 + 0.5 + 0.2, abs=0.1)
