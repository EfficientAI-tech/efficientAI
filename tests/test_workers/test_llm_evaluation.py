"""Unit tests for app.workers.tasks.helpers.llm_evaluation enum / number_range handling.

These tests focus on the prompt-builder, system-message, and score-mapping pieces
introduced for custom-data-type aware metric evaluation. They exercise pure-function
behavior - no DB session and no LLM calls required.
"""

import importlib
import json
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.workers.tasks.helpers import llm_evaluation


@pytest.fixture(autouse=True)
def _load_real_llm_service_module():
    """Use the real ``llm_service.py`` (conftest stubs a lightweight fake for API tests)."""
    qual = "app.services.ai.llm_service"
    sys.modules.pop(qual, None)
    importlib.import_module(qual)


def _patch_llm_generate_response(monkeypatch, replacement):
    mod = importlib.import_module("app.services.ai.llm_service")
    monkeypatch.setattr(mod.llm_service, "generate_response", replacement, raising=False)


def _make_metric(
    *,
    name,
    metric_type="rating",
    custom_data_type=None,
    custom_config=None,
    description=None,
    metric_id=None,
    capture_rationale=False,
):
    """Build a duck-typed metric matching what the helpers read off ORM rows."""
    return SimpleNamespace(
        id=metric_id or f"id-{name}",
        name=name,
        description=description or f"Evaluate {name}",
        metric_type=metric_type,
        custom_data_type=custom_data_type,
        custom_config=custom_config,
        capture_rationale=capture_rationale,
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


# ---------------------------------------------------------------------------
# capture_rationale: prompt + parser + system message
# ---------------------------------------------------------------------------


def test_build_evaluation_prompt_adds_rationale_key_when_capture_rationale():
    metric = _make_metric(
        name="Pitch Type",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["WITH data", "WITHOUT data", "Others"]},
        capture_rationale=True,
    )
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
    )
    assert '"pitch_type" (one of:' in prompt
    assert '"pitch_type_rationale" (free-form text' in prompt
    # Example block should also include the rationale placeholder.
    assert '"pitch_type_rationale": "Brief justification' in prompt


def test_build_evaluation_prompt_omits_rationale_key_when_capture_rationale_false():
    metric = _make_metric(
        name="Pitch Type",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["A", "B"]},
        capture_rationale=False,
    )
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
    )
    assert "_rationale" not in prompt


def test_build_evaluation_prompt_skips_rationale_for_text_metrics():
    # Text metrics are themselves free-form prose; layering a rationale on
    # top would just be redundant. The flag is silently ignored.
    metric = _make_metric(
        name="Call Summary",
        metric_type="text",
        capture_rationale=True,
    )
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi", llm_metrics=[metric]
    )
    assert "_rationale" not in prompt


def test_build_system_message_includes_rationale_keys_in_exact_keys():
    metric = _make_metric(
        name="Pitch Type",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["A", "B"]},
        capture_rationale=True,
    )
    msg = llm_evaluation._build_system_message([metric])
    assert '"pitch_type"' in msg
    assert '"pitch_type_rationale"' in msg
    assert "Rationale companion keys must use a plain JSON STRING" in msg


def test_map_evaluation_attaches_rationale_to_enum_score():
    metric = _make_metric(
        name="Pitch Type",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["WITH data", "WITHOUT data"]},
        capture_rationale=True,
    )
    scores = llm_evaluation._map_evaluation_to_metrics(
        {
            "pitch_type": "WITH data",
            "pitch_type_rationale": "Agent referenced 120% growth.",
        },
        [metric],
    )
    entry = scores[str(metric.id)]
    assert entry["value"] == "WITH data"
    assert entry["rationale"] == "Agent referenced 120% growth."


def test_map_evaluation_attaches_rationale_to_rating_score():
    metric = _make_metric(
        name="Follow Instructions",
        metric_type="rating",
        capture_rationale=True,
    )
    scores = llm_evaluation._map_evaluation_to_metrics(
        {
            "follow_instructions": 0.9,
            "follow_instructions_rationale": "Followed every step.",
        },
        [metric],
    )
    entry = scores[str(metric.id)]
    assert entry["value"] == 0.9
    assert entry["rationale"] == "Followed every step."


def test_map_evaluation_rationale_is_none_when_missing_in_response():
    metric = _make_metric(
        name="Pitch Type",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["A", "B"]},
        capture_rationale=True,
    )
    scores = llm_evaluation._map_evaluation_to_metrics(
        {"pitch_type": "A"},  # no _rationale companion key
        [metric],
    )
    entry = scores[str(metric.id)]
    assert entry["value"] == "A"
    assert entry["rationale"] is None


