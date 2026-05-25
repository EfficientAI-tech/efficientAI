"""LLM-based evaluation: prompt building and response parsing."""

import json
import re
import time
from typing import Any, Optional
from uuid import UUID

from loguru import logger

from app.models.database import ModelProvider

from .json_utils import repair_truncated_json
from .score_utils import (
    provider_matches,
    extract_score,
    find_matching_key,
    get_metric_type_value,
    normalize_score,
)


def _get_custom_data_type(metric) -> Optional[str]:
    """Return the lowercased custom_data_type ('enum'/'number_range'/'boolean') or None."""
    raw = getattr(metric, "custom_data_type", None)
    if not raw:
        return None
    if hasattr(raw, "value"):
        raw = raw.value
    return str(raw).strip().lower() or None


def _get_enum_options(metric) -> list[str]:
    """Return the list of allowed enum option labels for an enum custom metric."""
    cfg = getattr(metric, "custom_config", None) or {}
    options = cfg.get("options") if isinstance(cfg, dict) else None
    if not isinstance(options, list):
        return []
    return [str(o).strip() for o in options if str(o).strip()]


def _get_number_range(metric) -> Optional[dict]:
    """Return {min, max, step} for a number_range custom metric, if configured."""
    cfg = getattr(metric, "custom_config", None) or {}
    if not isinstance(cfg, dict):
        return None
    if "min" not in cfg and "max" not in cfg:
        return None
    return {
        "min": cfg.get("min"),
        "max": cfg.get("max"),
        "step": cfg.get("step"),
    }


def _coerce_text_value(raw: Any) -> Optional[str]:
    """Coerce an LLM-returned value for a text/summary metric into a string.

    Accepts the well-formed case (a plain string) and tolerates a few common
    drift patterns: dict wrappers like ``{"value": "..."}``, numeric/bool
    scalars, and short lists of strings (joined with spaces). Returns ``None``
    when no usable text is found so the UI can show an explicit empty state.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        stripped = raw.strip()
        return stripped or None
    if isinstance(raw, (int, float, bool)):
        return str(raw)
    if isinstance(raw, dict):
        for k in ("value", "text", "summary", "answer", "content"):
            if k in raw and raw[k] is not None:
                return _coerce_text_value(raw[k])
        return None
    if isinstance(raw, list):
        parts = [p for p in (_coerce_text_value(item) for item in raw) if p]
        return " ".join(parts) or None
    try:
        text = str(raw).strip()
    except Exception:  # noqa: BLE001
        return None
    return text or None


def _wants_rationale(metric) -> bool:
    """Return True when the metric is configured to capture an LLM rationale."""
    return bool(getattr(metric, "capture_rationale", False))


def _rationale_key(metric_key: str) -> str:
    """Companion key emitted by the LLM next to the metric value."""
    return f"{metric_key}_rationale"


def _normalize_enum_value(raw: Any, options: list[str]) -> Optional[str]:
    """Map an LLM-returned value to the canonical option string (case-insensitive).

    Returns None if no match — the caller will record the metric as unscored.
    """
    if raw is None or not options:
        return None
    if isinstance(raw, dict):
        for k in ("value", "label", "choice", "answer"):
            if k in raw:
                raw = raw[k]
                break
    text = str(raw).strip()
    if not text:
        return None
    text_lower = text.lower()
    for opt in options:
        if opt.lower() == text_lower:
            return opt
    # Lenient fallback: substring containment in either direction.
    for opt in options:
        if opt.lower() in text_lower or text_lower in opt.lower():
            return opt
    return None


def _parent_key(parent_metric) -> str:
    """Stable LLM JSON key derived from the parent metric's name."""
    return (parent_metric.name or "parent").lower().replace(" ", "_")


def _sequence_key(parent_metric) -> str:
    """LLM JSON key holding the temporal flow of children for a parent.

    The model returns this alongside the per-child booleans so we can
    render a per-call React Flow chart and aggregate into a Sankey-style
    diagram on the evaluation overview.
    """
    return f"{_parent_key(parent_metric)}__sequence"


def _discovered_key(parent_metric) -> str:
    """LLM JSON key carrying candidate sub-labels discovered for a parent.

    Emitted/parsed when the parent has ``allow_discovery=True`` (works
    for both single_choice and multi_label parents). Discovered keys
    can also appear in the sequence array so they show up in the flow
    chart.
    """
    return f"{_parent_key(parent_metric)}__discovered"


def _discovery_enabled(parent_metric) -> bool:
    """True on any parent metric that opted into discovery.

    Both single_choice and multi_label parents can carry
    ``allow_discovery=True``; the prompt instructions vary slightly
    between modes so the single-choice "exactly one true" invariant
    stays intact (discovered labels are supplemental for single_choice).
    """
    if parent_metric is None:
        return False
    mode = (getattr(parent_metric, "selection_mode", None) or "").lower()
    return (
        bool(getattr(parent_metric, "allow_discovery", False))
        and mode in {"single_choice", "multi_label"}
    )


def _slug_label(value) -> str:
    """Lowercase + whitespace-collapse + underscore-join for label keys.

    Mirrors the dedup convention used by the routes layer so a label
    discovered as "Customer on Hold" and reused later as "customer on
    hold" collapse to the same key.
    """
    if value is None:
        return ""
    return "_".join(str(value).strip().lower().split())


# Reserved JSON key carrying top-level metric discoveries on a single
# row's LLM response. Uses leading + trailing ``__`` so it can't
# collide with a real metric name (slugify strips the underscores).
# Mirrors :func:`_discovered_key` for parent → child label discovery
# but lives at the response root, not nested under a parent key.
DISCOVERED_METRICS_KEY = "__discovered_metrics__"

# Allowed values for the LLM-suggested type on a discovered top-level
# metric. Kept in sync with ``DiscoveredMetricSuggestedType`` in
# ``app/models/schemas.py``. ``category`` promotes to a ``multi_label``
# parent with no children (the user adds children later).
_DISCOVERED_METRIC_TYPES = ("boolean", "rating", "category")


def _render_discovered_metrics_block(
    running_discovered_metrics: list | None,
) -> str:
    """Render the top-level metric-discovery instruction block.

    Inserted into the prompt once per row when the user opted into
    ``discover_new_metrics`` on the evaluation. Asks the LLM to surface
    an array of brand-new metric candidates it noticed in the
    transcript that the explicitly-selected metrics do NOT already
    cover. ``running_discovered_metrics`` lists candidates already
    discovered in this evaluation so the model reuses keys instead of
    re-inventing near-duplicates (same pattern as label discovery).
    """

    block = (
        f'\n\n## Discover New Metrics (REQUIRED top-level array '
        f'`{DISCOVERED_METRICS_KEY}`)\n'
        "DISCOVERY ENABLED for this run. In addition to scoring the "
        "metrics above, surface brand-new TOP-LEVEL metrics you "
        "noticed in this transcript that the listed metrics do NOT "
        "already capture (e.g. customer_satisfaction, agent_followup_promised, "
        "needs_human_handoff). Aim for 0-5 entries per call; only "
        "return [] when every interesting behaviour is already covered.\n"
        f'- "{DISCOVERED_METRICS_KEY}" (array of objects): Each entry MUST be '
        '{"key": "snake_case_metric", "name": "Human Readable Name", '
        '"description": "one short sentence describing what it measures", '
        '"suggested_type": "boolean" | "rating" | "category", '
        '"rationale": "verbatim transcript line that motivated this metric"}. '
        "Use ``boolean`` for yes/no behaviours, ``rating`` for 0-1 quality "
        "judgements, and ``category`` for groupings that will need their "
        "own set of sub-labels later. Do NOT propose a metric that "
        "duplicates one of the metrics listed earlier in this prompt.\n"
    )
    if running_discovered_metrics:
        block += (
            "\nPreviously discovered metrics in this evaluation — "
            "REUSE the existing key (and exact name) if the metric you'd "
            "propose is essentially identical. Reuse only applies to "
            "genuine matches — keep emitting NEW entries for metrics "
            "not in this list:\n"
        )
        for entry in running_discovered_metrics:
            key = entry.get("key") or ""
            name = entry.get("name") or key
            desc = entry.get("description")
            stype = entry.get("suggested_type") or "boolean"
            if desc:
                block += f'- "{key}" ({name}, {stype}) — {desc}\n'
            else:
                block += f'- "{key}" ({name}, {stype})\n'
    return block


