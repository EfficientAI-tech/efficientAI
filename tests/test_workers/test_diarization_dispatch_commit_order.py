"""Standalone diarisation dispatch must commit task ownership before queue."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@patch("app.workers.concurrency.diarization_dispatch.acquire_eval_slot", return_value=True)
@patch("app.workers.tasks.transcribe_call_import_row.transcribe_call_import_row_task")
def test_standalone_diarisation_commits_task_id_before_apply_async(
    mock_task, _mock_slot, monkeypatch
):
    from app.workers.concurrency.diarization_dispatch import (
        _try_dispatch_single_diarization_row,
    )

    order: list[str] = []
    row_id = uuid4()
    row = MagicMock()
    row.id = row_id
    row.diarised_transcript_status = "pending"
    row.celery_task_id = None

    db = MagicMock()

    def _commit():
        order.append("commit")

    db.commit.side_effect = _commit
    mock_task.apply_async.side_effect = lambda **_kwargs: (
        order.append("queue") or MagicMock(id="reserved-id")
    )

    monkeypatch.setattr(
        "app.workers.concurrency.diarization_dispatch.celery_uuid",
        lambda: "reserved-id",
    )

    result = _try_dispatch_single_diarization_row(
        db=db,
        row=row,
        call_import=MagicMock(
            workspace_id=uuid4(),
            organization_id=uuid4(),
        ),
        params={"mode": "stt_llm"},
    )

    assert result == "dispatched"
    assert order[0] == "commit"
    assert "queue" in order
    assert row.celery_task_id == "reserved-id"
