"""Tests for top-level metric discovery in the LLM evaluation helper.

These cover the new ``discover_new_metrics`` plumbing on
:func:`build_evaluation_prompt` / :func:`evaluate_with_llm`:

* The discovery instruction block is only emitted when the flag is on
  and lists ``__discovered_metrics__`` as the JSON key the LLM must
  produce.
* :func:`_parse_discovered_metrics` slug-dedupes within a single
  response, drops collisions with the selected metrics, and clamps the
  ``suggested_type`` field to the allowed set
  (``boolean`` / ``rating`` / ``category``).
* A "running" list passed via ``running_discovered_metrics`` lands in
  the prompt with the same REUSE wording as the label flow so the LLM
  can converge on a stable key.

All helpers are pure functions — no DB or LLM is required.
"""

from types import SimpleNamespace
from uuid import uuid4

from app.workers.tasks.helpers import llm_evaluation


def _make_standalone_metric(*, name, description=None, metric_type="boolean"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description=description or f"Evaluate {name}.",
        metric_type=metric_type,
        custom_data_type=None,
        custom_config=None,
        capture_rationale=False,
    )


def _make_parent(*, name="Outcome", selection_mode="multi_label"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description=f"Category covering {name}.",
        selection_mode=selection_mode,
        allow_discovery=False,
        metric_type="boolean",
        custom_data_type=None,
        custom_config=None,
        capture_rationale=False,
    )


# ---------------------------------------------------------------------------
# Prompt rendering: discover_new_metrics flag
# ---------------------------------------------------------------------------


def test_prompt_omits_metric_discovery_block_when_flag_off():
    metrics = [_make_standalone_metric(name="clarity", metric_type="rating")]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=metrics,
        discover_new_metrics=False,
    )
    # Sanity: the reserved key must not leak when the user hasn't
    # opted in, otherwise we'd be silently paying for discovery tokens
    # on every legacy run.
    assert llm_evaluation.DISCOVERED_METRICS_KEY not in prompt
    assert "Discover New Metrics" not in prompt


def test_prompt_includes_metric_discovery_block_when_flag_on():
    metrics = [_make_standalone_metric(name="clarity", metric_type="rating")]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=metrics,
        discover_new_metrics=True,
    )
    assert llm_evaluation.DISCOVERED_METRICS_KEY in prompt
    assert "Discover New Metrics" in prompt
    # The three allowed suggested_type values must show up so the LLM
    # knows the valid enum.
    for label in ("boolean", "rating", "category"):
        assert label in prompt


def test_prompt_metric_discovery_works_in_hierarchical_mode_too():
    """The flag plumbs through the parent-metric branch of the prompt
    builder so a hierarchical run can also discover new top-level
    metrics in addition to sub-labels under its parent."""

    parent = _make_parent(selection_mode="multi_label")
    children = [_make_standalone_metric(name="connected")]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=children,
        parent_metric=parent,
        discover_new_metrics=True,
    )
    assert llm_evaluation.DISCOVERED_METRICS_KEY in prompt


def test_prompt_lists_running_discovered_metrics_with_reuse_wording():
    metrics = [_make_standalone_metric(name="clarity", metric_type="rating")]
    running = [
        {
            "key": "customer_satisfaction",
            "name": "Customer Satisfaction",
            "description": "how happy the customer ended the call",
            "suggested_type": "rating",
            "count": 3,
        }
    ]
    prompt = llm_evaluation.build_evaluation_prompt(
        transcription="hello",
        llm_metrics=metrics,
        discover_new_metrics=True,
        running_discovered_metrics=running,
    )
    assert "REUSE" in prompt
    assert '"customer_satisfaction"' in prompt
    # The suggested_type from the running entry is surfaced so the
    # model has the existing context, not just the key.
    assert "rating" in prompt


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_discovered_metrics_dedupes_and_drops_collisions():
    selected = [
        _make_standalone_metric(name="clarity", metric_type="rating"),
    ]
    raw = {
        llm_evaluation.DISCOVERED_METRICS_KEY: [
            {
                "key": "customer_satisfaction",
                "name": "Customer Satisfaction",
                "description": "...",
                "suggested_type": "rating",
                "rationale": "User: great call!",
            },
            # Dup slug within the same response is dropped.
            {
                "key": "Customer Satisfaction",
                "name": "Dup",
                "suggested_type": "boolean",
            },
            # Collides with an already-selected metric — dropped.
            {"key": "clarity", "name": "Clarity"},
            # Unknown suggested_type clamps to the default boolean.
            {
                "key": "needs_human_handoff",
                "name": "Needs Human Handoff",
                "suggested_type": "weird-value",
            },
        ]
    }

    parsed = llm_evaluation._parse_discovered_metrics(raw, selected)

    keys = [item["key"] for item in parsed]
    assert keys == ["customer_satisfaction", "needs_human_handoff"]
    # The rationale + description on the first entry survive; the
    # default boolean fallback kicks in on the clamped entry.
    sat = next(item for item in parsed if item["key"] == "customer_satisfaction")
    assert sat["suggested_type"] == "rating"
    assert sat["rationale"].startswith("User:")
    handoff = next(item for item in parsed if item["key"] == "needs_human_handoff")
    assert handoff["suggested_type"] == "boolean"


def test_parse_discovered_metrics_returns_empty_when_key_missing():
    selected = [_make_standalone_metric(name="clarity")]
    # No __discovered_metrics__ key at all — must not throw and must
    # not invent entries.
    parsed = llm_evaluation._parse_discovered_metrics({"clarity": 0.8}, selected)
    assert parsed == []


def test_parse_discovered_metrics_handles_non_list_payload():
    """The LLM occasionally returns a dict or string for an array key;
    we treat it like an empty list rather than crashing."""

    selected = [_make_standalone_metric(name="clarity")]
    parsed = llm_evaluation._parse_discovered_metrics(
        {llm_evaluation.DISCOVERED_METRICS_KEY: "not a list"},
        selected,
    )
    assert parsed == []
