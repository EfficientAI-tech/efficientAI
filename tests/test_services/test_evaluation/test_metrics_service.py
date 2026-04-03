"""Service-layer tests for metrics calculation."""

import math

from app.services.evaluation.metrics_service import MetricsService


def test_calculate_wer_exact_match_is_zero():
    assert MetricsService.calculate_wer("hello world", "hello world") == 0.0


def test_calculate_wer_empty_reference_and_non_empty_hypothesis_is_inf():
    assert math.isinf(MetricsService.calculate_wer("", "hello"))


def test_calculate_cer_counts_character_errors():
    cer = MetricsService.calculate_cer("abc", "axc")
    assert cer == 1 / 3


def test_calculate_latency_returns_seconds_and_milliseconds():
    result = MetricsService.calculate_latency(1.0, 2.5)
    assert result["latency_s"] == 1.5
    assert result["latency_ms"] == 1500.0


def test_calculate_rtf_handles_zero_audio_duration():
    assert math.isinf(MetricsService.calculate_rtf(0.0, 1.0))


def test_calculate_metrics_mixes_available_and_missing_inputs():
    service = MetricsService()
    result = service.calculate_metrics(
        metrics_requested=["wer", "cer", "latency", "rtf", "quality_score"],
        reference_text="hello world",
        hypothesis_text="hello there",
        audio_duration=2.0,
        processing_time=1.0,
    )

    assert "wer" in result and result["wer"] > 0
    assert "cer" in result and result["cer"] > 0
    assert result["latency_s"] == 1.0
    assert result["latency_ms"] == 1000.0
    assert result["rtf"] == 0.5
    assert result["quality_score"] is None