def _parse_discovered_metrics(
    evaluation_data: dict, llm_metrics: list
) -> list[dict[str, Any]]:
    """Extract + validate the LLM's top-level metric discoveries.

    Reads ``evaluation_data[DISCOVERED_METRICS_KEY]``, slugifies keys,
    drops entries that collide with the already-selected metric names
    (the LLM is supposed to surface NEW metrics) or duplicate each
    other within the same response, and clamps ``suggested_type`` to
    the allowed set. Returns a list of dicts shaped for persistence in
    ``metric_scores[DISCOVERED_METRICS_KEY]`` — exactly what the
    aggregator and ``DiscoveredMetricItem`` schema consume.
    """

    raw = evaluation_data.get(DISCOVERED_METRICS_KEY)
    if raw is None:
        matched = find_matching_key(
            DISCOVERED_METRICS_KEY, list(evaluation_data.keys())
        )
        if matched:
            raw = evaluation_data.get(matched)
    if not isinstance(raw, list):
        return []

    existing_slugs: set[str] = set()
    for metric in llm_metrics:
        existing_slugs.add(_slug_label(getattr(metric, "name", None)))

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        raw_key = entry.get("key") or entry.get("name")
        slug = _slug_label(raw_key)
        if not slug:
            continue
        # Drop collisions with already-selected metrics (the prompt
        # asked for NEW metrics, not restatements of the selected
        # ones) and dedup within the same response.
        if slug in existing_slugs or slug in seen:
            continue
        seen.add(slug)

        name_val = (entry.get("name") or "").strip() or slug.replace(
            "_", " "
        )
        description_val = _coerce_text_value(entry.get("description"))
        rationale_val = _coerce_text_value(entry.get("rationale"))
        raw_type = str(entry.get("suggested_type") or "").strip().lower()
        if raw_type not in _DISCOVERED_METRIC_TYPES:
            raw_type = "boolean"

        payload: dict[str, Any] = {
            "key": slug,
            "name": name_val,
            "suggested_type": raw_type,
        }
        if description_val:
            payload["description"] = description_val
        if rationale_val:
            payload["rationale"] = rationale_val
        out.append(payload)

    return out


def _render_parent_block(
    parent_metric,
    children: list,
    running_discovered: list | None = None,
) -> str:
    """Build the per-parent prompt section for a hierarchical group.

    For ``single_choice`` parents the model is told that EXACTLY ONE
    child must be true. For ``multi_label`` parents the children are
    independent yes/no but the prompt explicitly warns the model to
    avoid contradictory pairs (the user's "A and not B" requirement).
    Both modes ask for a ``<parent_key>__sequence`` array so we can
    visualize the LLM-inferred flow through the labels.
    """
    parent_key = _parent_key(parent_metric)
    sequence_key = _sequence_key(parent_metric)
    selection_mode = (parent_metric.selection_mode or "multi_label").lower()
    parent_desc = parent_metric.description or (
        f"Category covering {parent_metric.name}"
    )

    block = (
        f"\n\n### Category: {parent_metric.name}\n"
        f"Context: {parent_desc}\n"
    )
    if selection_mode == "single_choice":
        block += (
            "Mode: SINGLE-CHOICE. Pick EXACTLY ONE child label below that "
            "best describes what happened in this call. Output a JSON "
            f'field `{parent_key}` set to the chosen child key, AND set '
            "every child key to true/false such that EXACTLY ONE is true. "
            "Any other configuration is invalid.\n"
        )
    else:
        block += (
            "Mode: MULTI-LABEL. Set each child key to true/false "
            "INDEPENDENTLY. Some siblings are logically contradictory "
            "(e.g., 'customer_completed_survey' and 'angry_hangup' cannot "
            "both be true). MAINTAIN LOGICAL CONSISTENCY: do not mark "
            "contradictory labels both true at the same time.\n"
        )

    block += "Children (set each true/false):\n"
    for child in children:
        child_key = child.name.lower().replace(" ", "_")
        child_desc = child.description or f"Detect {child.name}"
        block += f'- "{child_key}" (true/false): {child_desc}\n'
        # When the user attached an illustrative example to this label
        # (via the Categorization Labels editor's "Example (Optional)"
        # field) we surface it on its own indented line so the LLM has
        # a concrete "what does this look like in a transcript?" anchor
        # alongside the definition.
        child_example = (getattr(child, "example", None) or "").strip()
        if child_example:
            block += f"  Example: {child_example}\n"

    block += (
        f'- "{sequence_key}" (array of strings, ordered): the child keys '
        "in the order they occurred during the call. Include ONLY children "
        "that actually happened. For single-choice, this may be a single "
        "element (the chosen child) or the path leading up to it.\n"
    )

    # Parent-level rationale: a single free-form string explaining the
    # overall categorization (which label(s) were picked and why). The
    # LLM is asked for one rationale per parent — never per child — so
    # the table can render exactly one "<Parent> - LLM Rationale" cell.
    if _wants_rationale(parent_metric):
        parent_rationale_key = _rationale_key(parent_key)
        if selection_mode == "single_choice":
            block += (
                f'- "{parent_rationale_key}" (free-form text, 1-2 concise '
                f'sentences explaining why "{parent_key}" was set to the '
                "chosen child key): Cite a transcript line when possible.\n"
            )
        else:
            block += (
                f'- "{parent_rationale_key}" (free-form text, 1-2 concise '
                f"sentences explaining which children were selected and "
                "why): Cite a transcript line when possible.\n"
            )

    # Discovery section: emitted on any parent (single_choice or
    # multi_label) that opted in via ``allow_discovery``. The wording
    # is intentionally assertive ("list EVERY distinct behavior", "aim
    # for 2-5 entries"). When a user has explicitly opted into
    # discovery they want the LLM to expand their taxonomy, so the
    # default failure mode should be over-discovery (which they can
    # merge / discard via the panel) rather than under-discovery
    # (silently empty arrays that look like discovery is broken).
    #
    # Important: for single_choice parents the discovered labels are
    # SUPPLEMENTAL — they do not break the "exactly one child true"
    # invariant. The chosen child still has to come from the predefined
    # children list; discovered entries surface as analytics-only
    # candidates the user can later promote into real children.
    if _discovery_enabled(parent_metric):
        discovered_key = _discovered_key(parent_metric)
        block += (
            f'- "{discovered_key}" (array of objects, REQUIRED for '
            "non-trivial calls): DISCOVERY ENABLED. List EVERY distinct "
            "behaviour, intent, topic, or outcome demonstrated by the "
            "agent or user that is NOT already covered by the listed "
            "children above. Examples of things to surface when present: "
            "price/budget discussion, product/feature questions, "
            "scheduling (test drive, callback, appointment), payment / "
            "financing / EMI, complaints or objections, escalation or "
            "human-handoff, off-topic chatter, repeat caller context, "
            "confirmation / acknowledgement patterns, etc. Aim for 2-5 "
            "entries on a typical call; only return [] when the call is "
            "trivially short (a few turns) or every behaviour genuinely "
            "fits an existing child. Each entry must be an object: "
            '{"key": "snake_case_label", "name": "Human Readable", '
            '"description": "one short sentence", '
            '"rationale": "exact transcript line"}. '
            "Discovered keys may also appear in the sequence array.\n"
        )
        if selection_mode == "single_choice":
            block += (
                "  IMPORTANT for single-choice mode: discovered entries "
                "are SUPPLEMENTAL — they do NOT replace the chosen "
                "child. You MUST still mark exactly one of the "
                "predefined children above as true and reflect that "
                "choice in the parent_key field. Discovered labels are "
                "captured separately for the user to promote into real "
                "children later.\n"
            )
        if running_discovered:
            block += (
                "\nPreviously discovered labels in this evaluation — "
                "REUSE the existing key (and exact name) if the outcome "
                "matches; do NOT invent a near-duplicate. Reuse only "
                "applies to genuine matches — keep emitting NEW entries "
                "for behaviours not in this list:\n"
            )
            for entry in running_discovered:
                key = entry.get("key") or ""
                name = entry.get("name") or key
                desc = entry.get("description")
                if desc:
                    block += f'- "{key}" ({name}) — {desc}\n'
                else:
                    block += f'- "{key}" ({name})\n'
    return block


