"""Unit tests for app.workers.tasks.helpers.llm_evaluation enum / number_range handling.

These tests focus on the prompt-builder, system-message, and score-mapping pieces
introduced for custom-data-type aware metric evaluation. They exercise pure-function
behavior - no DB session and no LLM calls required.
"""

from types import SimpleNamespace

from app.workers.tasks.helpers import llm_evaluation


def _make_metric(
    *,
    name,
    metric_type="rating",
    custom_data_type=None,
    custom_config=None,
    description=None,
    metric_id=None,
):
    """Build a duck-typed metric matching what the helpers read off ORM rows."""
    return SimpleNamespace(
        id=metric_id or f"id-{name}",
        name=name,
        description=description or f"Evaluate {name}",
        metric_type=metric_type,
        custom_data_type=custom_data_type,
        custom_config=custom_config,
    )


# ---------------------------------------------------------------------------
# _normalize_enum_value
# ---------------------------------------------------------------------------

def test_normalize_enum_value_exact_match_is_canonical():
    assert llm_evaluation._normalize_enum_value("Good", ["Good", "Bad"]) == "Good"


def test_normalize_enum_value_is_case_insensitive_but_returns_canonical_casing():
    assert llm_evaluation._normalize_enum_value("good", ["Good", "Bad"]) == "Good"
    assert llm_evaluation._normalize_enum_value("BAD", ["Good", "Bad"]) == "Bad"


def test_normalize_enum_value_falls_back_to_substring_match():
    # LLM may say "very good" - we accept it as long as one option is contained.
    assert llm_evaluation._normalize_enum_value("very good", ["Good", "Bad"]) == "Good"
    # Other direction: option contained in returned label.
    assert (
        llm_evaluation._normalize_enum_value("excellent", ["Excellent", "Acceptable"])
        == "Excellent"
    )


def test_normalize_enum_value_returns_none_for_no_match():
    assert llm_evaluation._normalize_enum_value("unrelated", ["Good", "Bad"]) is None


def test_normalize_enum_value_returns_none_for_empty_inputs():
    assert llm_evaluation._normalize_enum_value(None, ["Good"]) is None
    assert llm_evaluation._normalize_enum_value("Good", []) is None
    assert llm_evaluation._normalize_enum_value("", ["Good"]) is None


def test_normalize_enum_value_extracts_from_dict_response():
    # LLMs sometimes wrap their answer; the helper unwraps common keys.
    payload = {"value": "Good", "explanation": "..."}
    assert llm_evaluation._normalize_enum_value(payload, ["Good", "Bad"]) == "Good"


# ---------------------------------------------------------------------------
# build_evaluation_prompt - custom data type rendering
# ---------------------------------------------------------------------------

def test_build_evaluation_prompt_lists_enum_options():
    enum_metric = _make_metric(
        name="Tone Category",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["Good", "Bad", "Poor", "Neutral"]},
    )
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=[enum_metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
    )
    assert '"tone_category" (one of: "Good", "Bad", "Poor", "Neutral")' in prompt
    # Example response section uses the first option as the sample value.
    assert '"tone_category": "Good"' in prompt


def test_build_evaluation_prompt_lists_number_range_bounds():
    metric = _make_metric(
        name="CSAT",
        metric_type="number",
        custom_data_type="number_range",
        custom_config={"min": 1, "max": 5, "step": 1},
    )
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
    )
    assert '"csat" (numeric, min=1, max=5, step=1)' in prompt


def test_build_evaluation_prompt_falls_back_to_legacy_format_for_non_custom_metrics():
    rating_metric = _make_metric(name="Follow Instructions", metric_type="rating")
    boolean_metric = _make_metric(name="Booking Done", metric_type="boolean")
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=[rating_metric, boolean_metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
    )
    assert '"follow_instructions" (rating 0.0-1.0)' in prompt
    assert '"booking_done" (true/false)' in prompt


def test_build_evaluation_prompt_skips_enum_branch_when_options_missing():
    # Enum custom_data_type with no options falls back to the legacy rating
    # rendering rather than producing a malformed enum line. We assert on the
    # metric-specific pattern because the static response-format instructions
    # block contains the literal phrase "one of: ..." in its rules text.
    metric = _make_metric(
        name="Sentiment",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={},
    )
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
    )
    assert '"sentiment" (one of:' not in prompt
    assert '"sentiment" (rating 0.0-1.0)' in prompt


