"""Unit tests for ElevenLabsWSBridge real-time playout pacing and turn delivery."""

from __future__ import annotations

import asyncio
import base64
import time
from unittest.mock import AsyncMock

import pytest

from app.services.webrtc_bridge import elevenlabs_ws_bridge as bridge_mod
from app.services.webrtc_bridge.elevenlabs_ws_bridge import ElevenLabsWSBridge

SAMPLE_RATE = 16_000


def _audio_event(seconds: float, event_id: int = 1) -> dict:
    pcm = b"\x01\x00" * int(SAMPLE_RATE * seconds)
    return {
        "type": "audio",
        "audio_event": {"event_id": event_id, "audio_base_64": base64.b64encode(pcm).decode()},
    }


def _make_bridge() -> ElevenLabsWSBridge:
    bridge = ElevenLabsWSBridge(signed_url="wss://example.invalid", sample_rate=SAMPLE_RATE)
    bridge.is_connected = True
    return bridge


async def _start_pacer(bridge: ElevenLabsWSBridge) -> None:
    bridge._pacer_task = asyncio.create_task(bridge._playout_loop())


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_burst_audio_is_played_out_in_real_time():
    bridge = _make_bridge()
    played: list[float] = []

    async def on_audio(frame: bytes) -> None:
        played.append(time.monotonic())

    bridge.on_audio_received = on_audio
    await _start_pacer(bridge)

    # 0.4 s of audio arrives all at once (faster than real time).
    await bridge._handle_message(_audio_event(0.4))
    await _wait_for(lambda: len(played) >= 20)

    assert len(played) == 20  # 20 ms frames
    assert played[-1] - played[0] >= 0.33
    await bridge.disconnect()


@pytest.mark.asyncio
async def test_turn_end_waits_for_playout(monkeypatch):
    monkeypatch.setattr(bridge_mod, "SILENCE_THRESHOLD_S", 0.1)
    bridge = _make_bridge()
    bridge.on_audio_received = AsyncMock()
    stop = AsyncMock()
    bridge.on_agent_stop_talking = stop
    bridge.on_transcript_received = AsyncMock()
    await _start_pacer(bridge)

    started = time.monotonic()
    await bridge._handle_message(_audio_event(0.5))
    await bridge._handle_message(
        {"type": "agent_response", "agent_response_event": {"agent_response": "Hello there."}}
    )
    await _wait_for(lambda: stop.await_count > 0)

    # Stop fires only after the 0.5 s of audio has played, plus the threshold.
    assert stop.await_count == 1
    assert time.monotonic() - started >= 0.55
    bridge.on_transcript_received.assert_awaited_once_with("Hello there.")
    await bridge.disconnect()


@pytest.mark.asyncio
async def test_start_talking_fires_on_first_played_frame():
    bridge = _make_bridge()
    bridge.on_audio_received = AsyncMock()
    start = AsyncMock()
    bridge.on_agent_start_talking = start

    await bridge._handle_message(_audio_event(0.1))
    await asyncio.sleep(0.05)
    assert start.await_count == 0  # queued, not yet played

    await _start_pacer(bridge)
    await _wait_for(lambda: start.await_count > 0)
    assert start.await_count == 1
    await bridge.disconnect()


@pytest.mark.asyncio
async def test_interruption_drops_unplayed_audio():
    bridge = _make_bridge()
    frames: list[bytes] = []

    async def on_audio(frame: bytes) -> None:
        frames.append(frame)

    bridge.on_audio_received = on_audio
    bridge.on_agent_stop_talking = AsyncMock()
    await _start_pacer(bridge)

    await bridge._handle_message(_audio_event(1.0, event_id=1))
    await asyncio.sleep(0.1)
    await bridge._handle_message({"type": "interruption", "interruption_event": {"event_id": 1}})
    played_at_interrupt = len(frames)
    await asyncio.sleep(0.2)

    assert played_at_interrupt < 15
    assert len(frames) <= played_at_interrupt + 1
    assert not bridge._playout_pending()
    await bridge.disconnect()


