"""Service-layer tests for STT client adapters."""

import importlib.util
import sys
import types
from pathlib import Path

_STT_CLIENTS_PATH = Path(__file__).resolve().parents[3] / "app" / "services" / "ai" / "stt_clients.py"
_STT_SPEC = importlib.util.spec_from_file_location("stt_clients_under_test", _STT_CLIENTS_PATH)
stt_clients = importlib.util.module_from_spec(_STT_SPEC)
assert _STT_SPEC is not None and _STT_SPEC.loader is not None
_STT_SPEC.loader.exec_module(stt_clients)


def test_transcribe_openai_parses_segments_and_words(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    class _Word:
        def __init__(self, word, start_time, end_time):
            self.word = word
            self.start_time = start_time
            self.end_time = end_time

    transcript = types.SimpleNamespace(
        text="hello world",
        language="en",
        segments=[{"start": 0.0, "end": 1.0, "text": "hello world"}],
        words=[_Word("hello", 0.0, 0.4), _Word("world", 0.5, 1.0)],
    )

    class _Transcriptions:
        @staticmethod
        def create(**_kwargs):
            return transcript

    class _Audio:
        transcriptions = _Transcriptions()

    class _OpenAIClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.audio = _Audio()

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _OpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    result = stt_clients.transcribe_openai(str(audio), "whisper-1", "key-1")

    assert result["text"] == "hello world"
    assert result["language"] == "en"
    assert len(result["segments"]) == 1
    assert len(result["words"]) == 2


def test_transcribe_elevenlabs_uses_httpx_payload(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    class _Resp:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"text": "transcribed", "language_code": "en"}

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.post = lambda *args, **kwargs: _Resp()
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    result = stt_clients.transcribe_elevenlabs(str(audio), "scribe_v2", "key-1")
    assert result["text"] == "transcribed"
    assert result["language"] == "en"


def test_transcribe_deepgram_extracts_transcript(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    alt = types.SimpleNamespace(transcript="hello from deepgram")
    channel = types.SimpleNamespace(alternatives=[alt])
    results = types.SimpleNamespace(channels=[channel])
    dg_response = types.SimpleNamespace(results=results)

    class _ListenV:
        @staticmethod
        def transcribe_file(_payload, _options):
            return dg_response

    class _ListenRest:
        @staticmethod
        def v(_version):
            return _ListenV()

    class _Listen:
        rest = _ListenRest()

    class _DeepgramClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.listen = _Listen()

    fake_deepgram = types.ModuleType("deepgram")
    fake_deepgram.DeepgramClient = _DeepgramClient
    monkeypatch.setitem(sys.modules, "deepgram", fake_deepgram)

    result = stt_clients.transcribe_deepgram(str(audio), "nova-2", "key-1")
    assert result["text"] == "hello from deepgram"
