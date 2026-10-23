"""Per-metric success criteria for simulation runs."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.schemas import MetricSuccessCriterion
from app.services.harbor.success_criteria import (
    _validate_rule_shape,
    apply_success_criteria,
    criterion_passes,
    infer_criterion_kind,
    validate_metric_success_criteria,
)


def _metric(**kwargs):
    defaults = {
        "id": uuid4(),
        "name": "M",
        "metric_type": "boolean",
        "custom_data_type": None,
        "custom_config": None,
        "selection_mode": None,
        "parent_metric_id": None,
        "organization_id": uuid4(),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_infer_boolean_and_classification_kind():
    assert infer_criterion_kind(_metric(metric_type="boolean")) == "boolean"
    assert (
        infer_criterion_kind(
            _metric(metric_type="text", custom_data_type="classification", custom_config={"noul": {"enabled": True}})
        )
        == "classification"
    )


def test_boolean_no_is_success():
    m = _metric(metric_type="boolean", name="Hallucinated")
    crit = {"metric_id": str(m.id), "kind": "boolean", "success_when": "no"}
    scores = {str(m.id): {"value": True, "type": "boolean"}}
    assert not criterion_passes(crit, metric_scores=scores, metric=m, children_by_parent={})
    scores[str(m.id)]["value"] = False
    assert criterion_passes(crit, metric_scores=scores, metric=m, children_by_parent={})


def test_rating_threshold():
    m = _metric(metric_type="rating", name="Quality")
    crit = {"metric_id": str(m.id), "kind": "rating", "op": "gte", "threshold": 0.7}
    scores = {str(m.id): {"value": 0.65, "type": "rating"}}
    assert not criterion_passes(crit, metric_scores=scores, metric=m, children_by_parent={})
    scores[str(m.id)]["value"] = 0.75
    assert criterion_passes(crit, metric_scores=scores, metric=m, children_by_parent={})


def test_category_single_and_multi():
    parent_id = uuid4()
    child_a = uuid4()
    child_b = uuid4()
    parent = _metric(
        id=parent_id,
        name="Outcome",
        metric_type="text",
        selection_mode="single_choice",
    )
    crit_single = {
        "metric_id": str(parent_id),
        "kind": "category_single",
        "success_values": ["Happy"],
    }
    scores = {
        str(parent_id): {
            "type": "category",
            "chosen_child_name": "Happy",
            "value": "Happy",
        }
    }
    assert criterion_passes(
        crit_single, metric_scores=scores, metric=parent, children_by_parent={}
    )

    parent_ml = _metric(
        id=parent_id,
        name="Tags",
        metric_type="text",
        selection_mode="multi_label",
    )
    crit_multi = {
        "metric_id": str(parent_id),
        "kind": "category_multi",
        "label_rules": [{"child_id": str(child_a), "expect": "yes"}],
    }
    scores_ml = {
        str(child_a): {"value": True, "type": "boolean"},
        str(child_b): {"value": True, "type": "boolean"},
    }
    assert criterion_passes(
        crit_multi, metric_scores=scores_ml, metric=parent_ml, children_by_parent={}
    )
    scores_ml[str(child_a)]["value"] = False
    assert not criterion_passes(
        crit_multi, metric_scores=scores_ml, metric=parent_ml, children_by_parent={}
    )


def test_apply_all_must_pass_and_reward_fraction():
    m1 = _metric(metric_type="boolean", name="A")
    m2 = _metric(metric_type="boolean", name="B")
    criteria = [
        {"metric_id": str(m1.id), "kind": "boolean", "success_when": "yes"},
        {"metric_id": str(m2.id), "kind": "boolean", "success_when": "yes"},
    ]
    scores = {
        str(m1.id): {"value": True, "type": "boolean"},
        str(m2.id): {"value": False, "type": "boolean"},
    }
    passed, reward, updated = apply_success_criteria(
        scores,
        criteria,
        {str(m1.id): m1, str(m2.id): m2},
        {},
    )
    assert not passed
    assert reward == 0.5
    assert updated[str(m1.id)]["passed"] is True
    assert updated[str(m2.id)]["passed"] is False

    scores[str(m2.id)]["value"] = True
    passed, reward, _ = apply_success_criteria(
        scores,
        criteria,
        {str(m1.id): m1, str(m2.id): m2},
        {},
    )
    assert passed
    assert reward == 1.0


def test_text_metric_does_not_gate():
    m = _metric(metric_type="text", name="Notes")
    criteria = [{"metric_id": str(m.id), "kind": "text"}]
    passed, reward, _ = apply_success_criteria(
        {str(m.id): {"value": "hello", "type": "text"}},
        criteria,
        {str(m.id): m},
        {},
    )
    assert not passed
    assert reward is None


def test_validate_enum_accepts_success_values_matching_object_options():
    m = _metric(
        name="Outcome enum",
        metric_type="text",
        custom_data_type="enum",
        custom_config={
            "options": [{"value": "professional", "description": "Clean close"}, "abrupt"],
        },
    )
    rule = MetricSuccessCriterion(
        metric_id=m.id,
        kind="enum",
        success_values=["professional"],
    )
    _validate_rule_shape(rule, m, [])


def test_validate_enum_distinct_zero_padded_labels():
    m = _metric(
        name="Codes",
        metric_type="text",
        custom_data_type="enum",
        custom_config={"options": ["01", "1"]},
    )
    _validate_rule_shape(
        MetricSuccessCriterion(metric_id=m.id, kind="enum", success_values=["1"]),
        m,
        [],
    )
    _validate_rule_shape(
        MetricSuccessCriterion(metric_id=m.id, kind="enum", success_values=["01"]),
        m,
        [],
    )
    with pytest.raises(ValueError, match="unknown"):
        _validate_rule_shape(
            MetricSuccessCriterion(metric_id=m.id, kind="enum", success_values=["1.0"]),
            m,
            [],
        )


def test_validate_enum_accepts_numeric_option_labels_as_strings():
    m = _metric(
        name="Rating bucket",
        metric_type="text",
        custom_data_type="enum",
        custom_config={"options": [1, 2, 3]},
    )
    rule = MetricSuccessCriterion(
        metric_id=m.id,
        kind="enum",
        success_values=["2"],
    )
    _validate_rule_shape(rule, m, [])


def test_validate_rejects_text_only(db_session, seed_org, default_workspace):
    org_id = seed_org.id
    from app.models.database import Metric

    text_m = Metric(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Comment",
        metric_type="text",
    )
    db_session.add(text_m)
    db_session.commit()
    with pytest.raises(ValueError, match="non-text metric"):
        validate_metric_success_criteria(
            db_session,
            organization_id=org_id,
            metric_ids=[text_m.id],
            criteria=[
                MetricSuccessCriterion(metric_id=text_m.id, kind="text"),
            ],
        )
