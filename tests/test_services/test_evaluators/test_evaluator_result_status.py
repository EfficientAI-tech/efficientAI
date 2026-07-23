"""Tests for evaluator result status repair helpers."""

from app.models.enums import EvaluatorResultStatus
from app.services.evaluators.evaluator_result_status import (
    effective_evaluator_result_status,
    has_meaningful_metric_scores,
    repair_evaluator_result_status_if_needed,
)


class _ResultStub:
    def __init__(self, *, status: str, metric_scores=None, error_message=None):
        self.status = status
        self.metric_scores = metric_scores
        self.error_message = error_message


def test_has_meaningful_metric_scores():
    assert has_meaningful_metric_scores({"m1": {"value": 1}}) is True
    assert has_meaningful_metric_scores({}) is False
    assert has_meaningful_metric_scores(None) is False


def test_effective_status_promotes_scored_in_flight_rows():
    row = _ResultStub(
        status=EvaluatorResultStatus.QUEUED.value,
        metric_scores={"abc": {"value": True, "type": "boolean"}},
    )
    assert effective_evaluator_result_status(row) == EvaluatorResultStatus.COMPLETED.value


def test_repair_persists_completed(db_session, seed_org, default_workspace):
    from app.models.database import EvaluatorResult

    row = EvaluatorResult(
        result_id="555001",
        organization_id=seed_org.id,
        workspace_id=default_workspace.id,
        name="Test",
        status=EvaluatorResultStatus.QUEUED.value,
        metric_scores={"m": {"value": 5, "type": "number", "metric_name": "Score"}},
    )
    db_session.add(row)
    db_session.commit()

    assert repair_evaluator_result_status_if_needed(db_session, row) is True
    db_session.refresh(row)
    assert row.status == EvaluatorResultStatus.COMPLETED.value
