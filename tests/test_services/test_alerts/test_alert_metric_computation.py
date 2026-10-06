"""Integration-style tests for alert metric computation from evaluator results."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.database import EvaluatorResult
from app.models.enums import EvaluatorResultStatus
from app.services.alerts.alert_evaluation_service import AlertEvaluationService


def test_compute_number_of_calls_from_evaluator_results(db_session, org_id, default_workspace):
    service = AlertEvaluationService()
    now = datetime.now(timezone.utc)
    alert = type(
        "Alert",
        (),
        {
            "metric_type": "number_of_calls",
            "aggregation": "sum",
            "time_window_minutes": 120,
            "organization_id": org_id,
            "agent_ids": None,
            "data_source": "evaluations",
        },
    )()

    for _ in range(3):
        db_session.add(
            EvaluatorResult(
                id=uuid4(),
                result_id=f"{uuid4().hex[:6]}",
                organization_id=org_id,
                workspace_id=default_workspace.id,
                status=EvaluatorResultStatus.COMPLETED.value,
                timestamp=now - timedelta(minutes=10),
            )
        )
    db_session.commit()

    value = service._compute_metric(alert, db_session)
    assert value == 3.0


def test_compute_error_rate_from_evaluator_results(db_session, org_id, default_workspace):
    service = AlertEvaluationService()
    now = datetime.now(timezone.utc)
    alert = type(
        "Alert",
        (),
        {
            "metric_type": "error_rate",
            "aggregation": "avg",
            "time_window_minutes": 120,
            "organization_id": org_id,
            "agent_ids": None,
            "data_source": "evaluations",
        },
    )()

    db_session.add(
        EvaluatorResult(
            id=uuid4(),
            result_id=f"{uuid4().hex[:6]}",
            organization_id=org_id,
            workspace_id=default_workspace.id,
            status=EvaluatorResultStatus.FAILED.value,
            timestamp=now - timedelta(minutes=5),
        )
    )
    db_session.add(
        EvaluatorResult(
            id=uuid4(),
            result_id=f"{uuid4().hex[:6]}",
            organization_id=org_id,
            workspace_id=default_workspace.id,
            status=EvaluatorResultStatus.COMPLETED.value,
            timestamp=now - timedelta(minutes=5),
        )
    )
    db_session.commit()

    value = service._compute_metric(alert, db_session)
    assert value == 50.0
