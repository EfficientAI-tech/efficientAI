"""Unit tests for evaluator-result metric cluster adapters."""

from __future__ import annotations

from uuid import uuid4

from app.models.database import EvaluatorResult, Metric
from app.models.enums import EvaluatorResultStatus
from app.services.call_import_metric_clusters import _build_flagged_row_payload_from_source
from app.services.metric_cluster_rows import evaluator_result_to_cluster_row
from app.models.schemas import MetricFailurePolicy


def test_evaluator_result_to_cluster_row_payload():
    metric_id = uuid4()
    metric = Metric(
        id=metric_id,
        organization_id=uuid4(),
        workspace_id=uuid4(),
        name="Pass/Fail",
        metric_type="boolean",
        enabled=True,
    )
    result = EvaluatorResult(
        id=uuid4(),
        result_id="661122",
        organization_id=uuid4(),
        workspace_id=uuid4(),
        status=EvaluatorResultStatus.COMPLETED.value,
        transcription="User: hello\nBot: hi",
        metric_scores={
            str(metric_id): {
                "value": False,
                "type": "boolean",
                "metric_name": "Pass/Fail",
                "rationale": "Bot failed to confirm identity.",
            }
        },
    )
    source = evaluator_result_to_cluster_row(result)
    policy = MetricFailurePolicy(metric_id=str(metric_id), failure_values=["false"])
    payload = _build_flagged_row_payload_from_source(source, metric, policy)
    assert payload is not None
    assert payload["conversation_id"] == "661122"
    assert payload["rationale"] == "Bot failed to confirm identity."
    assert "hello" in payload["transcript"]
