import pytest

from app.models.enums import MetricType
from app.models.schemas import MetricCreate, MetricUpdate
from app.services.metric_classification_validation import (
    assert_classification_metric_shape,
    validate_classification_custom_config,
)


def _valid_config():
    return {
        "noul": {
            "enabled": True,
            "instructions": "Was it resolved?",
            "criteria": {"true": "Resolved", "false": "Not resolved"},
        },
        "choice": {"enabled": False},
        "score": {"enabled": False},
    }


def test_validate_classification_custom_config_accepts_valid_noul():
    normalized = validate_classification_custom_config(_valid_config())
    assert normalized["noul"]["enabled"] is True
    assert normalized["noul"]["criteria"]["true"] == "Resolved"


def test_validate_classification_rejects_no_enabled_questions():
    with pytest.raises(ValueError, match="at least one"):
        validate_classification_custom_config(
            {"noul": {"enabled": False}, "choice": {"enabled": False}, "score": {"enabled": False}}
        )


def test_validate_classification_rejects_incomplete_noul():
    cfg = _valid_config()
    cfg["noul"]["criteria"] = {"true": "only true"}
    with pytest.raises(ValueError, match="false"):
        validate_classification_custom_config(cfg)


def test_metric_create_accepts_classification():
    body = MetricCreate(
        name="Outcome",
        metric_type=MetricType.TEXT,
        custom_data_type="classification",
        custom_config=_valid_config(),
    )
    assert body.custom_data_type == "classification"
    assert body.metric_type == MetricType.TEXT


def test_metric_create_rejects_compare_transcripts_on_classification():
    with pytest.raises(ValueError, match="compare_transcripts"):
        MetricCreate(
            name="Outcome",
            metric_type=MetricType.TEXT,
            custom_data_type="classification",
            custom_config=_valid_config(),
            compare_transcripts=True,
        )


def test_assert_classification_metric_shape_rejects_parent():
    with pytest.raises(ValueError, match="standalone"):
        assert_classification_metric_shape(
            custom_data_type="classification",
            custom_config=_valid_config(),
            parent_metric_id="00000000-0000-0000-0000-000000000001",
        )


def test_metric_update_classification_requires_config():
    with pytest.raises(ValueError, match="custom_config"):
        MetricUpdate(custom_data_type="classification")
