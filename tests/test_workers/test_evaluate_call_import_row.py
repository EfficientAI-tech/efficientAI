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
    assert "Transcript" in (eval_rows[0].error_message or "")
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
