from app.services.playground.provider_call_logs import (
    _parse_json_lines,
    _parse_retell_log_text,
    normalize_provider_log_entry,
)


def test_normalize_vapi_log_entry():
    entry = normalize_provider_log_entry(
        {
            "time": "2025-09-02T18:26:45.070Z",
            "level": "info",
            "category": "transcriber",
            "message": "Soniox WebSocket request",
            "service": "deepgram",
        }
    )
    assert entry["level"] == "info"
    assert entry["category"] == "transcriber"
    assert entry["summary"] == "Soniox WebSocket request"
    assert entry["raw"]["service"] == "deepgram"


def test_parse_json_lines_handles_plain_text():
    entries = _parse_json_lines('{"message":"call.queued"}\nnot json')
    assert len(entries) == 2
    assert entries[0]["message"] == "call.queued"
    assert entries[1]["message"] == "not json"


def test_parse_retell_log_text_json_lines():
    text = '{"time":"2025-09-02T18:26:45.070Z","level":"info","category":"voice","message":"TTS chunk"}\n'
    entries = _parse_retell_log_text(text)
    assert len(entries) == 1
    normalized = normalize_provider_log_entry(entries[0])
    assert normalized["category"] == "voice"
    assert normalized["summary"] == "TTS chunk"
