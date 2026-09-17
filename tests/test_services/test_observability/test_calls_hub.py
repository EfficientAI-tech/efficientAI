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
