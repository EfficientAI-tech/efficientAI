"""API tests for metric-cluster failure policies."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.metric_failure_policy import validate_failure_policies_for_metrics
from app.models.schemas import MetricFailurePolicy


def test_validate_failure_policies_rejects_unknown_metric_only():
    metric = MagicMock()
    metric.id = uuid.uuid4()
    metric.name = "Test metric"
    metric.selection_mode = None
    metric.parent_metric_id = None

    validate_failure_policies_for_metrics({}, [metric])

    validate_failure_policies_for_metrics(
        {str(metric.id): MetricFailurePolicy(metric_id=str(metric.id))},
        [metric],
    )

    with pytest.raises(ValueError, match="Unknown metric_id"):
        validate_failure_policies_for_metrics(
            {"not-a-real-metric": MetricFailurePolicy(metric_id="x")},
            [metric],
        )