def build_evaluation_prompt(
    transcription: str,
    llm_metrics: list,
    evaluator=None,
    agent=None,
    persona=None,
    scenario=None,
    parent_metric=None,
    running_discovered: list | None = None,
    extra_context: str | None = None,
    all_columns_block: str | None = None,
    comparison_pair: tuple[str, str] | None = None,
    discover_new_metrics: bool = False,
    running_discovered_metrics: list | None = None,
) -> str:
    """
    Build the evaluation prompt for LLM-based metric evaluation.

    Args:
        transcription: The conversation transcript
        llm_metrics: List of Metric objects to evaluate
        evaluator: Optional Evaluator with custom_prompt
        agent: Optional Agent for context
        persona: Optional Persona for language info
        scenario: Optional Scenario for context
        parent_metric: Optional parent Metric when ``llm_metrics`` are all
            children of the same parent. When set, the metrics block is
            rendered as a single hierarchical category instead of N
            independent metric lines. May be combined with
            ``comparison_pair`` for categorisation metrics whose prompt
            asks the LLM to compare the production and diarised
            transcripts.
        extra_context: Legacy: pre-formatted block injected as a
            "Context Inputs" section. Kept on the signature for
            backwards-compatibility with non-call-import callers (e.g.
            scenario evaluator) that may still use it. The call-import
            worker now uses ``all_columns_block`` instead.
        all_columns_block: Optional pre-formatted block of EVERY CSV
            column from a call-import row. When set, rendered as a
            "## Imported Columns" section below ``context_block`` so the
            LLM has full row context for every metric without needing a
            per-metric column allow-list.
        comparison_pair: Optional ``(production, diarised)`` transcript
            pair. When set, the single ``## Conversation Transcript``
            section is replaced by a labeled ``## Transcripts to
            Compare`` block with ``### Production Transcript`` and
            ``### Diarised Transcript`` subsections, and ``transcription``
            is ignored. Used by transcript-compare judge metrics
            (``Metric.compare_transcripts=True`` *or* metrics whose
            description references the production transcript — see
            ``_metric_text_references_production`` in
            ``evaluate_call_import_row``). Can be combined with
            ``parent_metric`` so a categorisation parent can score
            against the pair.

    Returns:
        Complete evaluation prompt string
    """
    is_custom_evaluator = evaluator and (
        bool(evaluator.custom_prompt)
        or bool(getattr(evaluator, "metric_ids", None))
        # Some call-import code paths pass a lightweight SimpleNamespace
        # carrying only provider/model overrides (no ``agent_id`` field).
        # Treat missing ``agent_id`` exactly like ``None`` so prompt
        # construction stays robust across evaluator shapes.
        or (getattr(evaluator, "agent_id", None) is None)
    )
    is_comparison = comparison_pair is not None

    context_block = ""
    if extra_context and extra_context.strip():
        context_block = (
            "\n## Context Inputs\n"
            "The following named values come from the source row's imported "
            "columns. Treat them as authoritative inputs for the metrics below.\n\n"
            f"{extra_context.strip()}\n"
        )

    if all_columns_block and all_columns_block.strip():
        # Rendered AFTER ``context_block`` so the explicit per-metric
        # context wins precedence when both are present (today only the
        # call-import worker sets ``all_columns_block`` and it doesn't
        # set ``extra_context``, but the ordering keeps the legacy
        # contract intact for any other caller).
        context_block += (
            "\n## Imported Columns\n"
            "The following are every column from the source CSV row, in upload "
            "order. Treat them as supporting context; the metric is still scored "
            "against the transcript(s) above unless the metric description "
            "explicitly asks otherwise.\n\n"
            f"{all_columns_block.strip()}\n"
        )

    # Build the transcript section once so the custom-evaluator and
    # default branches stay in sync. For comparison metrics we emit a
    # labeled pair instead of a single transcript and include a
    # one-line framing so the LLM knows the two texts describe the
    # SAME call (production = CSV-supplied, diarised = STT output).
    if is_comparison:
        production_text, diarised_text = comparison_pair
        production_text = (production_text or "").strip() or "(empty)"
        diarised_text = (diarised_text or "").strip() or "(empty)"
        transcript_section = (
            "## Transcripts to Compare\n"
            "You are comparing two transcripts of the SAME call. The "
            "PRODUCTION transcript was supplied with the call import "
            "(typically the customer's existing system). The DIARISED "
            "transcript was generated by our STT / diarisation worker. "
            "Score the metrics below based on the RELATIONSHIP between "
            "the two transcripts (agreement, fidelity, missing turns, "
            "speaker-attribution differences, etc.) rather than the "
            "content of either one alone.\n\n"
            "### Production Transcript\n"
            f"{production_text}\n\n"
            "### Diarised Transcript\n"
            f"{diarised_text}\n"
        )
    else:
        transcript_section = (
            "## Conversation Transcript\n"
            f"{transcription}\n"
        )

    if is_custom_evaluator:
        has_prompt = bool(evaluator.custom_prompt and evaluator.custom_prompt.strip())
        if has_prompt:
            prompt = f"""You are evaluating a conversation transcript against the agent's system prompt. You MUST evaluate ONLY the specific metrics listed below and use the EXACT metric keys provided.

## Agent System Prompt
The following is the system prompt / instructions that the agent was configured with. Use this to understand the agent's goals, rules, and expected behavior when evaluating the conversation.

{evaluator.custom_prompt}
{context_block}
{transcript_section}
## Metrics to Evaluate (use EXACT keys below)
"""
        else:
            prompt = f"""You are evaluating a conversation transcript against the listed metrics. You MUST evaluate ONLY the specific metrics listed below and use the EXACT metric keys provided. Base your scoring on the transcript and each metric's description.
{context_block}
{transcript_section}
## Metrics to Evaluate (use EXACT keys below)
"""
    else:
        call_type_val = (
            (agent.call_type.value if hasattr(agent.call_type, "value") else agent.call_type)
            if agent and agent.call_type
            else "conversations"
        )
        language_val = "N/A"
        if persona:
            if hasattr(persona, "tts_voice_name") and persona.tts_voice_name:
                language_val = f"{persona.tts_voice_name} ({persona.tts_provider or 'unknown'})"
            elif hasattr(persona, "language") and persona.language:
                language_val = persona.language.value if hasattr(persona.language, "value") else persona.language
        agent_objective = (
            agent.description
            if agent and agent.description
            else f"The agent's objective is to handle {call_type_val}."
        )
        scenario_context = scenario.description if scenario and scenario.description else ""
        scenario_goals = scenario.required_info if scenario and scenario.required_info else {}

        prompt = f"""You are evaluating a conversation transcript. You MUST evaluate ONLY the specific metrics listed below and use the EXACT metric keys provided.

## Agent Information
- Name: {agent.name if agent else 'Unknown'}
- Objective/Purpose: {agent_objective}
- Call Type: {call_type_val if agent and agent.call_type else 'N/A'}
- Language: {language_val}

## Scenario Information
- Name: {scenario.name if scenario else 'Unknown'}
- Description: {scenario_context}
- Required Information: {json.dumps(scenario_goals) if scenario_goals else 'N/A'}
{context_block}
{transcript_section}
## Metrics to Evaluate (use EXACT keys below)
"""

    if parent_metric is not None:
        # Hierarchical mode: render ONE category block with the children
        # plus a sequence array. Falls through to the format
        # instructions which understand the parent grouping. When
        # ``comparison_pair`` is also set (categorisation parent whose
        # prompt references the production / diarised transcript pair),
        # the labeled transcript pair was already rendered as the
        # ``transcript_section`` above so the category block just
        # follows it.
        prompt += _render_parent_block(
            parent_metric,
            llm_metrics,
            running_discovered=running_discovered,
        )
        if discover_new_metrics:
            prompt += _render_discovered_metrics_block(
                running_discovered_metrics
            )
        prompt += _build_response_format_instructions(
            llm_metrics,
            parent_metric=parent_metric,
            discover_new_metrics=discover_new_metrics,
        )
        return prompt

    for metric in llm_metrics:
        metric_key = metric.name.lower().replace(" ", "_")
        metric_desc = metric.description or f"Evaluate {metric.name}"
        m_type = get_metric_type_value(metric)
        custom_type = _get_custom_data_type(metric)

        # Text metrics are unstructured by definition; ignore any stale
        # ``custom_data_type`` (e.g. left over from when the metric used to be
        # an enum) and ask the LLM for a free-form string. Rationale doesn't
        # apply to text metrics (they are themselves free-form prose), so we
        # short-circuit the rest of the loop body.
        if m_type == "text":
            prompt += (
                f'\n- "{metric_key}" (free-form text, 1-3 concise sentences, '
                f'plain string): {metric_desc}'
            )
            continue

        # Emit the metric line. We deliberately do NOT ``continue`` after
        # the enum / number_range branches — falling through lets the
        # rationale companion block at the end of the loop run for those
        # metric shapes too.
        line_added = False
        if custom_type == "enum":
            options = _get_enum_options(metric)
            if options:
                opts_str = ", ".join(f'"{o}"' for o in options)
                prompt += f'\n- "{metric_key}" (one of: {opts_str}): {metric_desc}'
                line_added = True

        if not line_added and custom_type == "number_range":
            rng = _get_number_range(metric)
            if rng:
                bounds = []
                if rng.get("min") is not None:
                    bounds.append(f"min={rng['min']}")
                if rng.get("max") is not None:
                    bounds.append(f"max={rng['max']}")
                if rng.get("step") is not None:
                    bounds.append(f"step={rng['step']}")
                bound_str = ", ".join(bounds) if bounds else "numeric value"
                prompt += f'\n- "{metric_key}" (numeric, {bound_str}): {metric_desc}'
                line_added = True

        if not line_added:
            if m_type == "rating":
                prompt += f'\n- "{metric_key}" (rating 0.0-1.0): {metric_desc}'
            elif m_type == "boolean":
                prompt += f'\n- "{metric_key}" (true/false): {metric_desc}'
            elif m_type == "number":
                prompt += f'\n- "{metric_key}" (numeric value): {metric_desc}'

        # When capture_rationale is on, ask for a sibling free-form rationale
        # key in the SAME flat JSON object. Stays consistent with the "no
        # nested objects" rule enforced below.
        if _wants_rationale(metric):
            prompt += (
                f'\n- "{_rationale_key(metric_key)}" (free-form text, '
                f'1-2 concise sentences explaining why "{metric_key}" was chosen): '
                f"Justification for the value above. Reference specific lines or "
                f"behaviors from the transcript when possible."
            )

    if discover_new_metrics:
        prompt += _render_discovered_metrics_block(
            running_discovered_metrics
        )

    prompt += _build_response_format_instructions(
        llm_metrics,
        discover_new_metrics=discover_new_metrics,
    )
    return prompt


