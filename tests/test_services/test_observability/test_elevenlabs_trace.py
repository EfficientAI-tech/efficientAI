import json
from pathlib import Path

from app.services.observability.elevenlabs_trace import (
    enrich_with_turn_metrics,
    extract_trace_id,
    normalize_elevenlabs_otlp,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "elevenlabs"


def test_extract_trace_id_from_otlp_fixture():
    payload = json.loads((FIXTURE_DIR / "conv_otel.json").read_text())
    trace_id = extract_trace_id(payload["otlp_traces"])
    assert trace_id == "0af7651916cd43dd8448eb211c80319c"


def test_normalize_elevenlabs_otlp_preserves_span_names_and_namespace():
    payload = json.loads((FIXTURE_DIR / "conv_otel.json").read_text())
    normalized = normalize_elevenlabs_otlp(
        payload["otlp_traces"],
        conversation_id=payload["conversation_id"],
        fallback_trace_id="fallback-trace",
    )

    assert normalized["trace_source"] == "elevenlabs"
    assert normalized["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    assert normalized["spans"]
    assert all(span["name"].startswith("elevenlabs.") for span in normalized["spans"])
    assert all(span["attributes"]["trace.provider"] == "elevenlabs" for span in normalized["spans"])


def test_enrich_with_turn_metrics_adds_metric_spans():
    otel = json.loads((FIXTURE_DIR / "conv_otel.json").read_text())
    conv = json.loads((FIXTURE_DIR / "conv.json").read_text())
    normalized = normalize_elevenlabs_otlp(
        otel["otlp_traces"],
        conversation_id=otel["conversation_id"],
    )
    enriched = enrich_with_turn_metrics(normalized, conv["transcript"])
    names = [span["name"] for span in enriched["spans"]]
    assert "elevenlabs.metric.asr" in names
    assert "elevenlabs.metric.llm" in names
    assert "elevenlabs.metric.tts" in names
