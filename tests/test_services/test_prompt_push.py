"""Compose and review helpers for live prompt pushes."""

import pytest

from app.services.call_import_prompt_push import (
    PromptPushError,
    compose_accepted_prompt,
    normalize_prompt,
    review_counts,
)


def test_compose_applies_only_accepted_edits_and_additions():
    base = "Hello world.\nKeep this."
    suggestions = [
        {
            "review_status": "accepted",
            "change_type": "edit",
            "anchor_excerpt": "Hello world.",
            "suggested_text": "Hello there.",
        },
        {
            "review_status": "rejected",
            "change_type": "edit",
            "anchor_excerpt": "Keep this.",
            "suggested_text": "Drop this.",
        },
        {
            "review_status": "accepted",
            "change_type": "add",
            "suggested_text": "Ask for the order id.",
            "edited_text": "Ask for the account id.",
        },
        {
            "review_status": "pending",
            "change_type": "add",
            "suggested_text": "Do not apply.",
        },
    ]
    composed = compose_accepted_prompt(base, suggestions)
    assert composed.startswith("Hello there.\nKeep this.")
    assert "Ask for the account id." in composed
    assert "Drop this." not in composed
    assert "Do not apply." not in composed


def test_compose_applies_non_overlapping_edits_without_appending():
    composed = compose_accepted_prompt(
        "Alpha. Beta.",
        [
            {
                "review_status": "accepted",
                "change_type": "edit",
                "anchor_excerpt": "Alpha.",
                "suggested_text": "One.",
            },
            {
                "review_status": "accepted",
                "change_type": "edit",
                "anchor_excerpt": "Beta.",
                "suggested_text": "Two.",
            },
        ],
    )
    assert composed == "One. Two."


def test_compose_rejects_overlapping_edits():
    with pytest.raises(PromptPushError, match="overlap"):
        compose_accepted_prompt(
            "Keep the greeting. Keep the closing.",
            [
                {
                    "review_status": "accepted",
                    "change_type": "edit",
                    "anchor_excerpt": "Keep the greeting.",
                    "suggested_text": "Hello.",
                },
                {
                    "review_status": "accepted",
                    "change_type": "edit",
                    "anchor_excerpt": "greeting. Keep",
                    "suggested_text": "overlap",
                },
            ],
        )


def test_compose_rejects_edit_whose_anchor_is_missing():
    with pytest.raises(PromptPushError, match="no longer matches"):
        compose_accepted_prompt(
            "Hello.",
            [
                {
                    "review_status": "accepted",
                    "change_type": "edit",
                    "anchor_excerpt": "Goodbye.",
                    "suggested_text": "See you.",
                },
            ],
        )


def test_normalize_prompt_ignores_trailing_space():
    assert normalize_prompt("Line  \r\nNext\n") == normalize_prompt("Line\nNext")


def test_review_counts_treat_missing_status_as_pending():
    accepted, rejected, pending, applied = review_counts(
        [
            {"review_status": "accepted"},
            {"review_status": "rejected"},
            {},
        ]
    )
    assert (accepted, rejected, pending, applied) == (1, 1, 1, 0)
