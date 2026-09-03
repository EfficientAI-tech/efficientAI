"""Tests for Voice AI provider metric enrichment helpers."""

from app.services.playground.post_call_processing import (
    call_metrics_indicate_ended,
    provider_metrics_enriched,
)


def test_call_metrics_indicate_ended_vapi():
    assert call_metrics_indicate_ended({"status": "ended", "endedAt": "2026-01-01T00:00:00Z"})


def test_provider_metrics_enriched_vapi_performance():
    metrics = {
        "status": "ended",
        "analysis": {},
        "artifact": {"performanceMetrics": {"turnLatencies": [{"turnLatency": 100}]}},
    }
    assert provider_metrics_enriched("vapi", metrics)


def test_provider_metrics_enriched_retell_analysis():
    metrics = {"call_status": "ended", "call_analysis": {"call_summary": "ok"}}
    assert provider_metrics_enriched("retell", metrics)