def _build_response_format_instructions(
    llm_metrics: list,
    parent_metric=None,
    discover_new_metrics: bool = False,
) -> str:
    """Build the response format section of the prompt.

    When ``parent_metric`` is set, the example block uses the parent's
    JSON shape (chosen child key + per-child booleans + sequence array)
    instead of N independent metric lines.
    """
    instructions = """

## REQUIRED Response Format
You MUST respond with ONLY a JSON object using the EXACT metric keys listed above. No other keys allowed.

Example format:
{
"""

    if parent_metric is not None:
        parent_key = _parent_key(parent_metric)
        sequence_key = _sequence_key(parent_metric)
        selection_mode = (parent_metric.selection_mode or "multi_label").lower()
        child_keys = [
            c.name.lower().replace(" ", "_") for c in llm_metrics
        ]
        if not child_keys:
            child_keys = ["example_child"]
        chosen_child = child_keys[0]
        if selection_mode == "single_choice":
            instructions += f'  "{parent_key}": "{chosen_child}",\n'
            for i, ck in enumerate(child_keys):
                instructions += (
                    f'  "{ck}": {"true" if i == 0 else "false"},\n'
                )
        else:
            for i, ck in enumerate(child_keys):
                instructions += (
                    f'  "{ck}": {"true" if i % 2 == 0 else "false"},\n'
                )
        # Sequence: first one or two children in order.
        seq_sample = child_keys[: min(2, len(child_keys))]
        seq_str = ", ".join(f'"{k}"' for k in seq_sample)
        instructions += f'  "{sequence_key}": [{seq_str}],\n'
        if _discovery_enabled(parent_metric):
            discovered_key = _discovered_key(parent_metric)
            instructions += (
                f'  "{discovered_key}": [\n'
                '    {"key": "new_outcome_key", "name": "New Outcome", '
                '"description": "one short sentence", '
                '"rationale": "verbatim transcript line"}\n'
                '  ],\n'
            )
        # Parent-level rationale companion example (one per group, not
        # per child).
        if _wants_rationale(parent_metric):
            parent_rationale_key = _rationale_key(parent_key)
            instructions += (
                f'  "{parent_rationale_key}": '
                f'"Brief justification referencing the transcript.",\n'
            )

        if discover_new_metrics:
            instructions += (
                f'  "{DISCOVERED_METRICS_KEY}": [\n'
                '    {"key": "new_metric_key", "name": "New Metric", '
                '"description": "one short sentence", '
                '"suggested_type": "boolean", '
                '"rationale": "verbatim transcript line"}\n'
                '  ],\n'
            )

        discovery_rule = ""
        if _discovery_enabled(parent_metric):
            discovery_rule = (
                "\n7. Discovered labels: emit entries for EVERY distinct "
                "behaviour, topic, or outcome the agent or user "
                "demonstrates that the listed children do NOT already "
                "capture. Aim for 2-5 entries on a normal call; an empty "
                "array means you are claiming the listed children cover "
                "100% of what happened, which is rarely true. Reuse "
                "previously-discovered keys (shown above) only when the "
                "outcome is essentially identical — keep emitting new "
                "entries for genuinely new behaviours. Discovered keys "
                "may also appear inside the sequence array."
            )

        metrics_discovery_rule = ""
        if discover_new_metrics:
            metrics_discovery_rule = (
                f'\n8. Top-level "{DISCOVERED_METRICS_KEY}" array: '
                "propose only BRAND-NEW metrics not already covered by "
                "the metrics block above. Each entry MUST include a "
                "snake_case ``key``, a human-readable ``name``, a one-line "
                "``description``, a ``suggested_type`` from "
                '{"boolean", "rating", "category"}, and a verbatim '
                "``rationale`` line. Return [] only when there is "
                "genuinely nothing new to surface."
            )

        instructions += (
            "}\n\n"
            "CRITICAL RULES:\n"
            "1. Use the EXACT keys shown above - copy them character-for-character.\n"
            "2. Every child key value must be a BOOLEAN (true/false). No nested objects, no strings.\n"
            "3. For single-choice mode, EXACTLY ONE child must be true. Any other count is invalid.\n"
            "4. For multi-label mode, set children independently but DO NOT mark logically contradictory siblings both true.\n"
            "5. The sequence array contains the temporal order of children that actually happened (subset of the true children); use the EXACT child keys.\n"
            "6. Do NOT wrap in \"metrics\" or any other object."
            + discovery_rule
            + metrics_discovery_rule
            + "\nN. Do NOT add comments or explanations. Return ONLY the JSON object, nothing else."
        )

        return instructions

    for metric in llm_metrics:
        metric_key = metric.name.lower().replace(" ", "_")
        m_type = get_metric_type_value(metric)
        custom_type = _get_custom_data_type(metric)

        # ``text`` short-circuits any stale custom_data_type for the same
        # reason it does in ``build_evaluation_prompt``.
        if m_type == "text":
            instructions += (
                f'  "{metric_key}": '
                f'"A brief 1-3 sentence summary describing what was observed.",\n'
            )
            continue

        # Like build_evaluation_prompt: do NOT ``continue`` out of the
        # enum branch — fall through so the rationale example line gets
        # appended for enum metrics too when ``capture_rationale`` is on.
        line_added = False
        if custom_type == "enum":
            options = _get_enum_options(metric)
            if options:
                instructions += f'  "{metric_key}": "{options[0]}",\n'
                line_added = True

        if not line_added:
            if m_type == "rating":
                instructions += f'  "{metric_key}": 0.75,\n'
            elif m_type == "boolean":
                instructions += f'  "{metric_key}": true,\n'
            elif m_type == "number":
                instructions += f'  "{metric_key}": 5,\n'

        if _wants_rationale(metric):
            instructions += (
                f'  "{_rationale_key(metric_key)}": '
                f'"Brief justification referencing the transcript.",\n'
            )

    if discover_new_metrics:
        instructions += (
            f'  "{DISCOVERED_METRICS_KEY}": [\n'
            '    {"key": "new_metric_key", "name": "New Metric", '
            '"description": "one short sentence", '
            '"suggested_type": "boolean", '
            '"rationale": "verbatim transcript line"}\n'
            '  ],\n'
        )

    metrics_discovery_rule = ""
    if discover_new_metrics:
        metrics_discovery_rule = (
            f'\n8. Top-level "{DISCOVERED_METRICS_KEY}" array: propose only '
            "BRAND-NEW metrics not already covered by the metrics above. "
            "Each entry MUST include a snake_case ``key``, a human-readable "
            "``name``, a one-line ``description``, a ``suggested_type`` from "
            '{"boolean", "rating", "category"}, and a verbatim ``rationale``. '
            "Return [] only when there is genuinely nothing new to surface."
        )

    instructions += (
        "}\n\n"
        "CRITICAL RULES:\n"
        "1. Use the EXACT metric keys shown above - copy them character-for-character\n"
        "2. For numeric/boolean metrics, the value must be a SINGLE NUMBER or true/false (no nested objects)\n"
        "3. For enum metrics (\"one of: ...\"), the value must be EXACTLY one of the listed strings (copy verbatim, including casing)\n"
        "4. For text metrics (\"free-form text\"), the value must be a plain JSON string (use \\n for newlines, escape quotes); keep it concise (1-3 sentences unless the metric description asks for more)\n"
        "5. Do NOT wrap in \"metrics\" or any other object\n"
        "6. Do NOT add comments or explanations\n"
        "7. Return ONLY the JSON object, nothing else"
        + metrics_discovery_rule
    )

    return instructions


