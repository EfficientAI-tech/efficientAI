from datetime import date

from app.services.call_imports.evaluation_report_period import (
    evaluation_report_period_is_current,
    report_period_from_recording_bounds,
)


def test_report_period_from_recording_bounds_uses_latest_date_for_week():
    start, end, label, display = report_period_from_recording_bounds(
        date(2026, 10, 1),
        date(2026, 10, 19),
    )
    assert start == date(2026, 10, 1)
    assert end == date(2026, 10, 19)
    assert label == "2026-W43"
    assert "W43" in display


def test_evaluation_report_period_is_current_matches_completed_rows():
    class Eval:
        completed_rows = 10
        report_period_at_count = 10
        report_period_start = date(2026, 10, 1)

    assert evaluation_report_period_is_current(Eval()) is True

    class Stale:
        completed_rows = 11
        report_period_at_count = 10
        report_period_start = date(2026, 10, 1)

    assert evaluation_report_period_is_current(Stale()) is False
