"""Tests for user-insights cancel and checkpoint helpers."""

from uuid import uuid4

from app.services.evaluation_analysis_checkpoints import (
    USER_INSIGHTS_CANCELLED_BY_USER_ERROR,
    merge_theme_counts_from_batches,
    normalize_transcript_source,
    user_insights_raw_is_cancelled,
)
from app.models.database import EvaluationAnalysisBatch


def test_normalize_transcript_source_defaults_to_diarised():
    assert normalize_transcript_source(None) == "diarised"
    assert normalize_transcript_source("production") == "production"
    assert normalize_transcript_source("invalid") == "diarised"


def test_user_insights_raw_is_cancelled():
    assert user_insights_raw_is_cancelled({"status": "cancelled"}) is True
    assert user_insights_raw_is_cancelled(
        {"error_message": USER_INSIGHTS_CANCELLED_BY_USER_ERROR}
    ) is True
    assert user_insights_raw_is_cancelled({"status": "running"}) is False


def test_merge_theme_counts_from_batches():
    batch = EvaluationAnalysisBatch(
        evaluation_id=uuid4(),
        job_kind="user_insights",
        job_run_id=uuid4(),
        batch_index=0,
        payload={"theme_counts": {"First-time caller": 2, "Status check": 1}},
    )
    merged = merge_theme_counts_from_batches([batch])
    assert merged["First-time caller"] == 2
    assert merged["Status check"] == 1