def _build_system_message(
    llm_metrics: list,
    parent_metric=None,
    discover_new_metrics: bool = False,
) -> str:
    """Build the system message for LLM evaluation."""
    exact_keys: list[str] = []
    if parent_metric is not None:
        parent_root_key = _parent_key(parent_metric)
        exact_keys.append(parent_root_key)
        exact_keys.append(_sequence_key(parent_metric))
        if _discovery_enabled(parent_metric):
            exact_keys.append(_discovered_key(parent_metric))
        # Parent-level rationale key (one per group, never per child).
        if _wants_rationale(parent_metric):
            exact_keys.append(_rationale_key(parent_root_key))
    for metric in llm_metrics:
        key = metric.name.lower().replace(" ", "_")
        exact_keys.append(key)
        # In hierarchical mode children no longer emit rationale keys;
        # the parent owns the single rationale string for the group.
        if (
            parent_metric is None
            and _wants_rationale(metric)
            and get_metric_type_value(metric) != "text"
        ):
            exact_keys.append(_rationale_key(key))
    if discover_new_metrics:
        exact_keys.append(DISCOVERED_METRICS_KEY)

    enum_constraints: list[str] = []
    for metric in llm_metrics:
        if _get_custom_data_type(metric) == "enum":
            options = _get_enum_options(metric)
            if options:
                key = metric.name.lower().replace(" ", "_")
                enum_constraints.append(
                    f'   - "{key}" must be EXACTLY one of: {json.dumps(options)}'
                )

    enum_block = ""
    if enum_constraints:
        enum_block = (
            "\n5. Enum metrics must use a STRING value matching one of the listed options "
            "verbatim (preserve casing, no synonyms):\n" + "\n".join(enum_constraints)
        )

    text_keys = [
        metric.name.lower().replace(" ", "_")
        for metric in llm_metrics
        if get_metric_type_value(metric) == "text"
    ]
    text_block = ""
    if text_keys:
        text_block = (
            "\n5. Text metrics must use a plain JSON STRING value (free-form, "
            "no nested objects, no arrays). Keep it concise (1-3 sentences unless "
            "the metric description asks for more). The following keys are text:\n"
            + "\n".join(f'   - "{k}"' for k in text_keys)
        )

    if parent_metric is not None:
        # Hierarchical mode: only the parent emits a rationale key (when
        # capture_rationale is on); children never do.
        rationale_keys: list[str] = []
        if _wants_rationale(parent_metric):
            rationale_keys.append(_rationale_key(_parent_key(parent_metric)))
    else:
        rationale_keys = [
            _rationale_key(metric.name.lower().replace(" ", "_"))
            for metric in llm_metrics
            if _wants_rationale(metric) and get_metric_type_value(metric) != "text"
        ]
    rationale_block = ""
    if rationale_keys:
        rationale_block = (
            "\n5. Rationale companion keys must use a plain JSON STRING value "
            "(1-2 concise sentences explaining the corresponding value, no nested "
            "objects). The following keys are rationales:\n"
            + "\n".join(f'   - "{k}"' for k in rationale_keys)
        )

    return f"""You are an expert conversation evaluator. You MUST follow these rules STRICTLY:

1. Return ONLY valid JSON - no markdown, no explanations, no comments
2. Use ONLY these exact metric keys (copy-paste them exactly): {json.dumps(exact_keys)}
3. For numeric/boolean metrics, the value must be a single number (0.0-1.0 for ratings, true/false for booleans) - NO nested objects, NO comments
4. Do NOT rename, abbreviate, or modify the metric keys in any way{enum_block}{text_block}{rationale_block}

Example of CORRECT format:
{{"follow_instructions": 0.8, "tone_category": "Friendly", "call_summary": "Customer asked about billing; agent resolved the issue in one turn."}}

Example of WRONG format (DO NOT do this):
{{"metrics": {{"Clarity": {{"score": 7}}}}}}"""


