"""Calls hub merge pagination helpers."""

from datetime import datetime, timezone

from app.models.database import CallRecording


def test_merge_window_slices_by_global_time_order():
    from app.services.observability.calls_hub import _obs_sort_key, _trace_sort_key

    obs_old = CallRecording(created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    obs_new = CallRecording(created_at=datetime(2024, 6, 1, tzinfo=timezone.utc))

    class Trace:
        def __init__(self, started_at):
            self.started_at = started_at

    trace_mid = Trace(datetime(2024, 3, 1, tzinfo=timezone.utc))

    merged = sorted(
        [
            (_obs_sort_key(obs_old), "obs", obs_old),
            (_obs_sort_key(obs_new), "obs", obs_new),
            (_trace_sort_key(trace_mid), "trace", trace_mid),
        ],
        key=lambda row: row[0],
        reverse=True,
    )
    kinds = [row[1] for row in merged]
    assert kinds == ["obs", "trace", "obs"]


def test_merged_row_modality_filter():
    from app.services.observability.calls_hub import _merged_row_matches_modality

    class Trace:
        component_aggregates = {"session_modality": "chat"}
        transport = "custom"

    class VoiceTrace:
        component_aggregates = {"stt_ttfb_ms": {"count": 1}}
        transport = "webrtc"

    obs = CallRecording()
    assert _merged_row_matches_modality("obs", obs, "chat") is False
    assert _merged_row_matches_modality("obs", obs, "voice") is True
    assert _merged_row_matches_modality("trace", Trace(), "chat") is True
    assert _merged_row_matches_modality("trace", VoiceTrace(), "chat") is False
    assert _merged_row_matches_modality("trace", VoiceTrace(), "voice") is True


def test_infer_session_modality_from_turns():
    from app.services.synthetic_traces.otlp_mapper import infer_session_modality_from_turns

    assert infer_session_modality_from_turns([{"extra": {"pipeline_mode": "chat"}}]) == "chat"
    assert infer_session_modality_from_turns([{"llm_ttfb_ms": 120.0}]) == "voice"
    assert infer_session_modality_from_turns([{"llm_ttfb_ms": 120.0}], transport="custom") == "chat"
    assert infer_session_modality_from_turns([{"llm_ttfb_ms": 120.0}], transport="webrtc") == "voice"
    assert infer_session_modality_from_turns([{"stt_ttfb_ms": 80.0}]) == "voice"
    assert infer_session_modality_from_turns([{"extra": {}}]) == "voice"