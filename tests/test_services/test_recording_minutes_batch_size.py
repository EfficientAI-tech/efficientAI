from app.services.call_imports.eval_flexprice_billing import (
    recording_minutes_batch_size,
)


def test_million_rows_is_about_fifty_events():
    size = recording_minutes_batch_size(1_000_000)
    assert size == 20_000
    assert 1_000_000 // size == 50


def test_fifty_thousand_rows_is_about_fifty_events():
    size = recording_minutes_batch_size(50_000)
    assert size == 1_000
    assert 50_000 // size == 50


def test_small_runs_cannot_exceed_one_event_per_row():
    assert recording_minutes_batch_size(7) == 1
    assert recording_minutes_batch_size(10) == 1
    assert recording_minutes_batch_size(0) == 1
    assert recording_minutes_batch_size(100) == 2
