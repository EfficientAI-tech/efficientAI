"""Tests for the hierarchical metric handling in ``llm_evaluation``.

These exercise the prompt builder, system message, and the score-mapping
helper for parent/child metric groups. The helpers are pure functions so
no DB or LLM is required.
"""

from types import SimpleNamespace
from uuid import uuid4

from app.workers.tasks.helpers import llm_evaluation


def _make_parent(
    *,
    name="Call Outcome",
    selection_mode="single_choice",
    allow_discovery=False,
):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description=f"Category covering {name}.",
        selection_mode=selection_mode,
        allow_discovery=allow_discovery,
        metric_type="boolean",
        custom_data_type=None,
        custom_config=None,
        capture_rationale=False,
    )


def _make_child(*, name, description=None):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description=description or f"True iff {name} happened.",
        metric_type="boolean",
        custom_data_type=None,
        custom_config=None,
        capture_rationale=False,
    )


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_prompt_includes_single_choice_invariant():
    parent = _make_parent(selection_mode="single_choice")
    children = [
        _make_child(name="happy_completion"),
        _make_child(name="angry_hangup"),
    ]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi there",
        llm_metrics=children,
        parent_metric=parent,
    )
    # The model must be told to pick exactly one and that any other
    # configuration is invalid; this is the core consistency contract.
    assert "SINGLE-CHOICE" in prompt
    assert "EXACTLY ONE" in prompt
    # Both children render in the body with their generated keys.
    assert '"happy_completion"' in prompt
    assert '"angry_hangup"' in prompt
    # The sequence array is requested unconditionally so we can render
    # the flow chart.
    assert "call_outcome__sequence" in prompt


def test_prompt_includes_multi_label_consistency_warning():
    parent = _make_parent(selection_mode="multi_label")
    children = [
        _make_child(name="connected"),
        _make_child(name="hung_up"),
    ]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi",
        llm_metrics=children,
        parent_metric=parent,
    )
    assert "MULTI-LABEL" in prompt
    # The prompt must warn against marking contradictory siblings both
    # true — that's the user's hard requirement.
    assert "contradictory" in prompt.lower()
    assert "LOGICAL CONSISTENCY" in prompt


# ---------------------------------------------------------------------------
# _map_evaluation_to_metrics with parent_metric
# ---------------------------------------------------------------------------


def test_map_single_choice_uses_chosen_key_to_repair_zero_trues():
    parent = _make_parent(selection_mode="single_choice")
    happy = _make_child(name="happy_completion")
    angry = _make_child(name="angry_hangup")
    confused = _make_child(name="didnt_understand")
    children = [happy, angry, confused]

    # The LLM forgot to flip any boolean to true but did emit the
    # parent-level "chosen child" field — the repair logic must use
    # that to coerce the booleans into the only-one-true invariant.
    evaluation_data = {
        "happy_completion": False,
        "angry_hangup": False,
        "didnt_understand": False,
        "call_outcome": "angry_hangup",
        "call_outcome__sequence": ["angry_hangup"],
    }

    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, children, parent_metric=parent
    )

    assert scores[str(happy.id)]["value"] is False
    assert scores[str(angry.id)]["value"] is True
    assert scores[str(confused.id)]["value"] is False
    parent_entry = scores[str(parent.id)]
    assert parent_entry["chosen_child_name"] == "angry_hangup"
    assert parent_entry["value"] == "angry_hangup"
    assert parent_entry["sequence"] == ["angry_hangup"]


def test_map_single_choice_repairs_multiple_trues():
    parent = _make_parent(selection_mode="single_choice")
    happy = _make_child(name="happy_completion")
    angry = _make_child(name="angry_hangup")
    evaluation_data = {
        "happy_completion": True,
        "angry_hangup": True,
        # No parent-level tiebreaker; the helper must keep the FIRST
        # true and flip the rest.
        "call_outcome__sequence": ["happy_completion"],
    }

    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, [happy, angry], parent_metric=parent
    )

    assert scores[str(happy.id)]["value"] is True
    assert scores[str(angry.id)]["value"] is False


