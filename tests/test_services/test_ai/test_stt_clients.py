"""Service-layer tests for STT client adapters.

Each ``transcribe_<provider>`` function lives under
``app.services.ai.stt_clients.<provider>``. We verify that each adapter
correctly normalises the upstream provider's response into our common
``{text, language, segments}`` shape.

For providers that import ``httpx`` at module load time
(elevenlabs / smallest), patching ``sys.modules["httpx"]`` after the
fact has no effect — we instead replace the already-bound ``httpx``
attribute on the provider module so the wrapper uses our fake.

For providers that import their SDK lazily inside the function
(openai / deepgram), ``monkeypatch.setitem(sys.modules, "openai", ...)``
works because the import happens fresh on every call.
"""

import sys
import types

from app.services.ai.stt_clients import (
    deepgram as deepgram_module,
    elevenlabs as elevenlabs_module,
    openai as openai_module,
    smallest as smallest_module,
)


def _make_fake_httpx_module(payload, *, status_code=200):
    """Build a stand-in for the ``httpx`` module that returns ``payload``."""

    class _Resp:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return payload

    captured = {"calls": []}

    class _Client:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def post(self, url, **kwargs):
            captured["calls"].append({"url": url, **kwargs})
            return _Resp()

    fake = types.ModuleType("httpx")
    fake.Client = _Client  # type: ignore[attr-defined]
    fake._captured = captured  # type: ignore[attr-defined]
    fake._Resp = _Resp  # type: ignore[attr-defined]
    return fake


def test_transcribe_openai_returns_text_language_segments(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    transcript = types.SimpleNamespace(
        text="hello world",
        language="en",
        segments=[
            {"start": 0.0, "end": 1.0, "text": "hello world"},
        ],
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
    # The wrapper imports ``openai`` lazily inside the function so a
    # sys.modules swap before the call is enough.
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    result = openai_module.transcribe_openai(str(audio), "whisper-1", "key-1")

    assert result["text"] == "hello world"
    assert result["language"] == "en"
    assert len(result["segments"]) == 1
    assert result["segments"][0]["text"] == "hello world"


def test_transcribe_openai_falls_back_to_plain_json_for_gpt4o(monkeypatch, tmp_path):
    """Non-whisper-1 models go through the ``response_format='json'`` branch."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    captured: dict[str, dict] = {}
    transcript = types.SimpleNamespace(text="ok", language=None, segments=None)

    class _Transcriptions:
        @staticmethod
        def create(**kwargs):
            captured["kwargs"] = kwargs
            return transcript

    class _Audio:
        transcriptions = _Transcriptions()

    class _OpenAIClient:
        def __init__(self, api_key):
            self.audio = _Audio()

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _OpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    openai_module.transcribe_openai(str(audio), "gpt-4o-transcribe", "key-1", "en")

    assert captured["kwargs"]["response_format"] == "json"
    assert "timestamp_granularities" not in captured["kwargs"]
    assert captured["kwargs"]["language"] == "en"


def test_transcribe_elevenlabs_uses_httpx_client(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    fake = _make_fake_httpx_module(
        {"text": "transcribed", "language_code": "en"}
    )
    # The provider imports httpx at module load, so we have to replace
    # the already-bound name on the module rather than swapping
    # sys.modules. Same trick used for smallest below.
    monkeypatch.setattr(elevenlabs_module, "httpx", fake)

    result = elevenlabs_module.transcribe_elevenlabs(
        str(audio), "scribe_v2", "key-1"
    )

    assert result["text"] == "transcribed"
    assert result["language"] == "en"
    assert result["segments"] == []
    # The URL the wrapper hit is preserved on the fake so we can sanity
    # check we didn't accidentally regress to a different endpoint.
    assert fake._captured["calls"][0]["url"] == elevenlabs_module.ELEVENLABS_STT_URL


def test_transcribe_smallest_extracts_transcript_field(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    fake = _make_fake_httpx_module(
        {"transcript": "  hello from smallest  ", "language": "en"}
    )
    monkeypatch.setattr(smallest_module, "httpx", fake)

    result = smallest_module.transcribe_smallest(
        str(audio), "lightning-large-v1", "key-1", "en"
    )

    assert result["text"] == "hello from smallest"
    assert result["language"] == "en"
    assert result["segments"] == []


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
    # Deepgram is also imported lazily inside the function, so the
    # sys.modules swap is sufficient.
    monkeypatch.setitem(sys.modules, "deepgram", fake_deepgram)

    result = deepgram_module.transcribe_deepgram(
        str(audio), "deepgram-nova-3", "key-1"
    )
    assert result["text"] == "hello from deepgram"
    assert result["segments"] == []


def test_transcribe_deepgram_strips_namespace_prefix(monkeypatch, tmp_path):
    """``deepgram-`` prefix in our models.json must be stripped before
    being sent to the Deepgram API (otherwise we get 403 access errors)."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    captured: dict[str, dict] = {}

    class _ListenV:
        @staticmethod
        def transcribe_file(payload, options):
            captured["payload"] = payload
            captured["options"] = options
            alt = types.SimpleNamespace(transcript="x")
            channel = types.SimpleNamespace(alternatives=[alt])
            results = types.SimpleNamespace(channels=[channel])
            return types.SimpleNamespace(results=results)

    class _ListenRest:
        @staticmethod
        def v(_):
            return _ListenV()

    class _Listen:
        rest = _ListenRest()

    class _DeepgramClient:
        def __init__(self, api_key):
            self.listen = _Listen()

    fake_deepgram = types.ModuleType("deepgram")
    fake_deepgram.DeepgramClient = _DeepgramClient
    monkeypatch.setitem(sys.modules, "deepgram", fake_deepgram)

    deepgram_module.transcribe_deepgram(
        str(audio), "deepgram-nova-3", "key-1"
    )

    assert captured["options"]["model"] == "nova-3"
