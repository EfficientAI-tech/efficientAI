from app.services.metrics.option_labels import (
    classification_score_labels_from_config,
    enum_option_labels_from_config,
)


def test_enum_option_labels_from_object_options():
    cfg = {"options": [{"value": "a", "description": "Alpha"}, "b"]}
    assert enum_option_labels_from_config(cfg) == ["a", "b"]


def test_classification_score_labels_from_object_criteria():
    cfg = {"score": {"criteria": [{"value": "high", "description": "Great"}, "low"]}}
    assert classification_score_labels_from_config(cfg) == ["high", "low"]