def _parse_llm_response(response_text: str, result_id: str) -> dict:
    """Parse LLM response text to extract evaluation data.

    Robust to: markdown code fences, leading/trailing prose, and
    responses truncated by ``finish_reason="length"`` (common with
    Gemini 2.5 Flash where thinking tokens consume the output budget).
    """
    text = (response_text or "").strip()

    if text.startswith("```json"):
        text = text[len("```json"):].strip()
        if text.endswith("```"):
            text = text[: -len("```")].strip()
    elif text.startswith("```"):
        text = text[len("```"):].strip()
        if text.endswith("```"):
            text = text[: -len("```")].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as initial_err:
        logger.warning(
            f"[EvaluatorResult {result_id}] JSON parsing failed ({initial_err}); "
            "attempting regex extraction"
        )
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Last resort: repair truncated/unterminated JSON so a partially
        # successful evaluation still yields whatever scores were emitted
        # before the cut-off.
        repaired = repair_truncated_json(text)
        if repaired:
            try:
                parsed = json.loads(repaired)
                logger.warning(
                    f"[EvaluatorResult {result_id}] Recovered partial JSON "
                    "from truncated LLM response (response was likely cut off "
                    "at max_tokens; check finish_reason)."
                )
                return parsed
            except json.JSONDecodeError:
                pass

        # Surface a useful error that hints at the real cause.
        snippet = text[-160:] if len(text) > 160 else text
        raise ValueError(
            "Could not parse LLM response as JSON "
            f"(likely truncated at max_tokens). Tail: {snippet!r}"
        )


def evaluate_with_llm(
    transcription: str,
    llm_metrics: list,
    ai_providers: list,
    organization_id: UUID,
    result_id: str,
    db,
    evaluator=None,
    agent=None,
    persona=None,
    scenario=None,
    parent_metric=None,
    running_discovered: list | None = None,
    extra_context: str | None = None,
    all_columns_block: str | None = None,
    comparison_pair: tuple[str, str] | None = None,
    discover_new_metrics: bool = False,
    running_discovered_metrics: list | None = None,
) -> tuple[dict[str, dict[str, Any]], float | None]:
    """
    Evaluate metrics using LLM.

    Args:
        transcription: The conversation transcript
        llm_metrics: List of Metric objects to evaluate
        ai_providers: List of configured AI providers
        organization_id: Organization UUID
        result_id: Result ID for logging
        db: Database session
        evaluator: Optional Evaluator with custom_prompt and LLM config
        agent: Optional Agent for context
        persona: Optional Persona for language info
        scenario: Optional Scenario for context
        parent_metric: Optional parent Metric when ``llm_metrics`` are all
            children of the same hierarchical group. The prompt is then
            rendered as one category block + sequence array.
        extra_context: Optional pre-formatted block of additional inputs
            (e.g. selected CSV column values for a call-import row) that
            is injected into the prompt as a "Context Inputs" section.
        comparison_pair: Optional ``(production, diarised)`` transcript
            pair. When set, the prompt builder swaps the single
            transcript section for a labeled production/diarised pair
            and ``transcription`` is ignored. Used by transcript-compare
            judge metrics (``Metric.compare_transcripts=True``).

    Returns:
        Tuple of (metric_scores dict, evaluation_time in seconds)
    """
    from app.services.ai.llm_service import llm_service

    evaluation_prompt = build_evaluation_prompt(
        transcription=transcription,
        llm_metrics=llm_metrics,
        evaluator=evaluator,
        agent=agent,
        persona=persona,
        scenario=scenario,
        parent_metric=parent_metric,
        running_discovered=running_discovered,
        extra_context=extra_context,
        all_columns_block=all_columns_block,
        comparison_pair=comparison_pair,
        discover_new_metrics=discover_new_metrics,
        running_discovered_metrics=running_discovered_metrics,
    )

    evaluator_llm_provider = getattr(evaluator, "llm_provider", None) if evaluator else None
    evaluator_llm_model = getattr(evaluator, "llm_model", None) if evaluator else None

    if evaluator_llm_provider and evaluator_llm_model:
        if isinstance(evaluator_llm_provider, str):
            llm_provider = ModelProvider(evaluator_llm_provider.lower())
        else:
            llm_provider = evaluator_llm_provider
        llm_model = evaluator_llm_model
    else:
        llm_provider = ModelProvider.OPENAI
        llm_model = "gpt-4o"

    chosen_provider = next(
        (p for p in ai_providers if provider_matches(p.provider, llm_provider)),
        None,
    )
    if not chosen_provider:
        logger.warning(
            f"[EvaluatorResult {result_id}] Provider {llm_provider.value} not configured, evaluation may fail"
        )

    messages = [
        {
            "role": "system",
            "content": _build_system_message(
                llm_metrics,
                parent_metric=parent_metric,
                discover_new_metrics=discover_new_metrics,
            ),
        },
        {"role": "user", "content": evaluation_prompt},
    ]

    # Size the output budget to the prompt: more metrics + rationales
    # means more JSON. 2000 tokens was too tight on Gemini 2.5 Flash where
    # internal "thinking" tokens are deducted from max_output_tokens and
    # truncated responses surfaced as JSONDecodeError. Scale to roughly
    # 300 tokens per metric (covers value + rationale + comma/quotes),
    # clamped to a reasonable ceiling. ``llm_service`` will additionally
    # disable thinking and enforce a floor for Gemini 2.5.
    metric_count = max(1, len(llm_metrics))
    rationale_count = sum(1 for m in llm_metrics if _wants_rationale(m))
    dynamic_max_tokens = min(
        8192,
        max(2000, 300 * metric_count + 200 * rationale_count),
    )

    evaluation_start_time = time.time()
    llm_result = llm_service.generate_response(
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        temperature=0.3,
        max_tokens=dynamic_max_tokens,
    )
    evaluation_time = time.time() - evaluation_start_time

    if llm_result.get("truncated"):
        logger.warning(
            f"[EvaluatorResult {result_id}] LLM response was truncated "
            f"(finish_reason=length, model={llm_model}, "
            f"max_tokens={dynamic_max_tokens}). Parser will attempt recovery."
        )

    evaluation_data = _parse_llm_response(llm_result["text"], result_id)

    if "metrics" in evaluation_data and isinstance(evaluation_data["metrics"], dict):
        evaluation_data = evaluation_data["metrics"]

    metric_scores = _map_evaluation_to_metrics(
        evaluation_data, llm_metrics, parent_metric=parent_metric
    )

    # Top-level metric discovery is independent of the per-row metric
    # mapping above — it lives at ``metric_scores["__discovered_metrics__"]``
    # as a JSON list keyed by the reserved constant so it can't collide
    # with a real metric UUID. We parse it here (rather than inside
    # ``_map_evaluation_to_metrics``) so both flat and hierarchical eval
    # paths share the same code.
    if discover_new_metrics:
        discovered_metrics = _parse_discovered_metrics(
            evaluation_data, llm_metrics
        )
        if discovered_metrics:
            metric_scores[DISCOVERED_METRICS_KEY] = discovered_metrics

    return metric_scores, evaluation_time