def test_map_evaluation_omits_rationale_when_capture_rationale_false():
    metric = _make_metric(
        name="Pitch Type",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["A", "B"]},
        capture_rationale=False,
    )
    scores = llm_evaluation._map_evaluation_to_metrics(
        {"pitch_type": "A", "pitch_type_rationale": "ignored"},
        [metric],
    )
    entry = scores[str(metric.id)]
    # Rationale field is intentionally NOT present on the entry to avoid
    # bloating storage for metrics that didn't ask for it.
    assert "rationale" not in entry


def test_handle_llm_evaluation_error_includes_null_rationale_when_flag_on():
    metric = _make_metric(
        name="Pitch Type",
        metric_type="rating",
        custom_data_type="enum",
        custom_config={"options": ["A", "B"]},
        capture_rationale=True,
    )
    plain = _make_metric(name="Other", metric_type="rating")
    scores = llm_evaluation.handle_llm_evaluation_error(
        [metric, plain], RuntimeError("nope")
    )
    rationale_entry = scores[str(metric.id)]
    assert rationale_entry["value"] is None
    assert rationale_entry["rationale"] is None
    plain_entry = scores[str(plain.id)]
    assert plain_entry["value"] is None
    assert "rationale" not in plain_entry


# ---------------------------------------------------------------------------
# extra_context — column-input judge support
# ---------------------------------------------------------------------------


def test_build_evaluation_prompt_injects_extra_context_in_default_branch():
    metric = _make_metric(name="Column Judge", metric_type="rating")
    context = "- customer_intent: refund\n- agent_response: granted"
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="conversation goes here",
        llm_metrics=[metric],
        agent=SimpleNamespace(name="Agent", description=None, call_type=None),
        scenario=SimpleNamespace(name="Sc", description=None, required_info=None),
        persona=None,
        extra_context=context,
    )
    # Header is present and the named cells are surfaced verbatim.
    assert "## Context Inputs" in prompt
    assert "customer_intent: refund" in prompt
    assert "agent_response: granted" in prompt
    # The Context Inputs block must precede the transcript so the LLM
    # reads inputs first and isn't biased by the dialog text.
    assert prompt.index("## Context Inputs") < prompt.index(
        "## Conversation Transcript"
    )


def test_build_evaluation_prompt_injects_extra_context_in_custom_evaluator_branch():
    metric = _make_metric(name="Column Judge", metric_type="rating")
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="...",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
        extra_context="- col_a: value_a",
    )
    assert "## Context Inputs" in prompt
    assert "col_a: value_a" in prompt


def test_build_evaluation_prompt_omits_context_section_when_extra_context_blank():
    metric = _make_metric(name="Plain Judge", metric_type="rating")
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="conversation",
        llm_metrics=[metric],
        agent=SimpleNamespace(name="Agent", description=None, call_type=None),
        scenario=SimpleNamespace(name="Sc", description=None, required_info=None),
        persona=None,
        extra_context=None,
    )
    assert "## Context Inputs" not in prompt
    # And whitespace-only context behaves the same way.
    prompt_blank = llm_evaluation.build_evaluation_prompt(
        transcription="conversation",
        llm_metrics=[metric],
        agent=SimpleNamespace(name="Agent", description=None, call_type=None),
        scenario=SimpleNamespace(name="Sc", description=None, required_info=None),
        persona=None,
        extra_context="   \n  ",
    )
    assert "## Context Inputs" not in prompt_blank


# ---------------------------------------------------------------------------
# build_evaluation_prompt: comparison_pair (transcript-compare judge)
# ---------------------------------------------------------------------------


def test_build_evaluation_prompt_renders_dual_transcript_header_when_comparison_pair_set():
    """A transcript-compare judge metric replaces the single
    ``## Conversation Transcript`` block with a labeled pair so the
    LLM is unambiguous about which text is which."""
    metric = _make_metric(name="Transcript Fidelity", metric_type="rating")
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="this should NOT appear",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
        comparison_pair=(
            "Agent: How can I help?\nCustomer: Need a refund.",
            "[00:01] Agent: How can I help?\n[00:04] Customer: Need a refund.",
        ),
    )
    # Single-transcript header is suppressed.
    assert "## Conversation Transcript" not in prompt
    # Pair header + subsections are rendered.
    assert "## Transcripts to Compare" in prompt
    assert "### Production Transcript" in prompt
    assert "### Diarised Transcript" in prompt
    # Both texts are present verbatim.
    assert "Agent: How can I help?" in prompt
    assert "[00:01] Agent: How can I help?" in prompt
    # The literal value passed via ``transcription`` is ignored.
    assert "this should NOT appear" not in prompt


