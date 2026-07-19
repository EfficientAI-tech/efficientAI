"""Tests for Celery queue routing (Option B: imports + diarization + evaluations)."""

from types import SimpleNamespace
from uuid import uuid4

from app.workers.config import celery_app
from app.workers.concurrency import DIARIZATION_QUEUE, EVALUATIONS_QUEUE, IMPORTS_QUEUE


def test_process_call_import_row_routes_to_imports_queue():
    routes = celery_app.conf.task_routes
    assert routes["process_call_import_row"]["queue"] == "imports"


def test_evaluate_call_import_row_routes_to_evaluations_queue():
    routes = celery_app.conf.task_routes
    assert routes["evaluate_call_import_row"]["queue"] == "evaluations"


def test_dispatch_evaluation_rows_routes_to_evaluations_queue():
    routes = celery_app.conf.task_routes
    assert routes["dispatch_evaluation_rows"]["queue"] == "evaluations"


def test_dispatch_fair_eval_rows_routes_to_evaluations_queue():
    routes = celery_app.conf.task_routes
    assert routes["dispatch_fair_eval_rows"]["queue"] == "evaluations"


def test_manual_transcribe_default_route_routes_to_diarization_queue():
    routes = celery_app.conf.task_routes
    assert routes["transcribe_call_import_row"]["queue"] == "diarization"


def test_diarization_queue_constant_distinct_from_imports():
    assert DIARIZATION_QUEUE == "diarization"
    assert DIARIZATION_QUEUE != IMPORTS_QUEUE


def test_manual_transcribe_bulk_enqueue_uses_diarization_queue(monkeypatch):
    """Bulk manual diarise must enqueue to diarization, not imports."""
    import sys
    import types

    captured_queues = []

    class _Task:
        @staticmethod
        def apply_async(*_args, **kwargs):
            captured_queues.append(kwargs.get("queue"))
            return SimpleNamespace(id="fake-task-id")

    fake_mod = types.ModuleType("app.workers.tasks.transcribe_call_import_row")
    fake_mod.transcribe_call_import_row_task = _Task()
    monkeypatch.setitem(
        sys.modules, "app.workers.tasks.transcribe_call_import_row", fake_mod
    )

    from app.workers.tasks.transcribe_call_import_row import (
        transcribe_call_import_row_task,
    )

    for row_id in (uuid4(), uuid4()):
        transcribe_call_import_row_task.apply_async(
            args=(str(row_id),),
            queue=DIARIZATION_QUEUE,
        )

    assert captured_queues == [DIARIZATION_QUEUE, DIARIZATION_QUEUE]
    assert EVALUATIONS_QUEUE == "evaluations"
