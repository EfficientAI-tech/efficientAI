"""Unit tests for call-import user insights batching and helpers."""

from __future__ import annotations

import math

from app.services.call_import_user_insights import (
    MAX_LLM_CALLS_DEFAULT,
    MAX_LLM_CALLS_MAX,
    SYNTHESIS_CALLS,
    build_row_payload,
    compute_extraction_plan,
    max_extraction_calls,
    normalize_max_llm_calls,
    total_llm_calls_for_rows,
    user_insights_state_from_raw,
)
from app.models.database import CallImportEvaluation, CallImportEvaluationRow, CallImportRow


def test_normalize_max_llm_calls_defaults_and_clamps():
    assert normalize_max_llm_calls(None) == MAX_LLM_CALLS_DEFAULT
    assert normalize_max_llm_calls(10) == 20
    assert normalize_max_llm_calls(999) == MAX_LLM_CALLS_MAX
    assert normalize_max_llm_calls(100) == 100


def test_compute_extraction_plan_small_run():
    batch_size, num_batches = compute_extraction_plan(500)
    assert batch_size >= 1
    assert num_batches <= max_extraction_calls()
    assert num_batches == math.ceil(500 / batch_size)


def test_compute_extraction_plan_large_run_capped():
    batch_size, num_batches = compute_extraction_plan(2000)
    assert num_batches <= max_extraction_calls()
    assert batch_size == math.ceil(2000 / max_extraction_calls())

    batch_size_small, num_batches_small = compute_extraction_plan(
        2000, max_llm_calls=50
    )
    assert num_batches_small <= max_extraction_calls(50)
    assert batch_size_small == math.ceil(2000 / max_extraction_calls(50))


def test_total_llm_calls_includes_synthesis():
    assert (
        total_llm_calls_for_rows(100)
        == compute_extraction_plan(100)[1] + SYNTHESIS_CALLS
    )
    assert total_llm_calls_for_rows(0) == 0
    assert total_llm_calls_for_rows(5000) <= MAX_LLM_CALLS_DEFAULT
    assert total_llm_calls_for_rows(5000, max_llm_calls=80) <= 80


def test_build_row_payload_includes_transcript_and_metrics():
    evaluation = CallImportEvaluation(transcript_source="diarised")
    source_row = CallImportRow(
        conversation_id="call-42",
        row_index=3,
        transcript="prod text",
        diarised_transcript="user: hello\nagent: hi",
    )
    eval_row = CallImportEvaluationRow(
        status="completed",
        metric_scores={
            "mid-1": {
                "value": "yes",
                "rationale": "Customer asked for status update.",
            }
        },
    )
    payload = build_row_payload(
        evaluation,
        eval_row,
        source_row,
        {"mid-1": "Caller Context"},
    )
    assert payload["conversation_id"] == "call-42"
    assert "user: hello" in payload["transcript"]
    assert payload["metrics"][0]["metric"] == "Caller Context"
    assert "status update" in payload["metrics"][0]["rationale"]


def test_user_insights_state_from_raw_stale_flag():
    state = user_insights_state_from_raw(
        {
            "status": "completed",
            "insights": [],
            "generated_at": "2026-01-01T00:00:00+00:00",
            "generated_at_completed_rows": 10,
            "max_llm_calls": 100,
        },
        completed_rows=15,
    )
    assert state is not None
    assert state.is_stale is True
    assert state.max_llm_calls == 100