@pytest.mark.asyncio
async def test_agent_response_parts_accumulate_within_turn():
    bridge = _make_bridge()
    for text in ("First part.", "Second part.", "Second part."):
        await bridge._handle_message(
            {"type": "agent_response", "agent_response_event": {"agent_response": text}}
        )
    assert bridge._pending_agent_text == "First part. Second part."


@pytest.mark.asyncio
async def test_deliver_empty_turns_when_enabled():
    bridge = _make_bridge()
    received = AsyncMock()
    bridge.on_transcript_received = received
    bridge.on_agent_stop_talking = AsyncMock()

    await bridge._deliver_turn_end()
    received.assert_not_awaited()

    bridge.deliver_empty_turns = True
    await bridge._deliver_turn_end()
    received.assert_awaited_once_with("")


@pytest.mark.asyncio
async def test_bad_event_does_not_crash_handler_loop():
    bridge = _make_bridge()
    bridge.on_audio_received = AsyncMock()
    # A malformed event_id raises inside _handle_message; the receive loop
    # wraps it, so assert the handler itself raises and state is untouched.
    with pytest.raises(ValueError):
        await bridge._handle_message({"type": "audio", "audio_event": {"event_id": "x"}})
    assert bridge.is_connected



# ----------------------------------------------------------------------
# Mic timeline: the caller track must keep up with real time
# ----------------------------------------------------------------------


class _RecordingWS:
    def __init__(self):
        self.mic_bytes = 0
        self.sends = 0

    async def send(self, raw):
        import json

        msg = json.loads(raw)
        if "user_audio_chunk" in msg:
            self.mic_bytes += len(base64.b64decode(msg["user_audio_chunk"]))
            self.sends += 1


def _mic_seconds(bridge, ws) -> float:
    return ws.mic_bytes / bridge_mod.BYTES_PER_SAMPLE / SAMPLE_RATE


@pytest.mark.asyncio
async def test_background_mic_keeps_up_with_wall_clock():
    bridge = _make_bridge()
    ws = bridge._ws = _RecordingWS()
    task = asyncio.create_task(bridge._background_silence_loop())
    start = time.monotonic()
    await asyncio.sleep(1.0)
    elapsed = time.monotonic() - start
    bridge.is_connected = False
    await task
    # Sleep-per-frame pacing falls behind; clock pacing stays within a frame or two.
    assert _mic_seconds(bridge, ws) == pytest.approx(elapsed, abs=0.06)


@pytest.mark.asyncio
async def test_mic_catches_up_after_event_loop_stall_with_bounded_burst():
    bridge = _make_bridge()
    ws = bridge._ws = _RecordingWS()
    task = asyncio.create_task(bridge._background_silence_loop())
    await asyncio.sleep(0.2)
    time.sleep(0.3)  # blocking call on the loop (like a sync HTTP poll)
    await asyncio.sleep(0.2)
    bridge.is_connected = False
    await task
    # The 0.3 s stall is filled with silence instead of being lost.
    assert _mic_seconds(bridge, ws) == pytest.approx(0.7, abs=0.08)


@pytest.mark.asyncio
async def test_silence_is_withheld_while_speech_flows_and_fills_after():
    bridge = _make_bridge()
    ws = bridge._ws = _RecordingWS()
    task = asyncio.create_task(bridge._background_silence_loop())
    await asyncio.sleep(0.1)

    frame = b"\x01\x00" * (SAMPLE_RATE // 50)
    for _ in range(25):  # 0.5 s of speech
        await bridge.receive_audio_from_test_agent(frame)
        await asyncio.sleep(0.02)
    bridge.mark_user_audio_done()
    await asyncio.sleep(0.2)
    bridge.is_connected = False
    await task

    # Total stream ~= wall time: no silence was mixed under the speech (it would
    # exceed elapsed), and sleep overshoot during speech was topped up after.
    assert _mic_seconds(bridge, ws) == pytest.approx(0.1 + 0.5 + 0.2, abs=0.1)
