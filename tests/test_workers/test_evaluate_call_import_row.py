"""Tests for the evaluate_call_import_row Celery task and its rollup helper."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    Organization,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


class _NonClosingSession:
    """Session proxy that ignores .close() so the test can still inspect rows
    after the Celery task wraps everything in a try/finally that closes the DB.
    """

    def __init__(self, session):
        self._session = session

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._session, name)


def _seed(db_session, *, row_count: int = 1, metric_count: int = 1):
    org = Organization(id=uuid4(), name="Eval Test Org")
    db_session.add(org)
    workspace = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add(workspace)
    db_session.commit()

    metrics = []
    for i in range(metric_count):
        metric = Metric(
            id=uuid4(),
            organization_id=org.id,
            workspace_id=workspace.id,
            name=f"Metric{i}",
            description=f"Metric {i}",
            metric_type="rating",
            trigger="always",
            enabled=True,
            supported_surfaces=["agent"],
            enabled_surfaces=["agent"],
        )
        db_session.add(metric)
        metrics.append(metric)

    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        provider="exotel",
        original_filename="batch.csv",
        total_rows=row_count,
        completed_rows=row_count,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    source_rows = []
    for idx in range(row_count):
        row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org.id,
            row_index=idx,
            external_call_id=f"call-{idx}",
            transcript=f"Hello transcript {idx}",
            status=CallImportRowStatus.COMPLETED,
        )
        db_session.add(row)
        source_rows.append(row)

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=workspace.id,
        selected_metric_ids=[str(m.id) for m in metrics],
        status="pending",
        total_rows=row_count,
        completed_rows=0,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.flush()

    eval_rows = []
    for row in source_rows:
        er = CallImportEvaluationRow(
            id=uuid4(),
            evaluation_id=evaluation.id,
            call_import_row_id=row.id,
            status="pending",
            metric_scores={},
        )
        db_session.add(er)
        eval_rows.append(er)
    db_session.commit()

    return org, call_import, metrics, source_rows, evaluation, eval_rows


def _patch_dependencies(monkeypatch, db_session, *, evaluate_with_llm=None):
    """Stub SessionLocal and the LLM helper inside the eval task module."""
    from app.workers.tasks import evaluate_call_import_row as task_module

    monkeypatch.setattr(
        task_module, "SessionLocal", lambda: _NonClosingSession(db_session)
    )

    def _default_eval(*_args, **_kwargs):
        metrics = _kwargs.get("llm_metrics") or (_args[1] if len(_args) > 1 else [])
        scores = {
            str(metric.id): {
                "value": 4,
                "type": "rating",
                "metric_name": metric.name,
            }
            for metric in metrics
        }
        return scores, 0.42

    monkeypatch.setattr(
        task_module,
        "evaluate_with_llm",
        evaluate_with_llm or _default_eval,
    )

    return task_module


def test_evaluate_call_import_row_happy_path(db_session, monkeypatch):
    _, _ci, metrics, _source_rows, evaluation, eval_rows = _seed(db_session)
    eval_row = eval_rows[0]

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(eval_row.id))

    assert result["status"] == "completed"

    db_session.refresh(eval_row)
    db_session.refresh(evaluation)

    assert eval_row.status == "completed"
    assert eval_row.error_message is None
    assert str(metrics[0].id) in (eval_row.metric_scores or {})
    assert eval_row.metric_scores[str(metrics[0].id)]["value"] == 4

    assert evaluation.completed_rows == 1
    assert evaluation.failed_rows == 0
    assert evaluation.status == "completed"
    assert evaluation.finished_at is not None


def test_evaluate_call_import_row_honors_metric_subset(db_session, monkeypatch):
    """When the evaluation selects a subset of metrics, only those are scored."""
    _, _ci, metrics, _rows, evaluation, eval_rows = _seed(
        db_session, metric_count=3
    )

    # Restrict the evaluation to just the first two metrics.
    selected = metrics[:2]
    evaluation.selected_metric_ids = [str(m.id) for m in selected]
    db_session.commit()

    received_metric_ids = {}

    def _capture_eval(*_a, **kw):
        llm_metrics = kw["llm_metrics"]
        received_metric_ids["ids"] = {str(m.id) for m in llm_metrics}
        return (
            {
                str(m.id): {"value": 3, "type": "rating", "metric_name": m.name}
                for m in llm_metrics
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture_eval
    )
    task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert received_metric_ids["ids"] == {str(m.id) for m in selected}
    db_session.refresh(eval_rows[0])
    assert set(eval_rows[0].metric_scores.keys()) == {str(m.id) for m in selected}


def test_evaluate_call_import_row_marks_failed_on_empty_transcript(
    db_session, monkeypatch
):
    _, _ci, _metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    source_rows[0].transcript = "   "
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "failed"
    assert result["reason"] == "missing_transcript"

    db_session.refresh(eval_rows[0])
    db_session.refresh(evaluation)
    assert eval_rows[0].status == "failed"
    # New error message is "No production transcript for this row..."
    err = (eval_rows[0].error_message or "").lower()
    assert "transcript" in err
    assert "production" in err
    assert evaluation.failed_rows == 1
    assert evaluation.completed_rows == 0
    assert evaluation.status == "failed"


def test_evaluate_call_import_row_partial_when_mixed_outcomes(db_session, monkeypatch):
    """If sibling rows are already failed, the rollup should land on 'partial'."""
    _, _ci, _metrics, _source_rows, evaluation, eval_rows = _seed(
        db_session, row_count=2
    )
    # Pre-mark the second eval row as failed.
    eval_rows[1].status = "failed"
    eval_rows[1].error_message = "previous failure"
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    db_session.refresh(evaluation)
    assert evaluation.completed_rows == 1
    assert evaluation.failed_rows == 1
    assert evaluation.status == "partial"


def test_evaluate_call_import_row_handles_llm_exception(db_session, monkeypatch):
    _, _ci, _metrics, _rows, evaluation, eval_rows = _seed(db_session)

    def _raise(*_a, **_kw):
        raise RuntimeError("LLM blew up")

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_raise
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))
    assert result["status"] == "failed"

    db_session.refresh(eval_rows[0])
    db_session.refresh(evaluation)
    assert eval_rows[0].status == "failed"
    assert "LLM blew up" in (eval_rows[0].error_message or "")
    assert evaluation.status == "failed"


def test_evaluate_call_import_row_handles_missing_row(db_session, monkeypatch):
    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(uuid4()))
    assert result["status"] == "skipped"
    assert result["reason"] == "row_not_found"


def test_evaluate_call_import_row_reads_diarised_when_source_is_diarised(
    db_session, monkeypatch
):
    """When the parent evaluation's ``transcript_source = 'diarised'`` the
    worker must hand the diarised transcript (not the CSV production
    transcript) to the LLM helper."""
    _, _ci, _metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    # CSV transcript is set by _seed; populate the diarised column with
    # something distinguishable and flip the parent eval to 'diarised'.
    source_rows[0].diarised_transcript = "DIARISED ONLY VALUE"
    evaluation.transcript_source = "diarised"
    db_session.commit()

    captured: dict = {}

    def _capture(*_args, **kwargs):
        captured["transcription"] = kwargs.get("transcription")
        llm_metrics = kwargs["llm_metrics"]
        return (
            {
                str(m.id): {
                    "value": 5,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in llm_metrics
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "completed"
    assert captured["transcription"] == "DIARISED ONLY VALUE"


def test_evaluate_call_import_row_fails_when_diarised_transcript_missing(
    db_session, monkeypatch
):
    """A diarised-source evaluation must skip+fail rows whose
    ``diarised_transcript`` is empty (with a clear error message)."""
    _, _ci, _metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    source_rows[0].transcript = "production has text"
    source_rows[0].diarised_transcript = None
    evaluation.transcript_source = "diarised"
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "failed"
    assert result["reason"] == "missing_transcript"

    db_session.refresh(eval_rows[0])
    err = (eval_rows[0].error_message or "").lower()
    assert "diarised" in err
    assert "transcript" in err


# ---------------------------------------------------------------------------
# Column-input judge metrics (Metric.input_columns)
# ---------------------------------------------------------------------------


def test_evaluate_call_import_row_routes_column_metric_through_extra_context(
    db_session, monkeypatch
):
    """A metric with ``input_columns`` set must be evaluated by ``evaluate_with_llm``
    with an ``extra_context`` block built from the row's ``raw_columns`` —
    NOT against the transcript."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.input_columns = ["customer_intent", "agent_response"]
    source_rows[0].raw_columns = {
        "customer_intent": "refund please",
        "agent_response": "approved",
        "unrelated": "noise",
    }
    db_session.commit()

    captured: dict = {}

    def _capture(*_args, **kwargs):
        captured["transcription"] = kwargs.get("transcription")
        captured["extra_context"] = kwargs.get("extra_context")
        captured["metric_ids"] = [
            str(m.id) for m in kwargs["llm_metrics"]
        ]
        return (
            {
                str(m.id): {
                    "value": 5,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "completed"
    # Column-input metrics intentionally pass an empty transcript.
    assert captured["transcription"] == ""
    # Both selected headers (and ONLY those) appear in the context block.
    assert captured["extra_context"] is not None
    assert "customer_intent: refund please" in captured["extra_context"]
    assert "agent_response: approved" in captured["extra_context"]
    assert "unrelated" not in captured["extra_context"]
    assert captured["metric_ids"] == [str(metric.id)]


def test_evaluate_call_import_row_skips_column_metric_when_required_column_missing(
    db_session, monkeypatch
):
    """A column-input metric whose required header is missing or empty on
    the row is recorded as a ``columns_missing`` skip (no LLM call). When
    it is the only thing selected on the row the run hard-fails — same
    behavior as audio-only-no-recording — so users notice that their
    metric ran but produced nothing."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.input_columns = ["customer_intent", "agent_response"]
    # ``agent_response`` intentionally absent from raw_columns.
    source_rows[0].raw_columns = {"customer_intent": "refund"}
    db_session.commit()

    llm_called = {"hit": False}

    def _capture(*_args, **_kwargs):
        llm_called["hit"] = True
        return ({}, 0.0)

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "failed"
    assert result["reason"] == "no_evaluable_metrics"
    assert llm_called["hit"] is False

    db_session.refresh(eval_rows[0])
    # The skip entry is still persisted on the row so the UI can show
    # the user *which* columns were missing instead of a bare failure.
    entry = eval_rows[0].metric_scores[str(metric.id)]
    assert entry["value"] is None
    assert entry["skipped"] == "columns_missing"
    assert entry["missing_columns"] == ["agent_response"]
    assert entry["metric_name"] == metric.name


def test_evaluate_call_import_row_records_skip_alongside_other_metrics(
    db_session, monkeypatch
):
    """When a column-input metric is skipped but at least one other
    metric in the same run produced a real score, the row completes
    cleanly and the skip entry is preserved next to the real score."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(
        db_session, metric_count=2
    )
    transcript_metric, column_metric = metrics
    column_metric.input_columns = ["agent_response"]
    # ``raw_columns`` is missing the required header.
    source_rows[0].raw_columns = {"customer_intent": "refund"}
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "completed"

    db_session.refresh(eval_rows[0])
    real = eval_rows[0].metric_scores[str(transcript_metric.id)]
    assert real["value"] == 4
    skipped = eval_rows[0].metric_scores[str(column_metric.id)]
    assert skipped["skipped"] == "columns_missing"
    assert skipped["missing_columns"] == ["agent_response"]


def test_evaluate_call_import_row_mixes_transcript_and_column_metrics(
    db_session, monkeypatch
):
    """A run can select both kinds in one go — each is dispatched separately."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(
        db_session, metric_count=2
    )
    transcript_metric, column_metric = metrics
    column_metric.input_columns = ["customer_intent"]
    source_rows[0].raw_columns = {"customer_intent": "refund"}
    db_session.commit()

    invocations: list[dict] = []

    def _capture(*_args, **kwargs):
        invocations.append(
            {
                "transcription": kwargs.get("transcription"),
                "extra_context": kwargs.get("extra_context"),
                "metric_ids": [str(m.id) for m in kwargs["llm_metrics"]],
            }
        )
        return (
            {
                str(m.id): {
                    "value": 1,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))
    assert result["status"] == "completed"

    # Two LLM invocations: one per "kind" of metric.
    assert len(invocations) == 2
    by_metric = {
        invocation["metric_ids"][0]: invocation for invocation in invocations
    }
    column_call = by_metric[str(column_metric.id)]
    transcript_call = by_metric[str(transcript_metric.id)]
    assert column_call["transcription"] == ""
    assert "customer_intent: refund" in (column_call["extra_context"] or "")
    # Transcript-based metrics still receive the row's transcript and
    # NO extra_context block.
    assert transcript_call["transcription"] == "Hello transcript 0"
    assert transcript_call["extra_context"] is None

    db_session.refresh(eval_rows[0])
    assert set(eval_rows[0].metric_scores.keys()) == {
        str(transcript_metric.id),
        str(column_metric.id),
    }


def test_evaluate_call_import_row_scores_column_metric_when_transcript_empty(
    db_session, monkeypatch
):
    """A column-input metric is independent of the transcript: the row
    must still complete (and produce a real score) when the only LLM
    metric is column-based and the transcript is empty."""
    _, _ci, metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.input_columns = ["customer_intent"]
    source_rows[0].transcript = "   "
    source_rows[0].raw_columns = {"customer_intent": "refund"}
    db_session.commit()

    task_module = _patch_dependencies(monkeypatch, db_session)
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "completed"
    db_session.refresh(eval_rows[0])
    db_session.refresh(evaluation)
    assert eval_rows[0].status == "completed"
    assert str(metric.id) in (eval_rows[0].metric_scores or {})
    # No skipped entry — the column metric scored cleanly.
    assert "skipped" not in eval_rows[0].metric_scores[str(metric.id)]
    assert evaluation.status == "completed"


# ---------------------------------------------------------------------------
# Friendly-name fallback: input_columns can store either a verbatim CSV
# header or the friendly name the uploader gave a column in
# CallImport.custom_column_mapping. The worker must resolve both shapes
# against the same row's raw_columns dict.
# ---------------------------------------------------------------------------


def test_evaluate_call_import_row_resolves_friendly_name_via_custom_mapping(
    db_session, monkeypatch
):
    """A metric storing the *friendly name* the uploader chose during
    import (key of ``custom_column_mapping``) must score correctly even
    though ``raw_columns`` is keyed by the underlying *CSV header*.

    This is the path the new picker exercises: the user clicks
    "customer_intent" inside an import where they mapped that name to
    "Intent_v2", and the metric should still read the right cell."""
    _, ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.input_columns = ["customer_intent"]  # friendly name
    ci.custom_column_mapping = {"customer_intent": "Intent_v2"}
    source_rows[0].raw_columns = {"Intent_v2": "refund please"}
    db_session.commit()

    captured: dict = {}

    def _capture(*_args, **kwargs):
        captured["extra_context"] = kwargs.get("extra_context")
        return (
            {
                str(m.id): {
                    "value": 5,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "completed"
    # Prompt label uses the friendly name (what the user picked) but
    # the value comes from raw_columns["Intent_v2"] thanks to the
    # custom_column_mapping fallback.
    assert "customer_intent: refund please" in (captured["extra_context"] or "")


def test_evaluate_call_import_row_extra_columns_still_lookup_directly(
    db_session, monkeypatch
):
    """Verbatim CSV headers (from ``CallImport.extra_columns``) must
    keep working through the direct ``raw_columns`` path even when the
    import also has unrelated entries in ``custom_column_mapping`` —
    the fallback should not interfere with the existing happy path."""
    _, ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.input_columns = ["AgentName"]
    ci.extra_columns = ["AgentName"]
    ci.custom_column_mapping = {"customer_intent": "Intent_v2"}
    source_rows[0].raw_columns = {
        "AgentName": "Alice",
        "Intent_v2": "refund please",
    }
    db_session.commit()

    captured: dict = {}

    def _capture(*_args, **kwargs):
        captured["extra_context"] = kwargs.get("extra_context")
        return (
            {
                str(m.id): {
                    "value": 5,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "completed"
    assert "AgentName: Alice" in (captured["extra_context"] or "")


def test_evaluate_call_import_row_friendly_name_missing_raw_value_marked_skipped(
    db_session, monkeypatch
):
    """If the friendly name resolves through ``custom_column_mapping`` but
    the underlying CSV header is *empty* on the row, the metric is
    treated as ``columns_missing`` so the user sees a clear skip
    instead of the LLM scoring an empty input."""
    _, ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.input_columns = ["customer_intent"]
    ci.custom_column_mapping = {"customer_intent": "Intent_v2"}
    source_rows[0].raw_columns = {"Intent_v2": ""}  # blank cell
    db_session.commit()

    llm_called = {"hit": False}

    def _capture(*_args, **_kwargs):
        llm_called["hit"] = True
        return ({}, 0.0)

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(str(eval_rows[0].id))

    assert result["status"] == "failed"
    assert result["reason"] == "no_evaluable_metrics"
    assert llm_called["hit"] is False

    db_session.refresh(eval_rows[0])
    entry = eval_rows[0].metric_scores[str(metric.id)]
    assert entry["skipped"] == "columns_missing"
    # The label preserved in ``missing_columns`` is what the metric
    # actually stores — so the UI message refers to "customer_intent"
    # (what the user picked) rather than the CSV header.
    assert entry["missing_columns"] == ["customer_intent"]


# ---------------------------------------------------------------------------
# Pure unit tests for the resolver helper — easier to reason about than
# stitching a full Celery run for every casing edge case.
# ---------------------------------------------------------------------------


def test_resolve_column_value_direct_match():
    from app.workers.tasks.evaluate_call_import_row import _resolve_column_value

    assert (
        _resolve_column_value("AgentName", {"AgentName": "Alice"}, None)
        == "Alice"
    )


def test_resolve_column_value_case_insensitive_direct_match():
    from app.workers.tasks.evaluate_call_import_row import _resolve_column_value

    # User's chip stored "agentname" (lowercased) but the import
    # preserved "AgentName" — should still resolve.
    assert (
        _resolve_column_value("agentname", {"AgentName": "Alice"}, None)
        == "Alice"
    )


def test_resolve_column_value_friendly_name_fallback():
    from app.workers.tasks.evaluate_call_import_row import _resolve_column_value

    raw_columns = {"Intent_v2": "refund please"}
    mapping = {"customer_intent": "Intent_v2"}
    assert (
        _resolve_column_value("customer_intent", raw_columns, mapping)
        == "refund please"
    )


def test_resolve_column_value_friendly_name_case_insensitive():
    from app.workers.tasks.evaluate_call_import_row import _resolve_column_value

    raw_columns = {"Intent_v2": "refund please"}
    mapping = {"customer_intent": "Intent_v2"}
    assert (
        _resolve_column_value("CUSTOMER_INTENT", raw_columns, mapping)
        == "refund please"
    )


def test_resolve_column_value_returns_none_when_unresolvable():
    from app.workers.tasks.evaluate_call_import_row import _resolve_column_value

    assert (
        _resolve_column_value("nope", {"AgentName": "Alice"}, {"foo": "bar"})
        is None
    )


def test_resolve_column_value_handles_missing_mapping_gracefully():
    from app.workers.tasks.evaluate_call_import_row import _resolve_column_value

    assert _resolve_column_value("foo", {}, None) is None
    assert _resolve_column_value("foo", {}, {}) is None


# ---------------------------------------------------------------------------
# Transcript-compare judge metrics (Metric.compare_transcripts)
# ---------------------------------------------------------------------------


def _make_categorize_metric(
    name: str,
    *,
    compare_transcripts: bool = False,
    input_columns: list[str] | None = None,
):
    """Lightweight duck-typed Metric for the pure ``_categorize_metrics``
    helper tests (no DB, no SQLAlchemy session)."""
    from types import SimpleNamespace
    from uuid import uuid4

    return SimpleNamespace(
        id=uuid4(),
        name=name,
        metric_type="rating",
        compare_transcripts=compare_transcripts,
        input_columns=input_columns or [],
    )


def test_categorize_metrics_buckets_comparison_metric_when_both_transcripts_present():
    from app.workers.tasks.evaluate_call_import_row import _categorize_metrics

    cmp_metric = _make_categorize_metric(
        "Transcript Fidelity", compare_transcripts=True
    )
    regular = _make_categorize_metric("Regular")
    column = _make_categorize_metric(
        "Column Judge", input_columns=["customer_intent"]
    )

    (
        transcript_metrics,
        audio_metrics,
        column_metrics,
        comparison_metrics,
        skipped,
    ) = _categorize_metrics(
        [cmp_metric, regular, column],
        has_audio=False,
        raw_columns={"customer_intent": "refund"},
        custom_column_mapping=None,
        has_production_transcript=True,
        has_diarised_transcript=True,
    )

    assert [m.id for m in comparison_metrics] == [cmp_metric.id]
    assert [m.id for m in transcript_metrics] == [regular.id]
    assert [m for (m, _ctx) in column_metrics] == [column]
    assert audio_metrics == []
    assert skipped == {}


def test_categorize_metrics_skips_comparison_metric_when_production_missing():
    from app.workers.tasks.evaluate_call_import_row import _categorize_metrics

    cmp_metric = _make_categorize_metric(
        "Transcript Fidelity", compare_transcripts=True
    )
    (
        transcript_metrics,
        _audio,
        _columns,
        comparison_metrics,
        skipped,
    ) = _categorize_metrics(
        [cmp_metric],
        has_audio=False,
        raw_columns=None,
        has_production_transcript=False,
        has_diarised_transcript=True,
    )

    assert comparison_metrics == []
    assert transcript_metrics == []
    entry = skipped[str(cmp_metric.id)]
    assert entry["skipped"] == "comparison_missing_transcript"
    assert entry["missing_transcripts"] == ["production"]
    assert entry["value"] is None
    assert entry["metric_name"] == "Transcript Fidelity"


def test_categorize_metrics_skips_comparison_metric_when_both_transcripts_missing():
    from app.workers.tasks.evaluate_call_import_row import _categorize_metrics

    cmp_metric = _make_categorize_metric(
        "Transcript Fidelity", compare_transcripts=True
    )
    (
        _transcript_metrics,
        _audio,
        _columns,
        comparison_metrics,
        skipped,
    ) = _categorize_metrics(
        [cmp_metric],
        has_audio=False,
        raw_columns=None,
        has_production_transcript=False,
        has_diarised_transcript=False,
    )

    assert comparison_metrics == []
    entry = skipped[str(cmp_metric.id)]
    assert entry["skipped"] == "comparison_missing_transcript"
    # Order is deterministic (production checked first), so both labels
    # appear when both sides are empty.
    assert entry["missing_transcripts"] == ["production", "diarised"]


def test_evaluate_call_import_row_scores_comparison_metric_with_both_transcripts(
    db_session, monkeypatch
):
    """Happy path: a comparison metric on a row with both transcripts
    calls evaluate_with_llm exactly once and forwards the labeled
    transcript pair via the ``comparison_pair`` kwarg."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.compare_transcripts = True
    source_rows[0].transcript = "PROD speak"
    source_rows[0].diarised_transcript = "DIAR speak"
    db_session.commit()

    captured: list[dict] = []

    def _capture(*_args, **kwargs):
        captured.append(
            {
                "transcription": kwargs.get("transcription"),
                "comparison_pair": kwargs.get("comparison_pair"),
                "extra_context": kwargs.get("extra_context"),
                "metric_ids": [str(m.id) for m in kwargs["llm_metrics"]],
            }
        )
        return (
            {
                str(m.id): {
                    "value": 0.85,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.12,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "completed"
    assert len(captured) == 1
    invocation = captured[0]
    assert invocation["metric_ids"] == [str(metric.id)]
    # Comparison metrics intentionally pass an empty transcription
    # because the prompt-builder reads the pair via ``comparison_pair``.
    assert invocation["transcription"] == ""
    assert invocation["extra_context"] is None
    assert invocation["comparison_pair"] == ("PROD speak", "DIAR speak")


def test_evaluate_call_import_row_records_comparison_skip_when_diarised_missing(
    db_session, monkeypatch
):
    """A comparison metric on a row with only the production transcript
    is skipped (not hard-failed) so neighboring metrics can still score
    cleanly. When it's the only metric on the row the run hard-fails
    with ``no_evaluable_metrics`` — same shape as the column-input
    skip-only case."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.compare_transcripts = True
    source_rows[0].transcript = "PROD only"
    source_rows[0].diarised_transcript = None
    db_session.commit()

    llm_called = {"hit": False}

    def _capture(*_args, **_kwargs):
        llm_called["hit"] = True
        return ({}, 0.0)

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "failed"
    assert result["reason"] == "no_evaluable_metrics"
    assert llm_called["hit"] is False

    db_session.refresh(eval_rows[0])
    entry = eval_rows[0].metric_scores[str(metric.id)]
    assert entry["value"] is None
    assert entry["skipped"] == "comparison_missing_transcript"
    assert entry["missing_transcripts"] == ["diarised"]
    assert entry["metric_name"] == metric.name


def test_evaluate_call_import_row_mixes_comparison_with_other_metric_kinds(
    db_session, monkeypatch
):
    """A run can mix comparison + transcript + column-input metrics in
    one row. Each metric is dispatched to its own bucket and the row
    completes once every bucket has either a score or a skip entry."""
    _, _ci, metrics, source_rows, _evaluation, eval_rows = _seed(
        db_session, metric_count=3
    )
    transcript_metric, column_metric, comparison_metric = metrics
    column_metric.input_columns = ["customer_intent"]
    comparison_metric.compare_transcripts = True
    source_rows[0].raw_columns = {"customer_intent": "refund"}
    source_rows[0].transcript = "PROD text"
    source_rows[0].diarised_transcript = "DIAR text"
    db_session.commit()

    invocations: list[dict] = []

    def _capture(*_args, **kwargs):
        invocations.append(
            {
                "metric_ids": [str(m.id) for m in kwargs["llm_metrics"]],
                "transcription": kwargs.get("transcription"),
                "extra_context": kwargs.get("extra_context"),
                "comparison_pair": kwargs.get("comparison_pair"),
            }
        )
        return (
            {
                str(m.id): {
                    "value": 1,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.1,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )
    assert result["status"] == "completed"

    # Three LLM invocations: one per kind (column, comparison,
    # transcript). Ordering is implementation-defined so key by metric.
    assert len(invocations) == 3
    by_metric = {inv["metric_ids"][0]: inv for inv in invocations}

    column_call = by_metric[str(column_metric.id)]
    assert column_call["transcription"] == ""
    assert column_call["comparison_pair"] is None
    assert "customer_intent: refund" in (column_call["extra_context"] or "")

    cmp_call = by_metric[str(comparison_metric.id)]
    assert cmp_call["transcription"] == ""
    assert cmp_call["extra_context"] is None
    assert cmp_call["comparison_pair"] == ("PROD text", "DIAR text")

    transcript_call = by_metric[str(transcript_metric.id)]
    assert transcript_call["comparison_pair"] is None
    assert transcript_call["extra_context"] is None
    assert transcript_call["transcription"] == "PROD text"

    db_session.refresh(eval_rows[0])
    assert set(eval_rows[0].metric_scores.keys()) == {
        str(transcript_metric.id),
        str(column_metric.id),
        str(comparison_metric.id),
    }


def test_evaluate_call_import_row_ignores_transcript_source_for_comparison_metrics(
    db_session, monkeypatch
):
    """The run's ``transcript_source`` setting must NOT affect what a
    comparison metric reads — it always receives both transcripts as a
    labeled pair regardless of which source the parent evaluation picked."""
    _, _ci, metrics, source_rows, evaluation, eval_rows = _seed(db_session)
    metric = metrics[0]
    metric.compare_transcripts = True
    source_rows[0].transcript = "PROD text"
    source_rows[0].diarised_transcript = "DIAR text"
    # Flip the run to diarised so the legacy transcript bucket would
    # normally read from ``diarised_transcript``. Comparison metrics
    # ignore this — both sides are still passed to the LLM.
    evaluation.transcript_source = "diarised"
    db_session.commit()

    captured: list[dict] = []

    def _capture(*_args, **kwargs):
        captured.append(
            {
                "comparison_pair": kwargs.get("comparison_pair"),
                "transcription": kwargs.get("transcription"),
            }
        )
        return (
            {
                str(m.id): {
                    "value": 0.5,
                    "type": "rating",
                    "metric_name": m.name,
                }
                for m in kwargs["llm_metrics"]
            },
            0.05,
        )

    task_module = _patch_dependencies(
        monkeypatch, db_session, evaluate_with_llm=_capture
    )
    result = task_module.evaluate_call_import_row_task.run(
        str(eval_rows[0].id)
    )

    assert result["status"] == "completed"
    assert len(captured) == 1
    # Pair order is (production, diarised) — fixed by the worker, not
    # by the run's transcript_source toggle.
    assert captured[0]["comparison_pair"] == ("PROD text", "DIAR text")
    assert captured[0]["transcription"] == ""
