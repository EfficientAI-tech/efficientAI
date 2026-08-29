"""Unit tests for VoiceMaker WebSocket streaming TTS."""

import base64
import json
import pytest
from websockets.protocol import State

from efficientai.frames.frames import ErrorFrame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from efficientai.services.voicemaker.tts import (
    VOICEMAKER_WS_URL,
    VoiceMakerTTSService,
    build_voicemaker_ws_payload,
    normalize_voicemaker_engine,
    pcm_from_voicemaker_audio,
)


def _wav_bytes(pcm: bytes) -> bytes:
    return b"RIFF" + b"\x00" * 40 + pcm


class FakeWebSocket:
    def __init__(self, incoming=None, state=State.OPEN):
        self.incoming = list(incoming or [])
        self.sent = []
        self.state = state

    async def send(self, message):
        self.sent.append(message)

    async def close(self):
        self.state = State.CLOSED

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming:
            raise StopAsyncIteration
        return self.incoming.pop(0)


def test_normalize_voicemaker_engine_strips_prefix():
    assert normalize_voicemaker_engine("voicemaker-neural") == "neural"
    assert normalize_voicemaker_engine("neural") == "neural"
    assert normalize_voicemaker_engine(None) is None


def test_build_voicemaker_ws_payload_uses_wav_and_required_fields():
    payload = build_voicemaker_ws_payload(
        text="Welcome to Voicemaker API.",
        voice_id="ai3-Jony",
        language_code="en-US",
        sample_rate=24000,
        engine="voicemaker-neural",
    )

    assert payload["VoiceId"] == "ai3-Jony"
    assert payload["Text"] == "Welcome to Voicemaker API."
    assert payload["LanguageCode"] == "en-US"
    assert payload["OutputFormat"] == "wav"
    assert payload["SampleRate"] == "24000"
    assert payload["Engine"] == "neural"
    assert "ResponseType" not in payload


def test_pcm_from_voicemaker_audio_strips_riff_header():
    pcm = b"\x01\x02\x03\x04"
    encoded = base64.b64encode(_wav_bytes(pcm)).decode("ascii")

    assert pcm_from_voicemaker_audio(encoded) == pcm


def test_pcm_from_voicemaker_audio_leaves_raw_pcm_unchanged():
    pcm = b"\x11\x22\x33\x44"
    encoded = base64.b64encode(pcm).decode("ascii")

    assert pcm_from_voicemaker_audio(encoded) == pcm


def _service() -> VoiceMakerTTSService:
    tts = VoiceMakerTTSService(
        api_key="test-key",
        voice_id="ai3-Jony",
        model="voicemaker-neural",
        sample_rate=24000,
    )
    tts._sample_rate = 24000
    return tts


@pytest.mark.asyncio
async def test_connect_websocket_uses_bearer_auth(monkeypatch):
    captured = {}

    async def fake_connect(url, additional_headers=None, **_kwargs):
        captured["url"] = url
        captured["headers"] = additional_headers
        return FakeWebSocket()

    monkeypatch.setattr(
        "efficientai.services.voicemaker.tts.websocket_connect",
        fake_connect,
    )

    tts = _service()
    await tts._connect_websocket()

    assert captured["url"] == VOICEMAKER_WS_URL
    assert captured["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_run_tts_sends_json_payload_over_websocket():
    tts = _service()
    ws = FakeWebSocket()
    tts._websocket = ws

    frames = [frame async for frame in tts.run_tts("Hello there.")]

    assert any(isinstance(frame, TTSStartedFrame) for frame in frames if frame is not None)
    assert len(ws.sent) == 1
    payload = json.loads(ws.sent[0])
    assert payload["Text"] == "Hello there."
    assert payload["OutputFormat"] == "wav"
    assert payload["VoiceId"] == "ai3-Jony"
    assert payload["LanguageCode"]
    assert payload["SampleRate"] == "24000"
    assert payload["Engine"] == "neural"
    assert "ResponseType" not in payload


@pytest.mark.asyncio
async def test_receive_audio_chunk_pushes_pcm_and_stops_ttfb():
    pcm = b"\x01\x02\x03\x04"
    encoded = base64.b64encode(_wav_bytes(pcm)).decode("ascii")
    tts = _service()
    tts._websocket = FakeWebSocket(
        incoming=[json.dumps({"success": True, "audio": encoded})],
    )
    pushed = []
    ttfb_stopped = []

    async def capture(frame, direction=None):
        pushed.append(frame)

    async def stop_ttfb():
        ttfb_stopped.append(True)

    tts.push_frame = capture
    tts.stop_ttfb_metrics = stop_ttfb

    await tts._receive_messages()

    audio_frames = [frame for frame in pushed if isinstance(frame, TTSAudioRawFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].audio == pcm
    assert audio_frames[0].sample_rate == 24000
    assert ttfb_stopped == [True]


@pytest.mark.asyncio
async def test_receive_second_riff_chunk_also_strips_header():
    first = base64.b64encode(_wav_bytes(b"\x01\x02")).decode("ascii")
    second = base64.b64encode(_wav_bytes(b"\x03\x04")).decode("ascii")
    tts = _service()
    tts._websocket = FakeWebSocket(
        incoming=[
            json.dumps({"success": True, "audio": first}),
            json.dumps({"success": True, "audio": second}),
        ],
    )
    pushed = []

    async def capture(frame, direction=None):
        pushed.append(frame)

    async def noop():
        return None

    tts.push_frame = capture
    tts.stop_ttfb_metrics = noop

    await tts._receive_messages()

    audio = [frame.audio for frame in pushed if isinstance(frame, TTSAudioRawFrame)]
    assert audio == [b"\x01\x02", b"\x03\x04"]


@pytest.mark.asyncio
async def test_receive_is_final_pushes_stopped_frame():
    pcm = base64.b64encode(b"\x01\x02").decode("ascii")
    tts = _service()
    tts._started = True
    tts._websocket = FakeWebSocket(
        incoming=[json.dumps({"success": True, "audio": pcm, "isFinal": True})],
    )
    pushed = []

    async def capture(frame, direction=None):
        pushed.append(frame)

    async def noop():
        return None

    tts.push_frame = capture
    tts.stop_ttfb_metrics = noop

    await tts._receive_messages()

    assert any(isinstance(frame, TTSStoppedFrame) for frame in pushed)
    assert tts._started is False


@pytest.mark.asyncio
async def test_receive_error_pushes_error_frame():
    tts = _service()
    tts._websocket = FakeWebSocket(
        incoming=[
            json.dumps(
                {
                    "success": False,
                    "message": "Validation error",
                    "errors": ["Text is required and must be a non-empty string"],
                }
            )
        ],
    )
    pushed = []

    async def capture(frame, direction=None):
        pushed.append(frame)

    tts.push_frame = capture

    await tts._receive_messages()

    errors = [frame for frame in pushed if isinstance(frame, ErrorFrame)]
    assert len(errors) == 1
    assert "Validation error" in errors[0].error


@pytest.mark.asyncio
async def test_run_tts_reconnects_when_socket_closed():
    tts = _service()
    tts._websocket = FakeWebSocket(state=State.CLOSED)
    reconnected = []

    async def fake_connect():
        reconnected.append(True)
        tts._websocket = FakeWebSocket(state=State.OPEN)

    tts._connect = fake_connect

    frames = [frame async for frame in tts.run_tts("Hello")]

    assert reconnected == [True]
    assert any(isinstance(frame, TTSStartedFrame) for frame in frames if frame is not None)
    assert len(tts._websocket.sent) == 1