def test_map_single_choice_flags_invariant_violation_when_no_repair_possible():
    parent = _make_parent(selection_mode="single_choice")
    happy = _make_child(name="happy_completion")
    angry = _make_child(name="angry_hangup")
    evaluation_data = {
        "happy_completion": False,
        "angry_hangup": False,
        # No chosen child, no sequence -> nothing to recover from.
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, [happy, angry], parent_metric=parent
    )
    parent_entry = scores[str(parent.id)]
    assert parent_entry["value"] is None
    assert parent_entry["error"] == "single_choice_invariant_violated"


def test_map_multi_label_passes_booleans_through_and_auto_promotes_sequence():
    parent = _make_parent(selection_mode="multi_label", name="Call Flow")
    a = _make_child(name="connected")
    b = _make_child(name="answered")
    c = _make_child(name="hung_up")
    # The LLM only marked one bool true but listed all three in the
    # sequence array — multi_label mode auto-promotes them so the per-
    # call flow chart matches the booleans.
    evaluation_data = {
        "connected": True,
        "answered": False,
        "hung_up": False,
        "call_flow__sequence": ["connected", "answered", "hung_up"],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, [a, b, c], parent_metric=parent
    )
    assert scores[str(a.id)]["value"] is True
    assert scores[str(b.id)]["value"] is True
    assert scores[str(c.id)]["value"] is True
    parent_entry = scores[str(parent.id)]
    assert parent_entry["selection_mode"] == "multi_label"
    assert parent_entry["sequence"] == ["connected", "answered", "hung_up"]
    assert set(parent_entry["selected_child_names"]) == {
        "connected",
        "answered",
        "hung_up",
    }


def test_map_filters_unknown_sequence_keys():
    parent = _make_parent(selection_mode="multi_label", name="Flow")
    a = _make_child(name="connected")
    b = _make_child(name="hung_up")
    evaluation_data = {
        "connected": True,
        "hung_up": True,
        # Unknown keys must be silently dropped from the sequence so
        # the flow chart never tries to render a missing node.
        "flow__sequence": ["connected", "bogus_label", "hung_up"],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, [a, b], parent_metric=parent
    )
    assert scores[str(parent.id)]["sequence"] == ["connected", "hung_up"]


# ---------------------------------------------------------------------------
# Discovery prompt + parsing
# ---------------------------------------------------------------------------


def test_prompt_omits_discovery_block_when_allow_discovery_is_false():
    parent = _make_parent(selection_mode="multi_label", allow_discovery=False)
    children = [_make_child(name="connected")]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi",
        llm_metrics=children,
        parent_metric=parent,
    )
    assert "DISCOVERY ENABLED" not in prompt
    assert "__discovered" not in prompt


def test_prompt_includes_discovery_block_for_any_parent_with_allow_discovery():
    """``allow_discovery`` works on both single_choice and multi_label
    parents now. For single_choice the prompt explicitly clarifies that
    discovered labels are supplemental — the chosen child still has to
    come from the predefined children, so the exactly-one-true
    invariant is preserved.
    """
    sc = _make_parent(
        selection_mode="single_choice",
        allow_discovery=True,
        name="Call Outcome",
    )
    ml = _make_parent(
        selection_mode="multi_label",
        allow_discovery=True,
        name="Call Flow",
    )
    children = [_make_child(name="connected"), _make_child(name="hung_up")]

    sc_prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi",
        llm_metrics=children,
        parent_metric=sc,
    )
    ml_prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi",
        llm_metrics=children,
        parent_metric=ml,
    )

    # Both parents now invite discovery.
    assert "DISCOVERY ENABLED" in sc_prompt
    assert "DISCOVERY ENABLED" in ml_prompt
    assert "call_outcome__discovered" in sc_prompt
    assert "call_flow__discovered" in ml_prompt
    # Single-choice prompt must reinforce the supplemental rule so the
    # LLM does not silently violate the exactly-one-true invariant by
    # treating a discovered entry as the chosen child.
    assert "SUPPLEMENTAL" in sc_prompt
    assert "SUPPLEMENTAL" not in ml_prompt


