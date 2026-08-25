"""Tests for Celery Beat platform schedule."""

from app.workers.config import _platform_beat_schedule, _usage_flush_beat_seconds


def test_usage_flush_beat_seconds_defaults_to_120():
    assert _usage_flush_beat_seconds() >= 30.0


def test_usage_flush_beat_seconds_respects_env(monkeypatch):
    monkeypatch.setenv("USAGE_FLUSH_BEAT_SECONDS", "90")
    assert _usage_flush_beat_seconds() == 90.0


def test_usage_flush_beat_seconds_clamps_minimum(monkeypatch):
    monkeypatch.setenv("USAGE_FLUSH_BEAT_SECONDS", "5")
    assert _usage_flush_beat_seconds() == 30.0


def test_platform_beat_schedule_has_four_entries():
    schedule = _platform_beat_schedule()
    assert set(schedule.keys()) == {
        "flush-usage-counters",
        "evaluate-alerts",
        "refresh-fx-rates",
        "prune-oss-usage-history",
    }


def test_flush_schedule_uses_env_interval(monkeypatch):
    monkeypatch.setenv("USAGE_FLUSH_BEAT_SECONDS", "180")
    schedule = _platform_beat_schedule()
    assert schedule["flush-usage-counters"]["schedule"] == 180.0
