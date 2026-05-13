"""LLM-based evaluation: prompt building and response parsing."""

import json
import re
import time
from typing import Any, Optional
from uuid import UUID

from loguru import logger

from app.models.database import ModelProvider

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


def build_evaluation_prompt(
    transcription: str,
    llm_metrics: list,
    evaluator=None,
    agent=None,
    persona=None,
    scenario=None,
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

    Returns:
        Complete evaluation prompt string
    """
    is_custom_evaluator = evaluator and bool(evaluator.custom_prompt)

    if is_custom_evaluator:
        prompt = f"""You are evaluating a conversation transcript against the agent's system prompt. You MUST evaluate ONLY the specific metrics listed below and use the EXACT metric keys provided.

## Agent System Prompt
The following is the system prompt / instructions that the agent was configured with. Use this to understand the agent's goals, rules, and expected behavior when evaluating the conversation.

{evaluator.custom_prompt}

## Conversation Transcript
{transcription}

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

## Conversation Transcript
{transcription}

## Metrics to Evaluate (use EXACT keys below)
"""

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

    prompt += _build_response_format_instructions(llm_metrics)
    return prompt


def _build_response_format_instructions(llm_metrics: list) -> str:
    """Build the response format section of the prompt."""
    instructions = """

## REQUIRED Response Format
You MUST respond with ONLY a JSON object using the EXACT metric keys listed above. No other keys allowed.

Example format:
{
"""
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

    instructions += """}

CRITICAL RULES:
1. Use the EXACT metric keys shown above - copy them character-for-character
2. For numeric/boolean metrics, the value must be a SINGLE NUMBER or true/false (no nested objects)
3. For enum metrics ("one of: ..."), the value must be EXACTLY one of the listed strings (copy verbatim, including casing)
4. For text metrics ("free-form text"), the value must be a plain JSON string (use \\n for newlines, escape quotes); keep it concise (1-3 sentences unless the metric description asks for more)
5. Do NOT wrap in "metrics" or any other object
6. Do NOT add comments or explanations
7. Return ONLY the JSON object, nothing else"""

    return instructions


def _build_system_message(llm_metrics: list) -> str:
    """Build the system message for LLM evaluation."""
    exact_keys: list[str] = []
    for metric in llm_metrics:
        key = metric.name.lower().replace(" ", "_")
        exact_keys.append(key)
        if _wants_rationale(metric) and get_metric_type_value(metric) != "text":
            exact_keys.append(_rationale_key(key))

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
    """Parse LLM response text to extract evaluation data."""
    text = response_text.strip()

    if text.startswith("```json"):
        text = text.replace("```json", "").replace("```", "").strip()
    elif text.startswith("```"):
        text = text.replace("```", "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"[EvaluatorResult {result_id}] JSON parsing failed, attempting regex extraction")
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                raise ValueError("Could not parse extracted JSON")
        raise ValueError("Could not parse LLM response as JSON")


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
        {"role": "system", "content": _build_system_message(llm_metrics)},
        {"role": "user", "content": evaluation_prompt},
    ]

    evaluation_start_time = time.time()
    llm_result = llm_service.generate_response(
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        temperature=0.3,
        max_tokens=2000,
    )
    evaluation_time = time.time() - evaluation_start_time

    evaluation_data = _parse_llm_response(llm_result["text"], result_id)

    if "metrics" in evaluation_data and isinstance(evaluation_data["metrics"], dict):
        evaluation_data = evaluation_data["metrics"]

    metric_scores = _map_evaluation_to_metrics(evaluation_data, llm_metrics)
    return metric_scores, evaluation_time


def _map_evaluation_to_metrics(
    evaluation_data: dict,
    llm_metrics: list,
) -> dict[str, dict[str, Any]]:
    """Map LLM evaluation response to metric scores.

    Enum custom metrics are kept as their canonical option string (validated
    against the metric's custom_config.options). Number_range custom metrics
    are clamped to the configured min/max bounds. All others fall back to the
    existing extract+normalize numeric/boolean path.
    """
    metric_scores: dict[str, dict[str, Any]] = {}
    response_keys = list(evaluation_data.keys())

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
