"""Tests for user-insights cancel and checkpoint helpers."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.call_import_user_insights_wave import (
    estimate_user_insights_total_llm_calls,
    reconcile_user_insights_job_header,
    resume_user_insights_job_header,
)
from app.services.evaluation_analysis_checkpoints import (
    USER_INSIGHTS_CANCELLED_BY_USER_ERROR,
    classify_task_run,
    claim_still_owns_header,
    completed_rows_from_batches,
    merge_extractions_from_batches,
    merge_theme_counts_from_batches,
    normalize_transcript_source,
    progress_header,
    rows_completed_for_batches,
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


def test_progress_header_clamps_completed_rows():
    header = progress_header(
        completed_rows=350,
        total_rows=277,
        completed_batches=1,
        total_batches=1,
    )
    assert header["completed_rows"] == 277


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


def test_progress_header_clamps_completed_batches():
    header = progress_header(
        completed_rows=10,
        total_rows=277,
        completed_batches=9,
        total_batches=1,
    )
    assert header["completed_batches"] == 1


def test_rows_completed_for_batches_uses_page_size_and_caps():
    assert rows_completed_for_batches(0, 277) == 0
    assert rows_completed_for_batches(1, 277) == 250
    assert rows_completed_for_batches(2, 277) == 277
    assert rows_completed_for_batches(1, 1200) == 250
    assert rows_completed_for_batches(5, 1200) == 1200
    assert rows_completed_for_batches(9, 1200) == 1200


def test_in_progress_batches_are_not_merged():
    batch = EvaluationAnalysisBatch(
        evaluation_id=uuid4(),
        job_kind="user_insights",
        job_run_id=uuid4(),
        batch_index=0,
        status="in_progress",
        payload={
            "theme_counts": {"Half-written": 3},
            "extractions": [{"conversation_id": "c1", "themes": ["x"], "quote": ""}],
            "rows_processed": 25,
        },
    )
    assert merge_theme_counts_from_batches([batch]) == {}
    assert merge_extractions_from_batches([batch]) == []
    assert completed_rows_from_batches([batch]) == 0


def test_completed_rows_from_batches_ignores_duplicate_batch_indexes():
    run_id = uuid4()
    batches = [
        EvaluationAnalysisBatch(
            evaluation_id=uuid4(),
            job_kind="user_insights",
            job_run_id=run_id,
            batch_index=0,
            status="completed",
            payload={"rows_processed": 250},
        ),
        EvaluationAnalysisBatch(
            evaluation_id=uuid4(),
            job_kind="user_insights",
            job_run_id=run_id,
            batch_index=0,
            status="completed",
            payload={"rows_processed": 250},
        ),
        EvaluationAnalysisBatch(
            evaluation_id=uuid4(),
            job_kind="user_insights",
            job_run_id=run_id,
            batch_index=1,
            status="completed",
            payload={"rows_processed": 77},
        ),
    ]
    assert completed_rows_from_batches(batches) == 327


def test_user_insights_llm_estimate_matches_extraction_plan():
    # 277 rows span two 250-row checkpoint pages (250 + 27).
    assert estimate_user_insights_total_llm_calls(277) == 7  # 6 passes + synthesis
    assert estimate_user_insights_total_llm_calls(0) == 0
    # 1200 rows span five pages of 250/250/250/250/200.
    assert estimate_user_insights_total_llm_calls(1200) == 26


def test_reconcile_header_repairs_legacy_budget_and_overcount():
    """Legacy headers carried a 140-call sampling budget and stale row counts."""
    db = MagicMock()
    evaluation = MagicMock()
    evaluation.id = uuid4()
    header = {
        "status": "running",
        "llm_calls_used": 14,
        "progress": {
            "completed_rows": 350,
            "total_rows": 300,
            "completed_batches": 4,
            "total_batches": 0,
            "completed_llm_calls": 1,
            "total_llm_calls": 140,
        },
    }
    with patch(
        "app.services.call_import_user_insights_wave.count_completed_evaluation_row_pairs",
        return_value=277,
    ):
        reconciled = reconcile_user_insights_job_header(db, evaluation, header)

    progress = reconciled["progress"]
    assert progress["total_rows"] == 277
    assert progress["total_batches"] == 2
    assert progress["completed_batches"] == 2
    assert progress["completed_rows"] <= 277
    assert progress["total_llm_calls"] == 7
    # Extraction passes must never move backwards after a resume.
    assert reconciled["llm_calls_used"] == 14
    assert progress["completed_llm_calls"] == 14


def test_resume_header_keeps_checkpoints_and_swaps_model():
    """Resume must not reset batch progress, and may switch LLM."""
    db = MagicMock()
    evaluation = MagicMock()
    evaluation.id = uuid4()
    prior = {
        "status": "cancelled",
        "job_run_id": str(uuid4()),
        "provider": "openrouter",
        "model": "google/gemini-3.5-flash",
        "transcript_source": "diarised",
        "cursor": {"row_index": 249, "evaluation_row_id": str(uuid4())},
        "llm_calls_used": 10,
        "progress": {
            "completed_rows": 250,
            "total_rows": 1200,
            "completed_batches": 1,
            "total_batches": 5,
            "completed_llm_calls": 10,
            "total_llm_calls": 26,
            "phase": "rows",
        },
    }
    with patch(
        "app.services.call_import_user_insights_wave.count_completed_evaluation_row_pairs",
        return_value=1200,
    ):
        resumed = resume_user_insights_job_header(
            db,
            evaluation,
            prior,
            transcript_source="diarised",
            provider="openai",
            model="gpt-5-nano",
        )

    assert resumed["status"] == "running"
    assert resumed["job_run_id"] == prior["job_run_id"]
    assert resumed["cursor"] == prior["cursor"]
    assert resumed["provider"] == "openai"
    assert resumed["model"] == "gpt-5-nano"
    assert resumed["llm_calls_used"] == 10
    assert resumed["progress"]["completed_batches"] == 1
    assert resumed["progress"]["completed_rows"] == 250
    assert resumed["progress"]["total_batches"] == 5
    assert resumed["progress"]["total_llm_calls"] == 26


def test_unclaimed_task_does_not_adopt_a_replacement_run():
    header_run = str(uuid4())
    state, run_id = classify_task_run({"job_run_id": header_run}, None)
    assert state == "unclaimed"
    assert run_id is None
    assert claim_still_owns_header({"job_run_id": header_run}, None) is False


def test_stale_claim_does_not_own_a_replacement_header():
    old_run = str(uuid4())
    new_run = str(uuid4())
    state, run_id = classify_task_run({"job_run_id": new_run}, old_run)
    assert state == "stale"
    assert run_id is None
    assert claim_still_owns_header({"job_run_id": new_run}, old_run) is False


def test_matching_claim_owns_the_header():
    run = str(uuid4())
    state, run_id = classify_task_run({"job_run_id": run}, run)
    assert state == "owned"
    assert str(run_id) == run
    assert claim_still_owns_header({"job_run_id": run}, run) is True