def _map_evaluation_to_metrics(
    evaluation_data: dict,
    llm_metrics: list,
    parent_metric=None,
) -> dict[str, dict[str, Any]]:
    """Map LLM evaluation response to metric scores.

    Enum custom metrics are kept as their canonical option string (validated
    against the metric's custom_config.options). Number_range custom metrics
    are clamped to the configured min/max bounds. All others fall back to the
    existing extract+normalize numeric/boolean path.

    When ``parent_metric`` is set, the LLM response is interpreted as a
    hierarchical group: each item in ``llm_metrics`` is a boolean child
    and the parent gets its own metric_scores entry summarising the
    chosen child (single_choice) or the set of selected children
    (multi_label), plus a ``sequence`` array used by the React Flow
    visualisation.
    """
    metric_scores: dict[str, dict[str, Any]] = {}
    response_keys = list(evaluation_data.keys())

    if parent_metric is not None:
        return _map_hierarchical_group(
            evaluation_data, llm_metrics, parent_metric, metric_scores
        )

    for metric in llm_metrics:
        metric_key = metric.name.lower().replace(" ", "_")
        m_type = get_metric_type_value(metric)
        custom_type = _get_custom_data_type(metric)

        raw_score = evaluation_data.get(metric_key)
        if raw_score is None:
            matched_key = find_matching_key(metric.name, response_keys)
            if matched_key:
                raw_score = evaluation_data.get(matched_key)

        # Free-form text / summary metric. Checked BEFORE the custom enum/
        # number_range branches so a stale ``custom_data_type`` left over
        # from a previous metric configuration can't hijack the answer
        # shape. The LLM is asked to return a plain JSON string; tolerate a
        # few obvious shapes (dict with ``value``/``text``/``summary``,
        # numbers/booleans, lists of strings) and coerce to one string.
        # ``None`` is preserved so the UI can render an explicit empty state.
        if m_type == "text":
            text_value = _coerce_text_value(raw_score)
            entry: dict[str, Any] = {
                "value": text_value,
                "type": "text",
                "metric_name": metric.name,
            }
        elif custom_type == "enum":
            options = _get_enum_options(metric)
            value = _normalize_enum_value(raw_score, options)
            entry = {
                "value": value,
                "type": "enum",
                "metric_name": metric.name,
                "options": options,
            }
            if value is None and raw_score is not None:
                entry["raw_value"] = str(raw_score)
        else:
            score = extract_score(raw_score)
            score = normalize_score(score, m_type)

            if custom_type == "number_range" and isinstance(score, (int, float)):
                rng = _get_number_range(metric) or {}
                min_v = rng.get("min")
                max_v = rng.get("max")
                try:
                    if min_v is not None:
                        score = max(float(min_v), float(score))
                    if max_v is not None:
                        score = min(float(max_v), float(score))
                except (TypeError, ValueError):
                    pass

            entry = {
                "value": score,
                "type": m_type,
                "metric_name": metric.name,
            }

        if _wants_rationale(metric) and m_type != "text":
            rationale_key = _rationale_key(metric_key)
            raw_rationale = evaluation_data.get(rationale_key)
            if raw_rationale is None:
                # Try the same fuzzy fallback the value uses, but constrained
                # to keys ending in ``_rationale`` so we never steal another
                # metric's value.
                rationale_candidates = [
                    k for k in response_keys if k.lower().endswith("_rationale")
                ]
                matched = find_matching_key(
                    f"{metric.name} rationale", rationale_candidates
                )
                if matched:
                    raw_rationale = evaluation_data.get(matched)
            entry["rationale"] = _coerce_text_value(raw_rationale)

        metric_scores[str(metric.id)] = entry

    return metric_scores


