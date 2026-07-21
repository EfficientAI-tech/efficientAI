"""Tests for evaluation serialize progress counter merge."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.api.v1.routes.call_import_evaluations import _serialize_eval


def test_serialize_eval_merges_redis_deltas_without_clearing(db_session, org_id, seed_org):
    now = datetime.now(timezone.utc)
    evaluation = type(
        "EvalStub",
        (),
        {
            "id": uuid4(),
            "call_import_id": uuid4(),
            "organization_id": org_id,
            "name": "run",
            "selected_metric_ids": [],
            "selected_metric_groups": None,
            "status": "running",
            "total_rows": 10,
            "completed_rows": 3,
            "failed_rows": 1,
            "error_message": None,
            "llm_provider": None,
            "llm_model": None,
            "llm_credential_id": None,
            "llm_config": None,
            "metric_llm_overrides": None,
            "stt_provider": None,
            "stt_model": None,
            "stt_credential_id": None,
            "transcript_source": "diarised",
            "tldr_summary": None,
            "started_at": None,
            "finished_at": None,
            "created_at": now,
            "updated_at": now,
        },
    )()

    with patch(
        "app.services.call_imports.progress_counters.merge_eval_counters_for_ui",
        return_value=(5, 2),
    ) as mock_merge, patch(
        "app.services.call_imports.progress_counters.clear_eval_progress_redis",
    ) as mock_clear, patch(
        "app.api.v1.routes.call_import_evaluations._metrics_for_ids",
        return_value=[],
    ):
        response = _serialize_eval(db_session, evaluation)

    mock_merge.assert_called_once_with(evaluation)
    mock_clear.assert_not_called()
    assert response.completed_rows == 5
    assert response.failed_rows == 2
