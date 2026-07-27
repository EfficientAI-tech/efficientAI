"""Smoke test for metric rubric text length validation."""

from pydantic import ValidationError

from app.models.schemas import (
    METRIC_RUBRIC_TEXT_MAX_LENGTH,
    MetricChildDraft,
    MetricCreateWithChildren,
)


def test_metric_rubric_accepts_text_over_legacy_4000_limit():
    long_text = "x" * 5000
    payload = MetricCreateWithChildren(
        name="Test",
        description=long_text,
        selection_mode="single_choice",
        children=[
            MetricChildDraft(name="Label1", description="def", example=long_text)
        ],
    )
    assert len(payload.description) == 5000
    assert len(payload.children[0].example) == 5000


def test_metric_rubric_rejects_text_over_max_length():
    try:
        MetricCreateWithChildren(
            name="Test",
            description="x" * (METRIC_RUBRIC_TEXT_MAX_LENGTH + 1),
            selection_mode="single_choice",
        )
    except ValidationError:
        return
    raise AssertionError("expected ValidationError for over-limit description")