def test_build_evaluation_prompt_renders_dual_transcript_in_default_branch():
    """The dual-transcript section must also render in the default
    (non-custom-evaluator) branch — it's used when the call-import
    worker calls evaluate_with_llm without an evaluator object."""
    metric = _make_metric(name="Transcript Fidelity", metric_type="rating")
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="ignored",
        llm_metrics=[metric],
        agent=SimpleNamespace(name="Agent", description=None, call_type=None),
        scenario=SimpleNamespace(name="Sc", description=None, required_info=None),
        persona=None,
        comparison_pair=("PROD text", "DIARISED text"),
    )
    assert "## Conversation Transcript" not in prompt
    assert "## Transcripts to Compare" in prompt
    assert "### Production Transcript\nPROD text" in prompt
    assert "### Diarised Transcript\nDIARISED text" in prompt


def test_build_evaluation_prompt_dual_transcript_substitutes_placeholder_for_empty_side():
    """If one transcript is an empty string the prompt still renders a
    placeholder for that subsection so the LLM sees both labels and
    can produce a defensible 'missing' score instead of hallucinating."""
    metric = _make_metric(name="Comparison", metric_type="boolean")
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="ignored",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
        comparison_pair=("only production", ""),
    )
    assert "### Production Transcript\nonly production" in prompt
    # The empty diarised side is replaced by an explicit placeholder so
    # the LLM doesn't read the next "##" header as the transcript text.
    assert "### Diarised Transcript\n(empty)" in prompt


def test_build_evaluation_prompt_without_comparison_pair_keeps_single_transcript_block():
    """Backwards compatibility: when ``comparison_pair`` is omitted the
    builder keeps emitting the historical single-transcript block."""
    metric = _make_metric(name="Plain Judge", metric_type="rating")
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello there",
        llm_metrics=[metric],
        evaluator=SimpleNamespace(custom_prompt="judge it"),
    )
    assert "## Conversation Transcript" in prompt
    assert "hello there" in prompt
    assert "## Transcripts to Compare" not in prompt
    assert "### Production Transcript" not in prompt


def test_build_evaluation_prompt_renders_multiple_parent_and_flat_groups():
    parent_a = _make_metric(
        name="Outcome A",
        metric_type="boolean",
        description="Category A",
    )
    parent_a.selection_mode = "multi_label"
    parent_a.allow_discovery = False
    child_a = _make_metric(name="Child A1", metric_type="boolean")
    flat = _make_metric(name="Flat Score", metric_type="rating")
    parent_b = _make_metric(
        name="Outcome B",
        metric_type="boolean",
        description="Category B",
    )
    parent_b.selection_mode = "multi_label"
    parent_b.allow_discovery = False
    child_b = _make_metric(name="Child B1", metric_type="boolean")

    groups = [
        llm_evaluation.MetricPromptGroup(parent_a, [child_a], None),
        llm_evaluation.MetricPromptGroup(parent_b, [child_b], None),
        llm_evaluation.MetricPromptGroup(None, [flat], None),
    ]
    prompt = llm_evaluation.build_evaluation_prompt(
        "transcript body",
        [],
        metric_groups=groups,
    )
    assert "### Category: Outcome A" in prompt
    assert "### Category: Outcome B" in prompt
    assert '"flat_score"' in prompt
    assert len(llm_evaluation.flatten_metric_groups(groups)) == 3


