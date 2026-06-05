"""Tests for per-evaluation metric failure policies."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.schemas import MetricFailurePolicy
from app.services.metric_failure_policy import (
    is_metric_failure,
    normalize_label,
    prune_policy_to_observed_rows,
    score_matches_failure_policy,
    suggest_failure_policy,
)


def _metric(
    *,
    name: str = "Primary Language detection",
    selection_mode: str | None = None,
    parent_metric_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        selection_mode=selection_mode,
        parent_metric_id=parent_metric_id,
        metric_type="boolean",
    )


def test_normalize_label_yes_no():
    assert normalize_label("Yes") == "yes"
    assert normalize_label(False) == "false"


def test_suggest_failure_policy_prefers_no_over_yes():
    metric = _metric()
    policy = suggest_failure_policy(metric, observed_labels=["Yes", "No"])
    assert policy.failure_values == ["no"]


def test_prune_policy_when_no_rows_match_failure_label():
    metric = _metric()
    raw = suggest_failure_policy(metric, observed_labels=["Yes", "No"])
    pruned = prune_policy_to_observed_rows(
        raw, metric, {"Yes": 50}
    )
    assert pruned.failure_values == []


def test_yes_not_failure_when_policy_says_no():
    metric = _metric(selection_mode="single_choice")
    policy = MetricFailurePolicy(metric_id=str(metric.id), failure_values=["no"])
    scores = {
        str(metric.id): {
            "chosen_child_name": "Yes",
            "value": "Yes",
            "type": "category",
            "selection_mode": "single_choice",
        }
    }
    assert score_matches_failure_policy(scores, metric, policy) is False

    scores[str(metric.id)] = {
        "chosen_child_name": "No",
        "value": "No",
        "type": "category",
        "selection_mode": "single_choice",
    }
    assert score_matches_failure_policy(scores, metric, policy) is True


def test_multilabel_only_failure_children():
    parent = _metric(selection_mode="multi_label")
    policy = MetricFailurePolicy(
        metric_id=str(parent.id),
        failure_child_names=["Wrong transfer"],
    )
    scores = {
        str(parent.id): {
            "selected_child_names": ["Happy path", "Wrong transfer"],
            "type": "category",
            "selection_mode": "multi_label",
        }
    }
    assert score_matches_failure_policy(scores, parent, policy) is True

    scores[str(parent.id)]["selected_child_names"] = ["Happy path"]
    assert score_matches_failure_policy(scores, parent, policy) is False


def test_numeric_lt_half():
    metric = _metric(name="Quality score")
    policy = MetricFailurePolicy(
        metric_id=str(metric.id),
        numeric_rule={"op": "lt", "threshold": 0.5},
    )
    row = SimpleNamespace(
        status="completed",
        metric_scores={str(metric.id): {"value": 0.3, "type": "rating"}},
    )
    assert is_metric_failure(row, metric, policy) is True

    row.metric_scores[str(metric.id)]["value"] = 0.8
    assert is_metric_failure(row, metric, policy) is False
