"""LLM-based evaluation: prompt building and response parsing."""

import json
import re
import time
from typing import Any
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

        if m_type == "rating":
            prompt += f'\n- "{metric_key}" (rating 0.0-1.0): {metric_desc}'
        elif m_type == "boolean":
            prompt += f'\n- "{metric_key}" (true/false): {metric_desc}'
        elif m_type == "number":
            prompt += f'\n- "{metric_key}" (numeric value): {metric_desc}'

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

        if m_type == "rating":
            instructions += f'  "{metric_key}": 0.75,\n'
        elif m_type == "boolean":
            instructions += f'  "{metric_key}": true,\n'
        elif m_type == "number":
            instructions += f'  "{metric_key}": 5,\n'

    instructions += """}

CRITICAL RULES:
1. Use the EXACT metric keys shown above - copy them character-for-character
2. Each value must be a SINGLE NUMBER (not an object with score/comments)
3. Do NOT wrap in "metrics" or any other object
4. Do NOT add comments or explanations
5. Return ONLY the JSON object, nothing else"""

    return instructions


def _build_system_message(llm_metrics: list) -> str:
    """Build the system message for LLM evaluation."""
    exact_keys = [metric.name.lower().replace(" ", "_") for metric in llm_metrics]

    return f"""You are an expert conversation evaluator. You MUST follow these rules STRICTLY:

1. Return ONLY valid JSON - no markdown, no explanations, no comments
2. Use ONLY these exact metric keys (copy-paste them exactly): {json.dumps(exact_keys)}
3. Each value must be a single number (0.0-1.0 for ratings, 0 or 1 for boolean) - NO nested objects, NO comments
4. Do NOT rename, abbreviate, or modify the metric keys in any way

Example of CORRECT format:
{{"follow_instructions": 0.8, "clarity_and_empathy": 0.7}}

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
    """Map LLM evaluation response to metric scores."""
    metric_scores: dict[str, dict[str, Any]] = {}
    response_keys = list(evaluation_data.keys())

    for metric in llm_metrics:
        metric_key = metric.name.lower().replace(" ", "_")
        m_type = get_metric_type_value(metric)

        raw_score = evaluation_data.get(metric_key)
        if raw_score is None:
            matched_key = find_matching_key(metric.name, response_keys)
            if matched_key:
                raw_score = evaluation_data.get(matched_key)

        score = extract_score(raw_score)
        score = normalize_score(score, m_type)

        metric_scores[str(metric.id)] = {
            "value": score,
            "type": m_type,
            "metric_name": metric.name,
        }

    return metric_scores


def handle_llm_evaluation_error(
    llm_metrics: list,
    error: Exception,
) -> dict[str, dict[str, Any]]:
    """Build error response for all LLM metrics when evaluation fails."""
    metric_scores: dict[str, dict[str, Any]] = {}
    for metric in llm_metrics:
        metric_scores[str(metric.id)] = {
            "value": None,
            "type": get_metric_type_value(metric),
            "metric_name": metric.name,
            "error": str(error),
        }
    return metric_scores
