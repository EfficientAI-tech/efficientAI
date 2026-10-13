"""Compose and review helpers for live prompt pushes."""

from app.services.call_import_prompt_push import (
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