def test_map_evaluation_to_metrics_handles_metric_groups():
    parent = _make_metric(name="Outcome", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "multi_label"
    parent.allow_discovery = False
    child = _make_metric(name="Yes Path", metric_type="boolean", metric_id="c1")
    flat = _make_metric(name="Quality", metric_type="rating", metric_id="f1")
    groups = [
        llm_evaluation.MetricPromptGroup(parent, [child], None),
        llm_evaluation.MetricPromptGroup(None, [flat], None),
    ]
    response = {
        "yes_path": True,
        "outcome__sequence": ["yes_path"],
        "quality": 0.9,
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        response,
        llm_evaluation.flatten_metric_groups(groups),
        metric_groups=groups,
    )
    assert "c1" in scores
    assert "p1" in scores
    assert "f1" in scores
    assert scores["f1"]["value"] == 0.9


# ---------------------------------------------------------------------------
# Namespaced categorization child keys (batched metric_groups)
# ---------------------------------------------------------------------------


def test_batched_metric_groups_prompt_uses_namespaced_child_keys():
    parent_a = _make_metric(name="AI reveal", metric_type="boolean")
    parent_a.selection_mode = "single_choice"
    parent_a.allow_discovery = False
    yes_a = _make_metric(name="Yes", metric_type="boolean")
    no_a = _make_metric(name="No", metric_type="boolean")
    parent_b = _make_metric(name="Bot gibberish", metric_type="boolean")
    parent_b.selection_mode = "single_choice"
    parent_b.allow_discovery = False
    yes_b = _make_metric(name="Yes", metric_type="boolean")
    no_b = _make_metric(name="No", metric_type="boolean")

    groups = [
        llm_evaluation.MetricPromptGroup(parent_a, [yes_a, no_a], None),
        llm_evaluation.MetricPromptGroup(parent_b, [yes_b, no_b], None),
    ]
    prompt = llm_evaluation.build_evaluation_prompt(
        "transcript",
        [],
        metric_groups=groups,
    )
    assert '"ai_reveal__yes"' in prompt
    assert '"ai_reveal__no"' in prompt
    assert '"bot_gibberish__yes"' in prompt
    assert '"bot_gibberish__no"' in prompt
    # Bare yes/no must not appear as child boolean keys in batched mode.
    assert '\n- "yes" (true/false)' not in prompt


def test_batched_yes_no_parents_parse_independently_with_namespaced_keys():
    parent_a = _make_metric(
        name="AI reveal", metric_type="boolean", metric_id="parent-a"
    )
    parent_a.selection_mode = "single_choice"
    parent_a.allow_discovery = False
    yes_a = _make_metric(name="Yes", metric_type="boolean", metric_id="yes-a")
    no_a = _make_metric(name="No", metric_type="boolean", metric_id="no-a")
    parent_b = _make_metric(
        name="Bot gibberish", metric_type="boolean", metric_id="parent-b"
    )
    parent_b.selection_mode = "single_choice"
    parent_b.allow_discovery = False
    yes_b = _make_metric(name="Yes", metric_type="boolean", metric_id="yes-b")
    no_b = _make_metric(name="No", metric_type="boolean", metric_id="no-b")

    groups = [
        llm_evaluation.MetricPromptGroup(parent_a, [yes_a, no_a], None),
        llm_evaluation.MetricPromptGroup(parent_b, [yes_b, no_b], None),
    ]
    response = {
        "ai_reveal": "no",
        "ai_reveal__yes": False,
        "ai_reveal__no": True,
        "ai_reveal__sequence": ["no"],
        "bot_gibberish": "yes",
        "bot_gibberish__yes": True,
        "bot_gibberish__no": False,
        "bot_gibberish__sequence": ["yes"],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        response,
        llm_evaluation.flatten_metric_groups(groups),
        metric_groups=groups,
    )
    assert scores["parent-a"]["value"] == "No"
    assert scores["parent-b"]["value"] == "Yes"
    assert scores["no-a"]["value"] is True
    assert scores["yes-b"]["value"] is True


def test_batched_outcome_detection_namespaced_children():
    parent = _make_metric(
        name="Outcome detection for ticket",
        metric_type="boolean",
        metric_id="outcome-parent",
    )
    parent.selection_mode = "single_choice"
    parent.allow_discovery = False
    children = [
        _make_metric(
            name="Product_not_delivered",
            metric_type="boolean",
            metric_id="c-prod",
        ),
        _make_metric(
            name="Pincode_unserviceable",
            metric_type="boolean",
            metric_id="c-pin",
        ),
    ]
    groups = [llm_evaluation.MetricPromptGroup(parent, children, None)]
    prompt = llm_evaluation.build_evaluation_prompt(
        "transcript", [], metric_groups=groups
    )
    assert '"outcome_detection_for_ticket__product_not_delivered"' in prompt
    assert '"outcome_detection_for_ticket__pincode_unserviceable"' in prompt

    response = {
        "outcome_detection_for_ticket": "pincode_unserviceable",
        "outcome_detection_for_ticket__product_not_delivered": False,
        "outcome_detection_for_ticket__pincode_unserviceable": True,
        "outcome_detection_for_ticket__sequence": ["pincode_unserviceable"],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        response,
        llm_evaluation.flatten_metric_groups(groups),
        metric_groups=groups,
    )
    assert scores["outcome-parent"]["value"] == "Pincode_unserviceable"
    assert scores["c-pin"]["value"] is True
    assert scores["c-prod"]["value"] is False


def test_legacy_single_parent_path_still_parses_bare_child_keys():
    parent = _make_metric(name="Call Outcome", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "single_choice"
    parent.allow_discovery = False
    happy = _make_metric(name="happy_completion", metric_type="boolean", metric_id="c1")
    angry = _make_metric(name="angry_hangup", metric_type="boolean", metric_id="c2")
    response = {
        "call_outcome": "angry_hangup",
        "happy_completion": False,
        "angry_hangup": True,
        "call_outcome__sequence": ["angry_hangup"],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        response,
        [happy, angry],
        parent_metric=parent,
    )
    assert scores["p1"]["value"] == "angry_hangup"
    assert scores["c2"]["value"] is True


def test_metric_groups_falls_back_to_bare_child_keys_when_namespaced_missing():
    parent = _make_metric(name="Outcome", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "multi_label"
    parent.allow_discovery = False
    child = _make_metric(name="Yes Path", metric_type="boolean", metric_id="c1")
    groups = [llm_evaluation.MetricPromptGroup(parent, [child], None)]
    response = {
        "yes_path": True,
        "outcome__sequence": ["yes_path"],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        response,
        llm_evaluation.flatten_metric_groups(groups),
        metric_groups=groups,
    )
    assert scores["c1"]["value"] is True


# ---------------------------------------------------------------------------
# Jev / Tev structured evaluation path
# ---------------------------------------------------------------------------


def test_is_jev_model_detects_tev_and_jev_ids():
    assert llm_evaluation._is_jev_model("together/Tev1-4B-experimental")
    assert llm_evaluation._is_jev_model("together_ai/together/Tev1-4B-experimental")
    assert llm_evaluation._is_jev_model("jev-latest")
    assert not llm_evaluation._is_jev_model("gpt-4o")
    assert not llm_evaluation._is_jev_model(None)


def test_build_jev_questions_maps_flat_boolean_enum_and_rating():
    boolean_metric = _make_metric(
        name="Is Urgent", metric_type="boolean", description="Urgent?"
    )
    enum_metric = _make_metric(
        name="Tone Category",
        custom_data_type="enum",
        custom_config={"options": ["Good", "Bad"]},
    )
    rating_metric = _make_metric(
        name="Quality", metric_type="rating", description="Rate quality"
    )
    groups = [
        llm_evaluation.MetricPromptGroup(
            None, [boolean_metric, enum_metric, rating_metric], None
        )
    ]
    questions, bindings, unsupported = llm_evaluation._build_jev_questions_and_bindings(
        groups
    )
    assert questions["is_urgent"]["type"] == "noul"
    assert questions["tone_category"]["type"] == "choice"
    assert questions["quality"]["type"] == "score"
    assert len(bindings) == 3
    assert unsupported == []


def test_build_jev_questions_maps_single_choice_parent_to_choice():
    parent = _make_metric(name="Call Outcome", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "single_choice"
    happy = _make_metric(name="happy_completion", metric_type="boolean", metric_id="c1")
    angry = _make_metric(name="angry_hangup", metric_type="boolean", metric_id="c2")
    groups = [llm_evaluation.MetricPromptGroup(parent, [happy, angry], None)]
    questions, bindings, unsupported = llm_evaluation._build_jev_questions_and_bindings(
        groups
    )
    assert questions["call_outcome"]["type"] == "choice"
    assert "happy_completion" in questions["call_outcome"]["criteria"]
    assert "angry_hangup" in questions["call_outcome"]["criteria"]
    assert unsupported == []


def test_map_jev_answers_maps_boolean_enum_and_single_choice():
    boolean_metric = _make_metric(name="Is Urgent", metric_type="boolean", metric_id="b1")
    enum_metric = _make_metric(
        name="Department",
        metric_id="e1",
        custom_data_type="enum",
        custom_config={"options": ["billing", "technical", "sales"]},
    )
    parent = _make_metric(name="Call Outcome", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "single_choice"
    angry = _make_metric(name="angry_hangup", metric_type="boolean", metric_id="c2")
    groups = [
        llm_evaluation.MetricPromptGroup(None, [boolean_metric, enum_metric], None),
        llm_evaluation.MetricPromptGroup(parent, [angry], None),
    ]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    answers = {
        "is_urgent": {"type": "noul", "noul": 0.94},
        "department": {
            "type": "choice",
            "choice": "technical",
            "confidence": 0.78,
            "probabilities": {"technical": 0.85, "sales": 0.0, "billing": 0.15},
        },
        "call_outcome": {"type": "choice", "choice": "angry_hangup"},
    }
    scores = llm_evaluation._map_jev_answers_to_metrics(answers, bindings, [])
    assert scores["b1"]["value"] is True
    assert scores["b1"]["noul_probability"] == 0.94
    assert scores["e1"]["value"] == "technical"
    assert scores["e1"]["confidence"] == 0.78
    assert scores["p1"]["value"] == "angry_hangup"
    assert scores["c2"]["value"] is True


def test_map_jev_answers_rating_normalizes_score_to_zero_one():
    metric = _make_metric(name="Quality", metric_type="rating", metric_id="r1")
    groups = [llm_evaluation.MetricPromptGroup(None, [metric], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    answers = {"quality": {"type": "score", "score": 3.0, "confidence": 1.0}}
    scores = llm_evaluation._map_jev_answers_to_metrics(answers, bindings, [])
    assert scores["r1"]["value"] == 0.75
    assert scores["r1"]["confidence"] == 1.0


def test_build_jev_questions_marks_text_metrics_unsupported():
    text_metric = _make_metric(name="Call Summary", metric_type="text", metric_id="t1")
    groups = [llm_evaluation.MetricPromptGroup(None, [text_metric], None)]
    questions, bindings, unsupported = llm_evaluation._build_jev_questions_and_bindings(
        groups
    )
    assert questions == {}
    assert bindings == []
    assert unsupported == [text_metric]


def test_build_classification_jev_questions_from_custom_config():
    metric = _make_metric(
        name="Outcome",
        metric_type="text",
        custom_data_type="classification",
        metric_id="cl1",
        custom_config={
            "noul": {
                "enabled": True,
                "instructions": "Resolved?",
                "criteria": {"true": "Yes", "false": "No"},
            },
            "choice": {
                "enabled": True,
                "instructions": "Issue type?",
                "criteria": {"billing": "Billing", "tech": "Technical"},
            },
            "score": {"enabled": False},
        },
    )
    questions = llm_evaluation._build_classification_jev_questions(metric)
    assert questions["noul"]["type"] == "noul"
    assert questions["choice"]["criteria"]["billing"] == "Billing"
    assert "score" not in questions


def test_map_classification_jev_answers_builds_display_and_probabilities():
    metric = _make_metric(name="Outcome", metric_type="text", metric_id="cl1")
    answers = {
        "noul": {"type": "noul", "noul": 0.92},
        "choice": {
            "type": "choice",
            "choice": "billing",
            "confidence": 0.8,
            "probabilities": {"billing": 0.9, "tech": 0.1},
        },
    }
    entry = llm_evaluation._map_classification_jev_answers(metric, answers)
    assert entry["type"] == "classification"
    assert "92%" in entry["value"]
    assert entry["answers"]["choice"]["probabilities"]["billing"] == 0.9
    assert entry["noul_probability"] == 0.92


def test_evaluate_with_llm_classification_requires_jev_model(monkeypatch):
    metric = _make_metric(
        name="Outcome",
        metric_type="text",
        custom_data_type="classification",
        metric_id="cl1",
        custom_config={
            "noul": {
                "enabled": True,
                "instructions": "Resolved?",
                "criteria": {"true": "Yes", "false": "No"},
            },
            "choice": {"enabled": False},
            "score": {"enabled": False},
        },
    )

    def fail_generate(**kwargs):
        raise AssertionError("LLM should not be called for classification on non-Jev model")

    _patch_llm_generate_response(monkeypatch, fail_generate)

    scores, _ = llm_evaluation.evaluate_with_llm(
        transcription="hello",
        llm_metrics=[metric],
        ai_providers=[],
        organization_id=uuid4(),
        result_id="test",
        db=None,
        evaluator=SimpleNamespace(
            llm_provider="openai",
            llm_model="gpt-4o",
            llm_config=None,
            llm_credential_id=None,
        ),
    )
    assert scores["cl1"]["error"] == "classification_requires_jev_model"


def test_evaluate_classification_kodekloud_uses_response_format(monkeypatch):
    captured: dict = {}

    def fake_generate_response(**kwargs):
        captured.update(kwargs)
        return {
            "text": json.dumps(
                {
                    "noul": {"type": "noul", "noul": 0.88},
                }
            )
        }

    _patch_llm_generate_response(monkeypatch, fake_generate_response)

    metric = _make_metric(
        name="Outcome",
        metric_type="text",
        custom_data_type="classification",
        metric_id="cl1",
        custom_config={
            "noul": {
                "enabled": True,
                "instructions": "Resolved?",
                "criteria": {"true": "Yes", "false": "No"},
            },
            "choice": {"enabled": False},
            "score": {"enabled": False},
        },
    )

    scores, _ = llm_evaluation.evaluate_with_llm(
        transcription="Customer transcript",
        llm_metrics=[metric],
        ai_providers=[],
        organization_id=uuid4(),
        result_id="test",
        db=None,
        evaluator=SimpleNamespace(
            llm_provider="openai",
            llm_model="typesafe/jev-1.13.0",
            llm_config=None,
            llm_credential_id=None,
        ),
    )
    assert captured["messages"] == [{"role": "user", "content": "Customer transcript"}]
    rf = captured["completion_extra"]["response_format"]
    assert rf["type"] == "questions"
    assert rf["questions"]["noul"]["type"] == "noul"
    assert scores["cl1"]["type"] == "classification"
    assert scores["cl1"]["noul_probability"] == 0.88


def test_evaluate_with_llm_uses_jev_payload_for_tev_model(monkeypatch):
    captured: dict = {}

    def fake_generate_response(**kwargs):
        captured["messages"] = kwargs["messages"]
        # Tev1 models answer with a single option letter, not Jev JSON.
        return {"text": "A"}

    _patch_llm_generate_response(monkeypatch, fake_generate_response)

    metric = _make_metric(name="Is Urgent", metric_type="boolean", metric_id="b1")
    scores, _ = llm_evaluation.evaluate_with_llm(
        transcription="Customer needs help ASAP",
        llm_metrics=[metric],
        ai_providers=[],
        organization_id=uuid4(),
        result_id="test",
        db=None,
        evaluator=SimpleNamespace(
            llm_provider="together",
            llm_model="together/Tev1-4B-experimental",
            llm_config=None,
            llm_credential_id=None,
        ),
    )
    user_content = json.loads(captured["messages"][1]["content"])
    assert "Customer needs help ASAP" in user_content["state"]
    assert user_content["question"]
    assert len(user_content["options"]) == 2
    assert scores["b1"]["value"] is True


def test_build_tev1_payload_puts_full_rubric_in_question():
    metric = _make_metric(
        name="Abrupt call closure",
        metric_type="boolean",
        description="Bot terminated the call unprofessionally.",
        metric_id="b1",
    )
    groups = [llm_evaluation.MetricPromptGroup(None, [metric], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    payload, label_to_key = llm_evaluation._build_tev1_payload("transcript text", bindings[0])
    assert payload["state"] == "transcript text"
    assert payload["question"] == "Bot terminated the call unprofessionally."
    assert len(payload["options"]) == 2
    assert label_to_key["A"] == "yes"
    assert label_to_key["B"] == "no"


def test_parse_tev1_response_accepts_single_letter():
    metric = _make_metric(name="Abrupt call closure", metric_type="boolean", metric_id="b1")
    groups = [llm_evaluation.MetricPromptGroup(None, [metric], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    _, label_to_key = llm_evaluation._build_tev1_payload("t", bindings[0])
    parsed = llm_evaluation._parse_tev1_response("A", bindings[0], label_to_key, "test")
    assert parsed == {"type": "noul", "noul": 1.0}


def test_parse_tev1_response_accepts_json_label_and_key():
    parent = _make_metric(name="Bot gibberish", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "single_choice"
    yes = _make_metric(name="Yes", metric_type="boolean", metric_id="c-yes")
    no = _make_metric(name="No", metric_type="boolean", metric_id="c-no")
    groups = [llm_evaluation.MetricPromptGroup(parent, [yes, no], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    parent_binding = next(b for b in bindings if b.kind == "single_choice_parent")
    _, label_to_key = llm_evaluation._build_tev1_payload("t", parent_binding)
    parsed = llm_evaluation._parse_tev1_response(
        '{"label":"B","key":"no"}',
        parent_binding,
        label_to_key,
        "test",
    )
    assert parsed == {"type": "choice", "choice": "no"}


def test_jev_call_specs_emit_one_call_per_flat_metric():
    metrics = [
        _make_metric(name="Metric A", metric_type="boolean", metric_id="a"),
        _make_metric(name="Metric B", metric_type="boolean", metric_id="b"),
    ]
    groups = [llm_evaluation.MetricPromptGroup(None, metrics, None)]
    questions, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    specs = llm_evaluation._jev_call_specs(questions, bindings)
    assert len(specs) == 2
    assert {spec[0] for spec in specs} == {"metric_a", "metric_b"}


def test_parse_jev_call_answer_accepts_flat_boolean_json():
    metric = _make_metric(name="Is Urgent", metric_type="boolean", metric_id="b1")
    groups = [llm_evaluation.MetricPromptGroup(None, [metric], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    binding = bindings[0]
    parsed = llm_evaluation._parse_jev_call_answer(
        '{"is_urgent": true}',
        "is_urgent",
        binding,
        "test",
    )
    assert parsed is not None
    assert parsed["type"] == "noul"
    assert parsed["noul"] == 1.0


def test_parse_jev_call_answer_accepts_judge_style_boolean_payload():
    metric = _make_metric(name="Abrupt call closure", metric_type="boolean", metric_id="b1")
    groups = [llm_evaluation.MetricPromptGroup(None, [metric], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    binding = bindings[0]
    parsed = llm_evaluation._parse_jev_call_answer(
        json.dumps(
            {
                "value": True,
                "type": "boolean",
                "metric_name": "Abrupt call closure",
                "rationale": "Bot ended without closing.",
            }
        ),
        "abrupt_call_closure",
        binding,
        "test",
    )
    assert parsed is not None
    assert parsed["noul"] == 1.0


def test_match_single_choice_key_maps_false_to_no_child():
    parent = _make_metric(name="Bot gibberish", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "single_choice"
    yes = _make_metric(name="Yes", metric_type="boolean", metric_id="c-yes")
    no = _make_metric(name="No", metric_type="boolean", metric_id="c-no")
    groups = [llm_evaluation.MetricPromptGroup(parent, [yes, no], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    parent_binding = next(b for b in bindings if b.kind == "single_choice_parent")
    assert llm_evaluation._match_single_choice_key("false", parent_binding) == "no"
    assert llm_evaluation._match_single_choice_key("No", parent_binding) == "no"


def test_map_jev_single_choice_accepts_false_string_choice():
    parent = _make_metric(name="Bot gibberish", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "single_choice"
    yes = _make_metric(name="Yes", metric_type="boolean", metric_id="c-yes")
    no = _make_metric(name="No", metric_type="boolean", metric_id="c-no")
    groups = [llm_evaluation.MetricPromptGroup(parent, [yes, no], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    parent_binding = next(b for b in bindings if b.kind == "single_choice_parent")
    scores = llm_evaluation._map_jev_single_choice_parent(
        {"bot_gibberish": {"type": "choice", "choice": "false"}},
        parent_binding,
    )
    assert scores["p1"]["value"] == "No"
    assert scores["c-no"]["value"] is True
    assert "error" not in scores["p1"]


def test_expand_number_range_rejects_huge_span_before_allocating_levels():
    metric = _make_metric(
        name="Huge Range",
        custom_data_type="number_range",
        custom_config={"min": 0, "max": 1_000_000, "step": 1},
    )
    assert llm_evaluation._expand_number_range_criteria(metric) is None


def test_map_jev_multi_label_missing_child_answer_is_none_not_false():
    parent = _make_metric(name="Topics", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "multi_label"
    child = _make_metric(name="Billing", metric_type="boolean", metric_id="c1")
    groups = [llm_evaluation.MetricPromptGroup(parent, [child], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    scores = llm_evaluation._map_jev_multi_label_group({}, bindings)
    assert scores["c1"]["value"] is None


def test_jev_call_errors_merge_overwrites_unanswered_multi_label_child():
    parent = _make_metric(name="Topics", metric_type="boolean", metric_id="p1")
    parent.selection_mode = "multi_label"
    child = _make_metric(name="Billing", metric_type="boolean", metric_id="c1")
    groups = [llm_evaluation.MetricPromptGroup(parent, [child], None)]
    _, bindings, _ = llm_evaluation._build_jev_questions_and_bindings(groups)
    metric_scores = llm_evaluation._map_jev_multi_label_group({}, bindings)
    call_errors = {
        "c1": llm_evaluation._unsupported_jev_entry(child, error="jev_answer_parse_failed"),
    }
    for metric_id, entry in call_errors.items():
        existing = metric_scores.get(metric_id)
        if existing is None or existing.get("value") is None or existing.get("error"):
            metric_scores[metric_id] = entry
        elif entry.get("error") and existing.get("value") is False:
            metric_scores[metric_id] = entry
    assert metric_scores["c1"]["error"] == "jev_answer_parse_failed"


def test_evaluate_with_llm_non_jev_model_uses_standard_prompt(monkeypatch):
    captured: dict = {}

    def fake_generate_response(**kwargs):
        captured["messages"] = kwargs["messages"]
        return {"text": '{"is_urgent": true}'}

    _patch_llm_generate_response(monkeypatch, fake_generate_response)

    metric = _make_metric(name="Is Urgent", metric_type="boolean", metric_id="b1")
    llm_evaluation.evaluate_with_llm(
        transcription="hello",
        llm_metrics=[metric],
        ai_providers=[],
        organization_id=uuid4(),
        result_id="test",
        db=None,
        evaluator=SimpleNamespace(
            llm_provider="openai",
            llm_model="gpt-4o",
            llm_config=None,
            llm_credential_id=None,
        ),
    )
    user_content = captured["messages"][1]["content"]
    assert "Metrics to Evaluate" in user_content
    assert '"is_urgent"' in user_content
