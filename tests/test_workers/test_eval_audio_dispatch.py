"""Tests for audio-metrics queue routing and fair dispatch integration."""

from __future__ import annotations

from unittest.mock import MagicMock
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
from app.workers.concurrency.eval_dispatch import (
    AUDIO_METRICS_QUEUE,
    EVALUATIONS_QUEUE,
    _try_dispatch_single_row,
)
from app.workers.config import celery_app


def _seed_audio_and_llm(db_session):
    org = Organization(id=uuid4(), name="Audio Dispatch Org")
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

    llm_metric = Metric(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Quality",
        description="Rate quality",
        metric_type="rating",
        trigger="always",
        enabled=True,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    audio_metric = Metric(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        name="MOS Score",
        description="Mean opinion score",
        metric_type="rating",
        trigger="always",
        enabled=True,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add_all([llm_metric, audio_metric])

    call_import = CallImport(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        provider="exotel",
        original_filename="batch.csv",
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    source_row = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=0,
        conversation_id="call-0",
        transcript="hello",
        diarised_transcript="hello",
        recording_s3_key="recordings/test.mp3",
        status=CallImportRowStatus.COMPLETED,
    )
    db_session.add(source_row)

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=workspace.id,
        selected_metric_ids=[str(llm_metric.id), str(audio_metric.id)],
        status="pending",
        total_rows=1,
        completed_rows=0,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.flush()

    eval_row = CallImportEvaluationRow(
        id=uuid4(),
        evaluation_id=evaluation.id,
        call_import_row_id=source_row.id,
        status="pending",
        metric_scores={},
    )
    db_session.add(eval_row)
    db_session.commit()

    return evaluation, eval_row, source_row, llm_metric, audio_metric


def test_task_route_audio_metrics_queue():
    routes = celery_app.conf.task_routes or {}
    assert routes["evaluate_call_import_row_audio"]["queue"] == "audio-metrics"


def test_dispatch_routes_audio_phase_to_audio_metrics_queue(
    db_session, monkeypatch
):
    evaluation, eval_row, source_row, _llm, _audio = _seed_audio_and_llm(
        db_session
    )
    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch.acquire_eval_slot",
        lambda **kwargs: True,
    )

    captured: dict = {}

    def _fake_apply_async(*args, **kwargs):
        captured["queue"] = kwargs.get("queue")
        captured["task"] = kwargs.get("task_id", "task-id")
        result = MagicMock()
        result.id = kwargs.get("task_id", "task-id")
        return result

    monkeypatch.setattr(
        "app.workers.tasks.evaluate_call_import_row_audio.evaluate_call_import_row_audio_task.apply_async",
        _fake_apply_async,
    )

    result = _try_dispatch_single_row(
        db=db_session,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
    )

    assert result == "dispatched"
    assert captured["queue"] == AUDIO_METRICS_QUEUE


def test_dispatch_routes_llm_only_to_evaluations_queue(db_session, monkeypatch):
    evaluation, eval_row, source_row, llm_metric, _audio = _seed_audio_and_llm(
        db_session
    )
    evaluation.selected_metric_ids = [str(llm_metric.id)]
    db_session.commit()

    monkeypatch.setattr(
        "app.workers.concurrency.eval_dispatch.acquire_eval_slot",
        lambda **kwargs: True,
    )

    captured: dict = {}

    def _fake_apply_async(*args, **kwargs):
        captured["queue"] = kwargs.get("queue")
        result = MagicMock()
        result.id = kwargs.get("task_id", "task-id")
        return result

    monkeypatch.setattr(
        "app.workers.tasks.evaluate_call_import_row.evaluate_call_import_row_task.apply_async",
        _fake_apply_async,
    )

    result = _try_dispatch_single_row(
        db=db_session,
        evaluation=evaluation,
        eval_row=eval_row,
        source_row=source_row,
    )

    assert result == "dispatched"
    assert captured["queue"] == EVALUATIONS_QUEUE
