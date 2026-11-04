"""Tests for diarized-reference transcript WER/CER helpers."""

from app.services.evaluation.transcript_error_rates import (
    compute_user_error_rates,
    extract_user_text_from_diarised,
    extract_user_text_from_production,
    normalize_for_wer,
    parse_labeled_transcript,
)


def test_production_parsing_user_turns_and_continuation():
    text = (
        "Agent: hello there\n"
        "User: I need help\n"
        "with my account\n"
        "Agent: sure\n"
        "Customer: thanks"
    )
    parsed = parse_labeled_transcript(text)
    assert parsed.unlabelled is False
    assert "I need help with my account thanks" in parsed.user_text
    assert parsed.user_turn_count >= 2


def test_production_unlabelled():
    parsed = extract_user_text_from_production("just some lines\nno speakers")
    assert parsed.unlabelled is True


def test_diarised_user_extraction_with_swap():
    segments = [
        {"speaker": "agent", "text": "hi"},
        {"speaker": "user", "text": "hello world"},
    ]
    assert extract_user_text_from_diarised(segments, swap=False) == "hello world"
    assert extract_user_text_from_diarised(segments, swap=True) == "hi"


def test_compute_user_error_rates_still_reports_insertions():
    """TTS-adjacent helper kept for callers that still pass an explicit pair."""
    out = compute_user_error_rates("hello world", "hello there world")
    assert "skipped" not in out
    assert out["details"]["insertions"] == 1
    assert out["details"]["ref_word_count"] == 2


def test_normalize_for_wer_collapses_currency():
    a = normalize_for_wer("pay ten dollars")
    b = normalize_for_wer("pay $10")
    assert "<amount>" in a
    assert "<num>" in b or "<amount>" in b
