"""Smoke test for metric rubric text length validation."""

from pydantic import ValidationError

from app.models.schemas import (
    METRIC_RUBRIC_TEXT_MAX_LENGTH,
    MetricChildDraft,
    MetricCreate,
    MetricCreateWithChildren,
    MetricUpdate,
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


def test_metric_rubric_accepts_text_at_max_length():
    max_text = "x" * METRIC_RUBRIC_TEXT_MAX_LENGTH

    create_payload = MetricCreate(
        name="Standalone",
        description=max_text,
        example=max_text,
    )
    assert len(create_payload.description) == METRIC_RUBRIC_TEXT_MAX_LENGTH
    assert len(create_payload.example) == METRIC_RUBRIC_TEXT_MAX_LENGTH

    with_children_payload = MetricCreateWithChildren(
        name="Parent",
        description=max_text,
        selection_mode="single_choice",
        children=[
            MetricChildDraft(name="Label1", description=max_text, example=max_text)
        ],
    )
    assert len(with_children_payload.description) == METRIC_RUBRIC_TEXT_MAX_LENGTH
    assert len(with_children_payload.children[0].description) == METRIC_RUBRIC_TEXT_MAX_LENGTH
    assert len(with_children_payload.children[0].example) == METRIC_RUBRIC_TEXT_MAX_LENGTH

    update_payload = MetricUpdate(description=max_text, example=max_text)
    assert len(update_payload.description) == METRIC_RUBRIC_TEXT_MAX_LENGTH
    assert len(update_payload.example) == METRIC_RUBRIC_TEXT_MAX_LENGTH


def test_metric_rubric_rejects_text_over_max_length():
    over_limit = "x" * (METRIC_RUBRIC_TEXT_MAX_LENGTH + 1)

    for factory, kwargs in (
        (MetricCreate, {"name": "Standalone", "description": over_limit}),
        (MetricCreate, {"name": "Standalone", "example": over_limit}),
        (
            MetricCreateWithChildren,
            {"name": "Test", "description": over_limit, "selection_mode": "single_choice"},
        ),
        (MetricUpdate, {"description": over_limit}),
        (MetricUpdate, {"example": over_limit}),
    ):
        try:
            factory(**kwargs)
        except ValidationError:
            continue
        raise AssertionError(f"expected ValidationError for over-limit {factory.__name__}")