def test_prompt_lists_running_discovered_labels_with_reuse_wording():
    parent = _make_parent(selection_mode="multi_label", allow_discovery=True)
    children = [_make_child(name="connected")]
    running = [
        {
            "key": "customer_on_hold",
            "name": "Customer put on hold",
            "description": "agent placed the caller on hold",
            "count": 3,
        }
    ]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hi",
        llm_metrics=children,
        parent_metric=parent,
        running_discovered=running,
    )
    assert "REUSE" in prompt
    assert '"customer_on_hold"' in prompt


def test_map_parses_discovered_labels_and_lets_them_flow_through_sequence():
    parent = _make_parent(
        selection_mode="multi_label",
        allow_discovery=True,
        name="Call Outcome",
    )
    a = _make_child(name="connected")
    b = _make_child(name="hung_up")
    evaluation_data = {
        "connected": True,
        "hung_up": False,
        "call_outcome__sequence": [
            "connected",
            "customer_on_hold",
            "hung_up",
        ],
        "call_outcome__discovered": [
            {
                "key": "Customer On Hold",
                "name": "Customer put on hold",
                "description": "caller waited while agent paused",
                "rationale": "Agent: please hold for a moment.",
            },
            # Duplicate slug in-response must be deduped.
            {
                "key": "customer_on_hold",
                "name": "Dup",
                "description": "",
            },
            # Collision with an existing child slug is dropped — the
            # model should have just set the boolean true instead.
            {"key": "connected", "name": "Connected"},
        ],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, [a, b], parent_metric=parent
    )
    parent_entry = scores[str(parent.id)]
    assert parent_entry["sequence"] == [
        "connected",
        "customer_on_hold",
        "hung_up",
    ]
    discovered = parent_entry["discovered_labels"]
    assert len(discovered) == 1
    assert discovered[0]["key"] == "customer_on_hold"
    assert discovered[0]["name"] == "Customer put on hold"
    assert discovered[0]["rationale"].startswith("Agent: please hold")


def test_map_keeps_discovered_labels_supplemental_for_single_choice_parent():
    # Single_choice parents with ``allow_discovery=True`` keep the
    # exactly-one-true invariant via the *chosen child* still being one
    # of the predefined children — discovered labels are surfaced as
    # supplemental info (so users can promote them later) but never
    # replace the chosen child. This mirrors the per-mode prompt
    # instruction added in ``_render_parent_block``.
    parent = _make_parent(
        selection_mode="single_choice",
        allow_discovery=True,
        name="Call Outcome",
    )
    a = _make_child(name="connected")
    evaluation_data = {
        "connected": True,
        "call_outcome": "connected",
        "call_outcome__discovered": [{"key": "x", "name": "X"}],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, [a], parent_metric=parent
    )
    parent_entry = scores[str(parent.id)]
    # The chosen child is still locked to a predefined option — the
    # invariant the old test was guarding is preserved here, just at
    # the choice level rather than by suppressing discovery wholesale.
    assert parent_entry["chosen_child_name"] == "connected"
    # Discovered labels survive as supplemental info.
    discovered = parent_entry.get("discovered_labels") or []
    assert [d["key"] for d in discovered] == ["x"]
    assert discovered[0]["name"] == "X"


def test_map_drops_discovered_labels_when_allow_discovery_false():
    # Discovery is gated entirely by ``allow_discovery`` on the parent.
    # Even on a single_choice parent, when the flag is off any
    # ``__discovered`` payload from a rebellious model must be
    # ignored so users don't start seeing labels they never opted into.
    parent = _make_parent(
        selection_mode="single_choice",
        allow_discovery=False,
        name="Call Outcome",
    )
    a = _make_child(name="connected")
    evaluation_data = {
        "connected": True,
        "call_outcome": "connected",
        "call_outcome__discovered": [{"key": "x", "name": "X"}],
    }
    scores = llm_evaluation._map_evaluation_to_metrics(
        evaluation_data, [a], parent_metric=parent
    )
    assert "discovered_labels" not in scores[str(parent.id)]