def _map_hierarchical_group(
    evaluation_data: dict,
    children: list,
    parent_metric,
    metric_scores: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Parse the LLM response for a parent + children group.

    Writes one entry per child (boolean) plus one entry for the parent
    (chosen child name for single_choice or list of true children for
    multi_label, plus a ``sequence`` array).
    """
    parent_key = _parent_key(parent_metric)
    sequence_key = _sequence_key(parent_metric)
    selection_mode = (parent_metric.selection_mode or "multi_label").lower()
    response_keys = list(evaluation_data.keys())

    child_key_to_metric: dict[str, Any] = {}
    for child in children:
        child_key_to_metric[child.name.lower().replace(" ", "_")] = child

    # ----- Per-child booleans -----
    child_results: dict[str, dict[str, Any]] = {}
    for child in children:
        child_key = child.name.lower().replace(" ", "_")
        raw_value = evaluation_data.get(child_key)
        if raw_value is None:
            matched = find_matching_key(child.name, response_keys)
            if matched:
                raw_value = evaluation_data.get(matched)
        score = extract_score(raw_value)
        score = normalize_score(score, "boolean")
        if not isinstance(score, bool):
            # Fall back to False when the LLM returns garbage; we'd
            # rather show a clear "this didn't happen" than guess.
            score = False
        entry: dict[str, Any] = {
            "value": score,
            "type": "boolean",
            "metric_name": child.name,
            "parent_metric_id": str(parent_metric.id),
            "parent_metric_name": parent_metric.name,
        }
        # In hierarchical mode the rationale is captured ONCE at the
        # parent level (below), not per child. Any legacy per-child
        # rationale on the LLM response is intentionally ignored so the
        # table only renders the parent's "<Metric> - LLM Rationale"
        # column.
        child_results[child_key] = entry

    # ----- Discovered labels (multi_label + allow_discovery only) -----
    # Parsed before the sequence so discovered slugs can flow through
    # the sequence array alongside child keys without being filtered out.
    discovered_labels: list[dict[str, Any]] = []
    discovered_slugs: set[str] = set()
    if _discovery_enabled(parent_metric):
        discovered_lookup_key = _discovered_key(parent_metric)
        raw_discovered = evaluation_data.get(discovered_lookup_key)
        if raw_discovered is None:
            matched = find_matching_key(discovered_lookup_key, response_keys)
            if matched:
                raw_discovered = evaluation_data.get(matched)
        if isinstance(raw_discovered, list):
            for entry in raw_discovered:
                if not isinstance(entry, dict):
                    continue
                raw_key = entry.get("key") or entry.get("name")
                slug = _slug_label(raw_key)
                if not slug:
                    continue
                # Drop collisions with real children OR duplicates within
                # the same response — both indicate the model recycled a
                # label it should have either reused (children) or
                # consolidated (in-response dups).
                if slug in child_key_to_metric or slug in discovered_slugs:
                    continue
                discovered_slugs.add(slug)
                name_val = (entry.get("name") or "").strip() or slug.replace(
                    "_", " "
                )
                description_val = _coerce_text_value(entry.get("description"))
                rationale_val = _coerce_text_value(entry.get("rationale"))
                payload: dict[str, Any] = {
                    "key": slug,
                    "name": name_val,
                }
                if description_val:
                    payload["description"] = description_val
                if rationale_val:
                    payload["rationale"] = rationale_val
                discovered_labels.append(payload)

    # ----- Sequence array (filter to known children + discovered slugs) -----
    raw_sequence = evaluation_data.get(sequence_key)
    if raw_sequence is None:
        matched = find_matching_key(sequence_key, response_keys)
        if matched:
            raw_sequence = evaluation_data.get(matched)
    sequence_keys: list[str] = []
    if isinstance(raw_sequence, list):
        seen_seq: set[str] = set()
        for item in raw_sequence:
            if not isinstance(item, str):
                continue
            normalized = _slug_label(item)
            if normalized in seen_seq:
                continue
            if (
                normalized in child_key_to_metric
                or normalized in discovered_slugs
            ):
                seen_seq.add(normalized)
                sequence_keys.append(normalized)

    # For multi_label, auto-promote any child that appears in the
    # sequence to ``true`` even if the LLM forgot to flip its boolean —
    # the sequence implies the event happened. For single_choice we do
    # NOT promote (it would silently violate the exactly-one invariant)
    # and instead flag the mismatch.
    sequence_mismatch = False
    if selection_mode == "multi_label":
        for ck in sequence_keys:
            entry = child_results.get(ck)
            if entry and not entry.get("value"):
                entry["value"] = True
    else:
        # single_choice: collect any sequenced-but-false keys for logging.
        for ck in sequence_keys:
            entry = child_results.get(ck)
            if entry and not entry.get("value"):
                sequence_mismatch = True
                break

    # ----- Single_choice invariant repair -----
    chosen_child_key: str | None = None
    if selection_mode == "single_choice":
        # The LLM may have ALSO emitted a ``<parent_key>`` field telling
        # us its single chosen child. Use that as the source of truth
        # for repair when the booleans drift.
        raw_choice = evaluation_data.get(parent_key)
        normalized_choice: str | None = None
        if isinstance(raw_choice, str):
            normalized_choice = (
                raw_choice.lower().strip().replace(" ", "_")
            )
            if normalized_choice not in child_key_to_metric:
                normalized_choice = None

        trues = [k for k, e in child_results.items() if e.get("value")]
        if len(trues) == 1:
            chosen_child_key = trues[0]
        elif normalized_choice is not None:
            # Use the parent_key choice to repair.
            chosen_child_key = normalized_choice
            for ck, entry in child_results.items():
                entry["value"] = ck == chosen_child_key
        elif len(trues) > 1:
            # Multiple true with no tiebreaker: keep the first one,
            # flip the rest, and flag the result.
            chosen_child_key = trues[0]
            for ck, entry in child_results.items():
                if ck != chosen_child_key:
                    entry["value"] = False
        else:
            chosen_child_key = None

    # Persist child entries (now with any repairs applied).
    for ck, entry in child_results.items():
        child_metric = child_key_to_metric[ck]
        metric_scores[str(child_metric.id)] = entry

    # ----- Parent summary -----
    parent_entry: dict[str, Any] = {
        "type": "category",
        "metric_name": parent_metric.name,
        "selection_mode": selection_mode,
        "sequence": sequence_keys,
    }
    if discovered_labels:
        # Persist into metric_scores so the API surface can aggregate
        # candidates across rows + the flow chart can render discovered
        # nodes. Empty list isn't written so non-discovery flows keep
        # their payload shape unchanged.
        parent_entry["discovered_labels"] = discovered_labels

    if selection_mode == "single_choice":
        if chosen_child_key:
            chosen_metric = child_key_to_metric[chosen_child_key]
            parent_entry["value"] = chosen_metric.name
            parent_entry["chosen_child_id"] = str(chosen_metric.id)
            parent_entry["chosen_child_name"] = chosen_metric.name
        else:
            parent_entry["value"] = None
            parent_entry["error"] = "single_choice_invariant_violated"
        if sequence_mismatch:
            parent_entry["sequence_mismatch"] = True
    else:
        selected_children = [
            {
                "child_id": str(child_key_to_metric[ck].id),
                "child_name": child_key_to_metric[ck].name,
            }
            for ck, entry in child_results.items()
            if entry.get("value")
        ]
        parent_entry["value"] = (
            ", ".join(c["child_name"] for c in selected_children) or None
        )
        parent_entry["selected_child_ids"] = [
            c["child_id"] for c in selected_children
        ]
        parent_entry["selected_child_names"] = [
            c["child_name"] for c in selected_children
        ]

    # ----- Parent-level rationale -----
    # When the parent metric has ``capture_rationale=True`` the LLM is
    # asked for a single rationale key alongside the category. Read it
    # back here so the UI (and CSV export) render exactly one
    # "<Parent> - LLM Rationale" column per categorization metric.
    if _wants_rationale(parent_metric):
        parent_rationale_key = _rationale_key(parent_key)
        raw_rationale = evaluation_data.get(parent_rationale_key)
        if raw_rationale is None:
            rationale_candidates = [
                k for k in response_keys if k.lower().endswith("_rationale")
            ]
            matched = find_matching_key(
                f"{parent_metric.name} rationale", rationale_candidates
            )
            if matched:
                raw_rationale = evaluation_data.get(matched)
        parent_entry["rationale"] = _coerce_text_value(raw_rationale)

    metric_scores[str(parent_metric.id)] = parent_entry
    return metric_scores


def handle_llm_evaluation_error(
    llm_metrics: list,
    error: Exception,
) -> dict[str, dict[str, Any]]:
    """Build error response for all LLM metrics when evaluation fails."""
    metric_scores: dict[str, dict[str, Any]] = {}
    for metric in llm_metrics:
        entry: dict[str, Any] = {
            "value": None,
            "type": get_metric_type_value(metric),
            "metric_name": metric.name,
            "error": str(error),
        }
        if _wants_rationale(metric) and get_metric_type_value(metric) != "text":
            entry["rationale"] = None
        metric_scores[str(metric.id)] = entry
    return metric_scores
