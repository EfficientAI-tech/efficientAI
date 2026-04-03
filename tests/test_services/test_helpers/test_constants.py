"""Unit tests for evaluator helper constants."""

from app.workers.tasks.helpers.constants import (
    AUDIO_ONLY_METRIC_NAMES,
    REMOVED_EVALUATION_METRIC_NAMES,
)


def test_removed_metrics_contains_expected_legacy_metric():
    assert "clarity and empathy" in REMOVED_EVALUATION_METRIC_NAMES


def test_audio_only_metrics_include_core_audio_dimensions():
    expected = {"pitch variance", "jitter", "shimmer", "hnr", "mos score"}
    assert expected.issubset(AUDIO_ONLY_METRIC_NAMES)
