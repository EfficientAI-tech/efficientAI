"""Tests for nested evaluation fair dispatch within a workspace."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.concurrency import fair_dispatch as fair_dispatch_module
from app.workers.concurrency.eval_dispatch import EvalDispatchOutcome


@pytest.fixture(autouse=True)
def _reset_eval_workspace_cursor(monkeypatch):
    cursors: dict[str, int] = {}

    def _get(workspace_id):
        return cursors.get(str(workspace_id), 0)

    def _set(workspace_id, cursor):
        cursors[str(workspace_id)] = cursor

    monkeypatch.setattr(
        fair_dispatch_module,
        "_get_workspace_eval_rr_cursor",
        _get,
    )
    monkeypatch.setattr(
        fair_dispatch_module,
        "_set_workspace_eval_rr_cursor",
        lambda workspace_id, cursor: _set(workspace_id, cursor),
    )


def test_dispatch_batch_interleaves_evaluations_in_same_workspace():
    workspace_id = uuid4()
    eval_a = uuid4()
    eval_b = uuid4()
    call_import_id = uuid4()

    row_a1 = SimpleNamespace(id=uuid4(), status="pending", celery_task_id=None)
    row_b1 = SimpleNamespace(id=uuid4(), status="pending", celery_task_id=None)
    row_a2 = SimpleNamespace(id=uuid4(), status="pending", celery_task_id=None)
    row_b2 = SimpleNamespace(id=uuid4(), status="pending", celery_task_id=None)

    source_a1 = SimpleNamespace(id=uuid4())
    source_b1 = SimpleNamespace(id=uuid4())
    source_a2 = SimpleNamespace(id=uuid4())
    source_b2 = SimpleNamespace(id=uuid4())

    evaluation_a = SimpleNamespace(
        id=eval_a, status="running", call_import_id=call_import_id
    )
    evaluation_b = SimpleNamespace(
        id=eval_b, status="running", call_import_id=call_import_id
    )

    pending_by_eval = {
        eval_a: [
            (row_a1, source_a1, evaluation_a),
            (row_a2, source_a2, evaluation_a),
        ],
        eval_b: [
            (row_b1, source_b1, evaluation_b),
            (row_b2, source_b2, evaluation_b),
        ],
    }
    dispatch_order: list[uuid4] = []

    def _pending_rows_for_evaluation(
        _db, evaluation_id, *, limit, shard_cache=None
    ):
        rows = pending_by_eval.get(evaluation_id, [])
        return rows[:limit]

    def _try_dispatch_single_row(**kwargs):
        evaluation = kwargs["evaluation"]
        eval_row = kwargs["eval_row"]
        dispatch_order.append(evaluation.id)
        pending_by_eval[evaluation.id] = [
            item
            for item in pending_by_eval[evaluation.id]
            if item[0].id != eval_row.id
        ]
        return EvalDispatchOutcome("dispatched")

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=call_import_id,
        organization_id=uuid4(),
        workspace_id=workspace_id,
        provider=None,
        telephony_integration_id=None,
    )
    with patch.object(
        fair_dispatch_module,
        "_evaluations_with_pending_rows",
        return_value=[eval_a, eval_b],
    ), patch.object(
        fair_dispatch_module,
        "_pending_rows_for_evaluation",
        side_effect=_pending_rows_for_evaluation,
    ), patch.object(
        fair_dispatch_module,
        "_try_dispatch_single_row",
        side_effect=_try_dispatch_single_row,
    ), patch.object(
        fair_dispatch_module,
        "get_row_restricted_metrics",
        return_value=None,
    ), patch.object(
        fair_dispatch_module,
        "evaluation_transcribe_overwrite",
        return_value=False,
    ), patch.object(
        fair_dispatch_module,
        "clear_row_restricted_metrics",
    ):
        dispatched, hit_capacity, _backoff = (
            fair_dispatch_module._dispatch_batch_for_workspace(
                db,
                workspace_id,
                batch_size=4,
            )
        )

    assert dispatched == 4
    assert hit_capacity is False
    assert dispatch_order == [eval_a, eval_b, eval_a, eval_b]


def test_dispatch_batch_job2_gets_rows_while_job1_has_backlog():
    workspace_id = uuid4()
    eval_job1 = uuid4()
    eval_job2 = uuid4()
    call_import_id = uuid4()

    row_job1 = SimpleNamespace(id=uuid4(), status="pending", celery_task_id=None)
    row_job2 = SimpleNamespace(id=uuid4(), status="pending", celery_task_id=None)
    source_job1 = SimpleNamespace(id=uuid4())
    source_job2 = SimpleNamespace(id=uuid4())
    evaluation_job1 = SimpleNamespace(
        id=eval_job1, status="running", call_import_id=call_import_id
    )
    evaluation_job2 = SimpleNamespace(
        id=eval_job2, status="pending", call_import_id=call_import_id
    )

    pending_by_eval = {
        eval_job1: [(row_job1, source_job1, evaluation_job1)] * 5,
        eval_job2: [(row_job2, source_job2, evaluation_job2)],
    }
    dispatched_evaluations: list[uuid4] = []

    def _pending_rows_for_evaluation(
        _db, evaluation_id, *, limit, shard_cache=None
    ):
        rows = pending_by_eval.get(evaluation_id, [])
        return rows[:limit]

    def _try_dispatch_single_row(**kwargs):
        evaluation = kwargs["evaluation"]
        dispatched_evaluations.append(evaluation.id)
        pending_by_eval[evaluation.id] = pending_by_eval[evaluation.id][1:]
        return EvalDispatchOutcome("dispatched")

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=call_import_id,
        organization_id=uuid4(),
        workspace_id=workspace_id,
        provider=None,
        telephony_integration_id=None,
    )
    with patch.object(
        fair_dispatch_module,
        "_evaluations_with_pending_rows",
        return_value=[eval_job1, eval_job2],
    ), patch.object(
        fair_dispatch_module,
        "_pending_rows_for_evaluation",
        side_effect=_pending_rows_for_evaluation,
    ), patch.object(
        fair_dispatch_module,
        "_try_dispatch_single_row",
        side_effect=_try_dispatch_single_row,
    ), patch.object(
        fair_dispatch_module,
        "get_row_restricted_metrics",
        return_value=None,
    ), patch.object(
        fair_dispatch_module,
        "evaluation_transcribe_overwrite",
        return_value=False,
    ), patch.object(
        fair_dispatch_module,
        "clear_row_restricted_metrics",
    ):
        dispatched, hit_capacity, _backoff = (
            fair_dispatch_module._dispatch_batch_for_workspace(
                db,
                workspace_id,
                batch_size=2,
            )
        )

    assert dispatched == 2
    assert hit_capacity is False
    assert eval_job2 in dispatched_evaluations
    assert dispatched_evaluations[0] == eval_job1
    assert dispatched_evaluations[1] == eval_job2
