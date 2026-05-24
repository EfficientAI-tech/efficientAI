"""Unit tests for app.services.judge_alignment.judge_runner pure helpers.

Covers:

- _parse_judge_response: tolerant parser that extracts {prediction,
  explanation} from whatever the LLM returns (raw JSON, markdown-fenced
  JSON, free text containing only the keyword).
- _field_header / _build_user_message: the prompt scaffolding that
  surfaces "User turns" / "Agent turns" headers for transcript
  datasets and the generic "Sample input" / "Sample output" headers
  otherwise.

Both are pure functions with no DB access; we instantiate JudgeSample
in-memory without committing to satisfy _build_user_message's input.
"""

import pytest

from app.models.database import JudgeSample
from app.services.judge_alignment.judge_runner import (
    INPUT_TRUNCATE,
    OUTPUT_TRUNCATE,
    _build_user_message,
    _field_header,
    _parse_judge_response,
)


# ---------------------------------------------------------------------------
# _parse_judge_response
# ---------------------------------------------------------------------------


def test_parse_returns_none_for_empty_string():
    parsed = _parse_judge_response("")

    assert parsed["prediction"] is None
    assert parsed["explanation"] is None
    assert parsed["raw"] == ""


def test_parse_extracts_plain_json_object():
    parsed = _parse_judge_response(
        '{"prediction": "fail", "explanation": "tone too casual"}'
    )

    assert parsed["prediction"] == "fail"
    assert parsed["explanation"] == "tone too casual"


def test_parse_strips_markdown_code_fences_around_json():
    raw = '```json\n{"prediction": "pass", "explanation": "ok"}\n```'

    parsed = _parse_judge_response(raw)

    assert parsed["prediction"] == "pass"
    assert parsed["explanation"] == "ok"


def test_parse_strips_bare_triple_backtick_fences():
    raw = '```\n{"prediction": "fail", "explanation": "x"}\n```'

    parsed = _parse_judge_response(raw)

    assert parsed["prediction"] == "fail"


def test_parse_finds_json_object_embedded_in_prose():
    raw = (
        'Here is my verdict:\n{"prediction": "fail", "explanation": "rude"}\n'
        "Hope that helps!"
    )

    parsed = _parse_judge_response(raw)

    assert parsed["prediction"] == "fail"
    assert parsed["explanation"] == "rude"


def test_parse_normalises_truthy_falsy_prediction_aliases():
    assert _parse_judge_response('{"prediction": 1}')["prediction"] == "fail"
    assert _parse_judge_response('{"prediction": "true"}')["prediction"] == "fail"
    assert _parse_judge_response('{"prediction": 0}')["prediction"] == "pass"
    assert _parse_judge_response('{"prediction": "false"}')["prediction"] == "pass"


def test_parse_falls_back_to_keyword_when_json_invalid():
    """Malformed responses should still surface a verdict if the keyword is unambiguous."""
    assert _parse_judge_response("This response should fail.")["prediction"] == "fail"
    assert _parse_judge_response("Looks like a pass to me.")["prediction"] == "pass"


def test_parse_returns_none_when_keyword_is_ambiguous():
    """Both 'pass' and 'fail' present and JSON unparseable -> no verdict."""
    parsed = _parse_judge_response("Could be a pass, but might fail too.")

    assert parsed["prediction"] is None
    # Explanation falls back to the (truncated) raw text.
    assert parsed["explanation"] is not None


def test_parse_returns_none_for_unknown_prediction_value():
    parsed = _parse_judge_response('{"prediction": "maybe", "explanation": "idk"}')

    assert parsed["prediction"] is None
    assert parsed["explanation"] == "idk"


def test_parse_truncates_explanation_to_500_chars():
    long_text = "x" * 1000
    raw = f'{{"prediction": "fail", "explanation": "{long_text}"}}'

    parsed = _parse_judge_response(raw)

    assert parsed["prediction"] == "fail"
    assert len(parsed["explanation"]) == 500


def test_parse_preserves_raw_response_for_audit():
    raw = '```json\n{"prediction": "pass"}\n```'

    parsed = _parse_judge_response(raw)

    assert parsed["raw"] == raw


# ---------------------------------------------------------------------------
# _field_header
# ---------------------------------------------------------------------------


def test_field_header_uses_friendly_labels_for_transcript_roles():
    assert _field_header("user", "input") == "User turns (test agent / customer)"
    assert _field_header("agent", "output") == "Agent turns (Voice AI under evaluation)"


def test_field_header_falls_back_to_generic_when_field_missing():
    assert _field_header(None, "input") == "Sample input"
    assert _field_header("", "output") == "Sample output"


def test_field_header_titlecases_unknown_custom_fields():
    """Custom CSV columns (e.g. `agent_response`) get a readable header."""
    assert _field_header("agent_response", "output") == "Agent Response"


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------


def _sample(input_text: str = "hi", output_text: str = "bye") -> JudgeSample:
    """Construct a JudgeSample without touching the DB."""
    return JudgeSample(input_text=input_text, output_text=output_text)


def test_build_user_message_uses_role_specific_headers_for_transcripts():
    msg = _build_user_message(
        criteria="Be polite.",
        sample=_sample("user said hi", "agent said bye"),
        input_field="user",
        output_field="agent",
    )

    assert "## Evaluation criteria\nBe polite." in msg
    assert "## User turns (test agent / customer)\nuser said hi" in msg
    assert "## Agent turns (Voice AI under evaluation)\nagent said bye" in msg


def test_build_user_message_uses_generic_headers_when_fields_omitted():
    msg = _build_user_message(criteria="x", sample=_sample("a", "b"))

    assert "## Sample input\na" in msg
    assert "## Sample output\nb" in msg
    # Should not leak the transcript-specific scaffolding.
    assert "User turns" not in msg
    assert "Agent turns" not in msg


def test_build_user_message_strips_surrounding_whitespace_from_criteria():
    msg = _build_user_message(
        criteria="   leading and trailing   \n",
        sample=_sample(),
    )

    assert "## Evaluation criteria\nleading and trailing" in msg


def test_build_user_message_truncates_oversized_input_and_output():
    big_in = "I" * (INPUT_TRUNCATE + 500)
    big_out = "O" * (OUTPUT_TRUNCATE + 500)

    msg = _build_user_message(
        criteria="x",
        sample=_sample(big_in, big_out),
    )

    # The full untruncated string should not appear.
    assert big_in not in msg
    assert big_out not in msg
    # But the truncated prefix should.
    assert "I" * INPUT_TRUNCATE in msg
    assert "O" * OUTPUT_TRUNCATE in msg


def test_build_user_message_handles_none_input_and_output_safely():
    """SQLAlchemy nullables can come back as None for unmapped rows."""
    sample = JudgeSample(input_text=None, output_text=None)  # type: ignore[arg-type]

    msg = _build_user_message(criteria="x", sample=sample)

    # Should not raise; renders empty placeholders.
    assert "## Sample input\n\n" in msg
    assert "## Sample output\n\n" in msg


def test_build_user_message_appends_response_format_instruction():
    msg = _build_user_message(criteria="x", sample=_sample())

    assert 'Respond with JSON: {"prediction": "pass"|"fail"' in msg


# Silence pytest about unused import in IDEs (kept for type symmetry).
_ = pytest
