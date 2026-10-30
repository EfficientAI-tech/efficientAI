"""Unit tests for Jev bundle config validation (no HTTP/DB)."""

import pytest
from fastapi import HTTPException

from app.api.v1.routes.metrics import _validate_jev_config
from app.models.enums import MetricType


def test_validate_jev_bundle_accepts_subset():
    metric_type, config, tags = _validate_jev_config(
        custom_config={
            "state_source": "both",
            "questions": {
                "noul": {"criteria": {"true": "Frustrated", "false": "Calm"}},
                "score": {
                    "criteria": ["Calm", "Frustrated", "Very angry"],
                    "confidence_threshold": 0.7,
                },
            },
        },
        parent_metric_id=None,
        selection_mode=None,
    )
    assert metric_type == MetricType.NUMBER
    assert "noul" in config["questions"]
    assert "score" in config["questions"]
    assert "choice" not in config["questions"]
    assert "jev" in tags


def test_validate_jev_bundle_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        _validate_jev_config(
            custom_config={"state_source": "both", "questions": {}},
            parent_metric_id=None,
            selection_mode=None,
        )
    assert "questions" in str(exc.value.detail).lower()


def test_validate_legacy_jev_type_writes_questions_map():
    _metric_type, config, _tags = _validate_jev_config(
        custom_config={
            "jev_type": "noul",
            "state_source": "both",
            "criteria": {"true": "Yes", "false": "No"},
        },
        parent_metric_id=None,
        selection_mode=None,
    )
    assert config["jev_type"] == "noul"
    assert "noul" in config["questions"]