# ---------------------------------------------------------------------------
# _build_system_message
# ---------------------------------------------------------------------------

def test_build_system_message_includes_enum_constraint_per_metric():
    enum_a = _make_metric(
        name="Tone",
        custom_data_type="enum",
        custom_config={"options": ["Friendly", "Cold"]},
    )
    enum_b = _make_metric(
        name="Outcome",
        custom_data_type="enum",
        custom_config={"options": ["Won", "Lost", "Pending"]},
    )
    rating = _make_metric(name="Quality", metric_type="rating")
    msg = llm_evaluation._build_system_message([enum_a, enum_b, rating])
    assert "Enum metrics must use a STRING value" in msg
    assert '"tone" must be EXACTLY one of: ["Friendly", "Cold"]' in msg
    assert '"outcome" must be EXACTLY one of: ["Won", "Lost", "Pending"]' in msg


def test_build_system_message_omits_enum_block_when_no_enum_metrics():
    rating = _make_metric(name="Quality", metric_type="rating")
    msg = llm_evaluation._build_system_message([rating])
    assert "Enum metrics" not in msg


# ---------------------------------------------------------------------------
# _map_evaluation_to_metrics - enum + number_range branches
# ---------------------------------------------------------------------------

def test_map_evaluation_preserves_enum_string_with_options():
    metric = _make_metric(
        name="Tone Category",
        custom_data_type="enum",
        custom_config={"options": ["Good", "Bad", "Neutral"]},
    )
    scores = llm_evaluation._map_evaluation_to_metrics(
        {"tone_category": "Good"}, [metric]
    )
    entry = scores[str(metric.id)]
    assert entry["value"] == "Good"
    assert entry["type"] == "enum"
    assert entry["metric_name"] == "Tone Category"
    assert entry["options"] == ["Good", "Bad", "Neutral"]
    assert "raw_value" not in entry


def test_map_evaluation_records_raw_value_when_enum_response_unrecognized():
    metric = _make_metric(
        name="Tone Category",
        custom_data_type="enum",
        custom_config={"options": ["Good", "Bad"]},
    )
    scores = llm_evaluation._map_evaluation_to_metrics(
        {"tone_category": "wonderful"}, [metric]
    )
    entry = scores[str(metric.id)]
    assert entry["value"] is None
    assert entry["type"] == "enum"
    assert entry["raw_value"] == "wonderful"
    assert entry["options"] == ["Good", "Bad"]


def test_map_evaluation_clamps_number_range_to_bounds():
    metric = _make_metric(
        name="CSAT",
        metric_type="number",
        custom_data_type="number_range",
        custom_config={"min": 1, "max": 5, "step": 1},
    )
    high = llm_evaluation._map_evaluation_to_metrics({"csat": 9.0}, [metric])
    low = llm_evaluation._map_evaluation_to_metrics({"csat": -3.0}, [metric])
    inside = llm_evaluation._map_evaluation_to_metrics({"csat": 3.5}, [metric])
    assert high[str(metric.id)]["value"] == 5.0
    assert low[str(metric.id)]["value"] == 1.0
    assert inside[str(metric.id)]["value"] == 3.5


def test_map_evaluation_keeps_legacy_rating_normalization_for_non_custom_metrics():
    metric = _make_metric(name="Follow Instructions", metric_type="rating")
    scores = llm_evaluation._map_evaluation_to_metrics(
        {"follow_instructions": 0.85}, [metric]
    )
    entry = scores[str(metric.id)]
    assert entry["type"] == "rating"
    assert entry["value"] == 0.85
    assert "options" not in entry


# ---------------------------------------------------------------------------
# Text / summary metric type
# ---------------------------------------------------------------------------

def test_coerce_text_value_handles_plain_string():
    assert llm_evaluation._coerce_text_value("Customer was happy.") == "Customer was happy."


def test_coerce_text_value_strips_whitespace_and_returns_none_for_empty():
    assert llm_evaluation._coerce_text_value("   ") is None
    assert llm_evaluation._coerce_text_value("") is None
    assert llm_evaluation._coerce_text_value(None) is None


