"""Tests for the transcription + configurable-LLM additions on call imports.

These cover the new pieces from migration 031 / the
``call_import_diarization_eval_viz`` plan:

* ``transcribe_call_import_row`` worker — confirms it asks the
  transcription service for *plain* text (no pyannote diarization) and
  stores the result on the row with the right provenance fields.
* The aggregation helper used by both the per-run Visualizations tab
  and the cross-run Insights tab.
* The Run Evaluation create payload validation for ``llm_provider``,
  ``metric_llm_overrides`` and ``auto_transcribe``.
* The transcribe API endpoints (skip / queue counts).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# transcribe_call_import_row worker — plain-transcript mode
# ---------------------------------------------------------------------------


def test_transcribe_worker_calls_service_with_diarization_disabled():
    """The worker should request a plain transcript, never run pyannote."""
    from app.workers.tasks import transcribe_call_import_row as task_module

    captured: dict = {}

    def _fake_transcribe(**kwargs):
        captured.update(kwargs)
        return {
            "transcript": "  hello world  ",
            "speaker_segments": None,
        }

    fake_service = SimpleNamespace(transcribe=_fake_transcribe)

    fake_row = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        recording_s3_key="s3://bucket/key.wav",
        transcript=None,
        transcript_status="idle",
        transcript_error=None,
        transcript_source=None,
        transcript_provider=None,
        transcript_model=None,
        transcribed_at=None,
        celery_task_id=None,
    )

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.first.return_value = fake_row

    fake_db = SimpleNamespace(
        query=lambda *_a, **_kw: fake_query,
        commit=lambda: None,
        close=lambda: None,
    )

    with patch.object(task_module, "SessionLocal", lambda: fake_db), patch(
        "app.services.ai.transcription_service.transcription_service",
        fake_service,
    ):
        result = task_module.transcribe_call_import_row_task.run(
            str(fake_row.id),
            "deepgram",
            "nova-2",
        )

    assert result["status"] == "completed"
    # Diarization must be off — that's the whole point of the simplification.
    assert captured.get("enable_speaker_diarization") is False
    # Plain transcript is stored, stripped, with the right provenance fields.
    assert fake_row.transcript == "hello world"
    assert fake_row.transcript_source == "transcribed"
    assert fake_row.transcript_provider == "deepgram"
    assert fake_row.transcript_model == "nova-2"
    assert fake_row.transcript_status == "completed"
    assert fake_row.transcript_error is None


def test_transcribe_worker_marks_failed_on_empty_transcript():
    from app.workers.tasks import transcribe_call_import_row as task_module

    fake_service = SimpleNamespace(
        transcribe=lambda **_kw: {"transcript": "   ", "speaker_segments": None}
    )

    fake_row = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        recording_s3_key="s3://bucket/key.wav",
        transcript=None,
        transcript_status="idle",
        transcript_error=None,
        celery_task_id=None,
    )

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.first.return_value = fake_row

    fake_db = SimpleNamespace(
        query=lambda *_a, **_kw: fake_query,
        commit=lambda: None,
        close=lambda: None,
    )

    with patch.object(task_module, "SessionLocal", lambda: fake_db), patch(
        "app.services.ai.transcription_service.transcription_service",
        fake_service,
    ):
        result = task_module.transcribe_call_import_row_task.run(
            str(fake_row.id),
            "deepgram",
            "nova-2",
        )

    assert result == {"status": "failed", "reason": "empty_transcript"}
    assert fake_row.transcript_status == "failed"
    assert "empty" in (fake_row.transcript_error or "").lower()


# ---------------------------------------------------------------------------
# Aggregate helper used by the Visualizations + Insights tabs
# ---------------------------------------------------------------------------


def test_compute_metric_aggregates_handles_numeric_and_categorical():
    from app.api.v1.routes.call_import_evaluations import (
        _compute_metric_aggregates,
    )

    # Stub out _metrics_for_ids so the helper doesn't go to the DB.
    metric_id_num = uuid4()
    metric_id_cat = uuid4()
    fake_metric_num = SimpleNamespace(
        id=metric_id_num, name="Adherence", metric_type="rating"
    )
    fake_metric_cat = SimpleNamespace(
        id=metric_id_cat, name="Outcome", metric_type="pass_fail"
    )

    evaluation = SimpleNamespace(
        organization_id=uuid4(),
        selected_metric_ids=[str(metric_id_num), str(metric_id_cat)],
    )

    eval_rows = [
        SimpleNamespace(
            metric_scores={
                str(metric_id_num): {"value": 0.5, "type": "rating"},
                str(metric_id_cat): {"value": "pass", "type": "pass_fail"},
            }
        ),
        SimpleNamespace(
            metric_scores={
                str(metric_id_num): {"value": 0.75, "type": "rating"},
                str(metric_id_cat): {"value": "fail", "type": "pass_fail"},
            }
        ),
        SimpleNamespace(
            metric_scores={
                str(metric_id_num): {
                    "value": None,
                    "type": "rating",
                    "skipped": "audio_required",
                },
                str(metric_id_cat): {"value": "pass", "type": "pass_fail"},
            }
        ),
    ]

    with patch(
        "app.api.v1.routes.call_import_evaluations._metrics_for_ids",
        return_value=[fake_metric_num, fake_metric_cat],
    ):
        aggregates = _compute_metric_aggregates(
            db=MagicMock(), evaluation=evaluation, eval_rows=eval_rows
        )

    by_id = {a.metric_id: a for a in aggregates}
    num_agg = by_id[str(metric_id_num)]
    cat_agg = by_id[str(metric_id_cat)]

    # Numeric metric: only completed values count toward stats; skipped
    # entries are tracked separately.
    assert num_agg.count == 2
    assert num_agg.skipped_count == 1
    assert pytest.approx(num_agg.mean, rel=1e-6) == 0.625
    assert num_agg.min == 0.5
    assert num_agg.max == 0.75
    assert len(num_agg.histogram_buckets) >= 1

    # Categorical metric: value_counts beats histogram; ranked by frequency.
    assert cat_agg.count == 3
    labels = [vc.label for vc in cat_agg.value_counts]
    assert labels[0] == "pass"
    assert {vc.label for vc in cat_agg.value_counts} == {"pass", "fail"}


def test_compute_metric_aggregates_treats_booleans_as_categorical():
    """Booleans should not collapse into a degenerate {0,1} histogram."""
    from app.api.v1.routes.call_import_evaluations import (
        _compute_metric_aggregates,
    )

    metric_id = uuid4()
    fake_metric = SimpleNamespace(
        id=metric_id, name="Resolved", metric_type="binary"
    )

    evaluation = SimpleNamespace(
        organization_id=uuid4(),
        selected_metric_ids=[str(metric_id)],
    )
    eval_rows = [
        SimpleNamespace(metric_scores={str(metric_id): {"value": True}}),
        SimpleNamespace(metric_scores={str(metric_id): {"value": False}}),
        SimpleNamespace(metric_scores={str(metric_id): {"value": True}}),
    ]

    with patch(
        "app.api.v1.routes.call_import_evaluations._metrics_for_ids",
        return_value=[fake_metric],
    ):
        aggregates = _compute_metric_aggregates(
            db=MagicMock(), evaluation=evaluation, eval_rows=eval_rows
        )

    [agg] = aggregates
    # Histogram should be empty (all values are bool); category_counts wins.
    assert agg.histogram_buckets == []
    label_counts = {vc.label: vc.count for vc in agg.value_counts}
    assert label_counts == {"true": 2, "false": 1}


# ---------------------------------------------------------------------------
# Run Evaluation create payload — LLM + auto_transcribe validation
# ---------------------------------------------------------------------------


def test_create_evaluation_payload_validates_llm_provider_and_model_pair():
    from app.models.schemas import (
        CallImportEvaluationCreate,
        CallImportEvaluationLLMOverride,
    )

    # Both empty: ok (legacy default).
    payload = CallImportEvaluationCreate(metric_ids=[uuid4()])
    assert payload.llm_provider is None
    assert payload.llm_model is None

    # Override with both: ok.
    payload = CallImportEvaluationCreate(
        metric_ids=[uuid4()],
        llm_provider="anthropic",
        llm_model="claude-3-opus",
    )
    assert payload.llm_provider == "anthropic"
    assert payload.llm_model == "claude-3-opus"

    # Per-metric overrides round-trip cleanly.
    metric_id = uuid4()
    payload = CallImportEvaluationCreate(
        metric_ids=[metric_id],
        metric_llm_overrides={
            str(metric_id): CallImportEvaluationLLMOverride(
                provider="openai", model="gpt-4o"
            )
        },
    )
    assert payload.metric_llm_overrides is not None
    assert (
        payload.metric_llm_overrides[str(metric_id)].provider == "openai"
    )


# ---------------------------------------------------------------------------
# transcribe_call_import endpoint helper
# ---------------------------------------------------------------------------


def test_select_rows_for_transcription_skips_rows_with_existing_transcripts():
    """``only_missing=True`` (default) keeps existing transcripts."""
    from app.api.v1.routes.call_imports import _select_rows_for_transcription
    from app.models.schemas import CallImportTranscribeRequest

    call_import = SimpleNamespace(id=uuid4())

    fake_rows = [
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key="s3-1",
            transcript="present",
            row_index=0,
        ),
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key="s3-2",
            transcript=None,
            row_index=1,
        ),
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key=None,  # no recording -> skip
            transcript=None,
            row_index=2,
        ),
    ]

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = SimpleNamespace(
        all=lambda: fake_rows
    )

    fake_db = SimpleNamespace(query=lambda *_: fake_query)

    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        only_missing=True,
        overwrite_existing=False,
    )
    selected, skip_counts = _select_rows_for_transcription(
        fake_db, call_import, payload
    )

    # Only the row with no transcript and a recording should be selected.
    assert len(selected) == 1
    assert selected[0].recording_s3_key == "s3-2"
    assert skip_counts.get("transcript_present") == 1
    assert skip_counts.get("no_recording") == 1


def test_select_rows_for_transcription_overwrite_replaces_existing():
    from app.api.v1.routes.call_imports import _select_rows_for_transcription
    from app.models.schemas import CallImportTranscribeRequest

    call_import = SimpleNamespace(id=uuid4())

    fake_rows = [
        SimpleNamespace(
            id=uuid4(),
            recording_s3_key="s3-1",
            transcript="present",
            row_index=0,
        ),
    ]
    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = SimpleNamespace(
        all=lambda: fake_rows
    )
    fake_db = SimpleNamespace(query=lambda *_: fake_query)

    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        only_missing=True,
        overwrite_existing=True,
    )
    selected, skip_counts = _select_rows_for_transcription(
        fake_db, call_import, payload
    )

    assert len(selected) == 1
    assert skip_counts == {}


def test_select_rows_for_transcription_raises_on_unknown_row_id():
    from app.api.v1.routes.call_imports import _select_rows_for_transcription
    from app.models.schemas import CallImportTranscribeRequest

    call_import = SimpleNamespace(id=uuid4())
    requested_id = uuid4()

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = SimpleNamespace(all=lambda: [])
    fake_db = SimpleNamespace(query=lambda *_: fake_query)

    payload = CallImportTranscribeRequest(
        stt_provider="deepgram", stt_model="nova-2"
    )

    with pytest.raises(HTTPException) as exc:
        _select_rows_for_transcription(
            fake_db, call_import, payload, requested_row_ids=[requested_id]
        )
    assert exc.value.status_code == 400
    assert str(requested_id) in exc.value.detail
