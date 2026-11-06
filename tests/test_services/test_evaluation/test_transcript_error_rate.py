"""Script-aware production-vs-diarised WER/CER."""

import time

from app.services.evaluation.transcript_error_rates import (
    compute_transcript_error_rates,
    normalise_for_error_rate,
    select_comparison_texts,
)


def _score(reference: str, hypothesis: str, *, mode: str = "native", mismatch: bool = False):
    return compute_transcript_error_rates(
        reference,
        hypothesis,
        mode=mode,
        script_mismatch=mismatch,
    )


def test_identical_native_text_is_zero():
    text = "मैं आपकी क्या सहायता कर सकती हूं"
    out = _score(text, text)
    assert out["cer"] == 0.0
    assert out["wer"] == 0.0


def test_danda_and_nukta_variants_score_zero():
    reference = "मैं आपकी क्या सहायता कर सकती हूं।"
    hypothesis = "मैं आपकी क्या सहायता कर सकती हूँ"
    out = _score(reference, hypothesis)
    assert out["cer"] == 0.0
    nukta = _score("फ़ोन", "फोन")
    assert nukta["cer"] == 0.0
    assert nukta["wer"] == 0.0


def test_devanagari_digits_match_ascii():
    out = _score("कॉल ९८", "कॉल 98")
    assert out["cer"] == 0.0
    assert out["wer"] == 0.0


def test_fillers_and_speaker_prefixes_are_removed():
    out = _score("Agent: hello hmm there", "User: hello there")
    assert out["cer"] == 0.0
    assert out["wer"] == 0.0
    assert "hmm" not in normalise_for_error_rate("hmm hello", romanised=False)


def test_romanised_fallback_hinglish_cer_is_low():
    production = "Agent: ignore this agent turn\nUser: मैं आपकी क्या सहायता कर सकती हूं"
    diarised = "Agent: ignore this agent turn\nUser: Main aap ki kya sahayata kar sakthi hu"
    selected = select_comparison_texts(
        production_transcript=production,
        diarised_transcript=diarised,
    )
    assert "ignore" not in selected["reference"]
    assert "ignore" not in selected["hypothesis"]
    assert selected["mode"] == "romanised_fallback"
    assert selected["script_mismatch"] is True
    out = compute_transcript_error_rates(
        selected["reference"],
        selected["hypothesis"],
        mode=selected["mode"],
        script_mismatch=selected["script_mismatch"],
    )
    assert out["cer"] is not None
    assert out["cer"] < 0.3
    assert out["mode"] == "romanised_fallback"


def test_empty_production_reference_is_none():
    out = _score("   ", "hello there")
    assert out["cer"] is None
    assert out["wer"] is None


def test_agent_speech_is_excluded_from_both_sides():
    production = (
        "agent: मैं बजाज के customer care center से ही बोल रही हूँ\n"
        "user: Please connect to service sales person."
    )
    diarised = (
        "user: Please connect to service sales person.\n"
        "agent: Namaste, main Aadya bol rahi hoon Bajaj Electricals se.\n"
        "user: Connect to service sales person.\n"
        "agent: Main Bajaj ke customer care center se hi bol rahi hoon."
    )
    selected = select_comparison_texts(
        production_transcript=production,
        diarised_transcript=diarised,
    )
    assert selected["mode"] == "native"
    assert selected["script_mismatch"] is False
    assert "बजाज" not in selected["reference"]
    assert "Namaste" not in selected["hypothesis"]
    out = compute_transcript_error_rates(
        selected["reference"],
        selected["hypothesis"],
        mode=selected["mode"],
        script_mismatch=selected["script_mismatch"],
    )
    assert out["ref_words"] == 6
    assert out["cer"] is not None
    assert out["cer"] < 1.0