def test_coerce_text_value_unwraps_dict_wrapper():
    assert (
        llm_evaluation._coerce_text_value({"value": "Resolved on first call."})
        == "Resolved on first call."
    )
    assert (
        llm_evaluation._coerce_text_value({"summary": "Short summary."})
        == "Short summary."
    )


def test_coerce_text_value_coerces_scalars_to_string():
    assert llm_evaluation._coerce_text_value(42) == "42"
    assert llm_evaluation._coerce_text_value(True) == "True"


def test_coerce_text_value_joins_list_of_strings():
    assert (
        llm_evaluation._coerce_text_value(["Issue: billing.", "Outcome: refund."])
        == "Issue: billing. Outcome: refund."
    )


def test_map_evaluation_text_metric_stores_free_form_string():
    metric = _make_metric(name="Call Summary", metric_type="text")
    scores = llm_evaluation._map_evaluation_to_metrics(
        {"call_summary": "Customer asked about billing; agent issued refund."},
        [metric],
    )
    entry = scores[str(metric.id)]
    assert entry["type"] == "text"
    assert entry["metric_name"] == "Call Summary"
    assert entry["value"] == "Customer asked about billing; agent issued refund."


def test_map_evaluation_text_metric_tolerates_dict_wrapper_from_llm():
    metric = _make_metric(name="Call Summary", metric_type="text")
    scores = llm_evaluation._map_evaluation_to_metrics(
        {"call_summary": {"value": "Brief outcome."}}, [metric]
    )
    entry = scores[str(metric.id)]
    assert entry["type"] == "text"
    assert entry["value"] == "Brief outcome."


def test_map_evaluation_text_metric_records_none_when_value_missing():
    metric = _make_metric(name="Call Summary", metric_type="text")
    scores = llm_evaluation._map_evaluation_to_metrics({}, [metric])
    entry = scores[str(metric.id)]
    assert entry["type"] == "text"
    assert entry["value"] is None


def test_build_evaluation_prompt_includes_text_metric_hint():
    metric = _make_metric(
        name="Call Summary",
        metric_type="text",
        description="Summarize the call in 1-3 sentences.",
    )
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi", llm_metrics=[metric]
    )
    assert '"call_summary"' in prompt
    assert "free-form text" in prompt.lower()
    assert "Summarize the call" in prompt


def test_build_system_message_lists_text_keys_with_string_rule():
    metric = _make_metric(name="Call Summary", metric_type="text")
    msg = llm_evaluation._build_system_message([metric])
    assert "Text metrics must use a plain JSON STRING value" in msg
    assert '"call_summary"' in msg


def test_text_metric_type_wins_over_stale_enum_custom_data_type():
    """A metric whose ``custom_data_type`` is left over from a prior enum
    configuration must still be evaluated as free-form text when the user
    switches its ``metric_type`` to ``text``."""
    metric = _make_metric(
        name="Call Summary",
        metric_type="text",
        custom_data_type="enum",
        custom_config={"options": ["Good", "Bad"]},
    )

    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi", llm_metrics=[metric]
    )
    # The metric-definition line for ``call_summary`` should describe it as
    # free-form text, NOT as a stale enum.
    assert '"call_summary" (free-form text' in prompt
    assert '"call_summary" (one of:' not in prompt
    # And the stale enum options must not appear anywhere as expected values
    # for this metric. (The string ``"one of: ..."`` itself appears in the
    # static CRITICAL RULES boilerplate of the prompt - that is documentation
    # about enum metrics in general, not about this metric, and is fine.)
    assert '"Good"' not in prompt
    assert '"Bad"' not in prompt

    instructions = llm_evaluation._build_response_format_instructions([metric])
    assert '"Good"' not in instructions  # stale enum example must not appear
    assert "1-3 sentence summary" in instructions

    scores = llm_evaluation._map_evaluation_to_metrics(
        {"call_summary": "Customer asked about billing; agent resolved."},
        [metric],
    )
    entry = scores[str(metric.id)]
    assert entry["type"] == "text"
    assert entry["value"] == "Customer asked about billing; agent resolved."
    assert "options" not in entry