def test_unlabelled_production_has_no_user_reference():
    selected = select_comparison_texts(
        production_transcript="मैं बजाज के customer care से बोल रही हूँ",
        diarised_transcript="User: Please connect to service sales person.",
    )
    assert selected["reference"] == ""
    assert selected["hypothesis"] == "Please connect to service sales person."


def test_empty_hypothesis_scores_one():
    out = _score("alpha beta", "")
    assert out["wer"] == 1.0
    assert out["cer"] == 1.0


def test_only_user_turns_are_scored_and_swap_flips_the_user():
    production = "Agent: hello from the agent\nUser: thanks"
    original_speakers = [
        {"speaker": "agent", "text": "hello from the agent"},
        {"speaker": "user", "text": "thanks"},
    ]
    swapped_speakers = [
        {"speaker": "user", "text": "hello from the agent"},
        {"speaker": "agent", "text": "thanks"},
    ]
    first = select_comparison_texts(
        production_transcript=production,
        diarised_segments=original_speakers,
    )
    assert first["reference"] == "thanks"
    assert first["hypothesis"] == "thanks"
    second = select_comparison_texts(
        production_transcript=production,
        diarised_segments=swapped_speakers,
        diarised_speaker_swap=True,
    )
    assert second["hypothesis"] == "thanks"
    scored = compute_transcript_error_rates(
        first["reference"],
        first["hypothesis"],
        mode=first["mode"],
        script_mismatch=first["script_mismatch"],
    )
    assert scored["cer"] == 0.0


def test_agent_native_text_is_not_the_hypothesis():
    selected = select_comparison_texts(
        production_transcript="User: hello there",
        diarised_segments=[
            {
                "speaker": "agent",
                "text": "Main aap ki",
                "text_native": "मैं आपकी",
            },
            {"speaker": "user", "text": "hello there"},
        ],
        diarised_native_transcript="मैं आपकी hello there",
    )
    assert selected["mode"] == "native"
    assert selected["hypothesis"] == "hello there"
    assert selected["reference"] == "hello there"
    assert selected["script_mismatch"] is False


def test_text_native_on_the_user_turn_is_preferred():
    selected = select_comparison_texts(
        production_transcript="User: मैं आपकी",
        diarised_segments=[
            {"speaker": "agent", "text": "ignore", "text_native": "एजेंट"},
            {"speaker": "user", "text": "Main aap ki", "text_native": "मैं आपकी"},
        ],
    )
    assert selected["mode"] == "native"
    assert selected["hypothesis"] == "मैं आपकी"
    assert selected["script_mismatch"] is False


def test_long_inputs_finish_quickly():
    reference = " ".join(["word"] * 10_000)
    hypothesis = " ".join(["word"] * 10_000)
    started = time.perf_counter()
    out = _score(reference, hypothesis)
    elapsed = time.perf_counter() - started
    assert out["cer"] == 0.0
    assert elapsed < 1.0


def test_numbered_speaker_aliases_keep_user_turns():
    selected = select_comparison_texts(
        production_transcript="speaker 1: agent line\nspeaker 2: hello there",
        diarised_transcript="speaker1: agent line\nspeaker2: hello there",
    )
    assert selected["reference"] == "hello there"
    assert selected["hypothesis"] == "hello there"
    assert "agent line" not in selected["reference"]
    assert "agent line" not in selected["hypothesis"]


def test_matching_indic_text_stays_native_without_text_native():
    sentence = "मैं आपकी क्या सहायता कर सकती हूं"
    selected = select_comparison_texts(
        production_transcript=f"User: {sentence}",
        diarised_transcript=f"User: {sentence}",
    )
    assert selected["mode"] == "native"
    assert selected["reference"] == sentence
    assert selected["hypothesis"] == sentence
    assert selected["script_mismatch"] is False
    out = compute_transcript_error_rates(
        selected["reference"],
        selected["hypothesis"],
        mode=selected["mode"],
        script_mismatch=selected["script_mismatch"],
    )
    assert out["cer"] == 0.0
    assert out["wer"] == 0.0
