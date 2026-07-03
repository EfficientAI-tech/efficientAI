"""
Build a GEPA-compatible evaluator callable.

The evaluator scores how well an LLM response (generated from a candidate
system prompt) aligns with metric targets for a historical voice AI
conversation transcript.  It delegates to ``LLMService.generate_response``
so that API keys are passed per-call -- consistent with the rest of the
codebase.
"""

import json
from typing import Any, Callable, Dict, List
from uuid import UUID

from loguru import logger

from app.models.database import AIProvider, Metric
from app.workers.tasks.helpers.score_utils import get_metric_type_value

_DEFAULT_SCORING_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "google": "gemini-2.0-flash",
}


def _normalize_provider_prefix(prefix: str) -> str:
    normalized = prefix.lower()
    if normalized == "gemini":
        return "google"
    return normalized


def _resolve_scoring_lm(
    lm_identifier: str | None,
    ai_providers: List[AIProvider],
) -> tuple["ModelProvider", str] | tuple[None, None]:
    """Pick provider + model for GEPA scoring calls."""
    from app.models.database import ModelProvider

    if lm_identifier and "/" in lm_identifier:
        prefix, model = lm_identifier.split("/", 1)
        provider_key = _normalize_provider_prefix(prefix)
        provider = next(
            (
                p
                for p in ai_providers
                if p.is_active and p.provider.lower() == provider_key
            ),
            None,
        )
        if provider:
            return ModelProvider(provider.provider.lower()), model

    provider = next(
        (p for p in ai_providers if p.is_active and p.provider.lower() == "openai"),
        None,
    )
    if provider:
        return ModelProvider.OPENAI, _DEFAULT_SCORING_MODELS["openai"]

    provider = next((p for p in ai_providers if p.is_active), None)
    if not provider:
        return None, None

    provider_key = provider.provider.lower()
    return (
        ModelProvider(provider_key),
        _DEFAULT_SCORING_MODELS.get(provider_key, _DEFAULT_SCORING_MODELS["openai"]),
    )


def _get_evaluation_result_class():
    """Lazy-import EvaluationResult; gepa will already be installed by the time this is called."""
    try:
        from gepa.adapters.default_adapter.default_adapter import EvaluationResult
        return EvaluationResult
    except ImportError:
        return None


def build_evaluator(
    metrics: List[Metric],
    ai_providers: List[AIProvider],
    organization_id: UUID,
    db,
    lm_identifier: str | None = None,
) -> Callable[[Dict[str, Any], str], Any]:
    """
    Return a function with the signature GEPA's ``Evaluator`` protocol
    expects::

        (data: DefaultDataInst, response: str) -> EvaluationResult
    """
    metrics_str = "\n".join(
        f'- "{m.name}" ({get_metric_type_value(m)}): {m.description or f"Evaluate {m.name}"}'
        for m in metrics
    )

    EvaluationResult = _get_evaluation_result_class()

    def evaluator_fn(data: Dict[str, Any], response: str) -> Any:
        transcript = data["input"]
        additional = data.get("additional_context", {})
        historical_scores = {
            k.replace("metric_", ""): v
            for k, v in additional.items()
            if k.startswith("metric_")
        }

        score_context = ""
        if historical_scores:
            score_context = (
                "\n\nHistorical metric scores for this conversation:\n"
                + "\n".join(f"- {k}: {v}" for k, v in historical_scores.items())
            )

        eval_prompt = (
            "You are evaluating whether a voice agent's generated response is "
            "consistent with the system prompt instructions and handles the "
            "conversation well.\n\n"
            f"## Agent's Generated Response\n{response[:2000]}\n\n"
            f"## Historical Conversation Transcript\n{transcript[:2000]}\n\n"
            f"## Metrics\n{metrics_str}\n"
            f"{score_context}\n\n"
            "Rate the quality of the agent's response. Consider:\n"
            "1. Does it follow the system prompt instructions?\n"
            "2. Would it score well on the listed metrics?\n"
            "3. Is it professional and helpful?\n\n"
            "Respond with ONLY a JSON object: "
            '{\"score\": <float 0.0-1.0>, \"feedback\": \"<brief explanation>\"}'
        )

        from app.services.ai.llm_service import llm_service

        llm_provider, llm_model = _resolve_scoring_lm(lm_identifier, ai_providers)
        if not llm_provider or not llm_model:
            return EvaluationResult(score=0.5, feedback="No AI provider available")

        try:
            result = llm_service.generate_response(
                messages=[
                    {"role": "system", "content": "You are an expert voice AI evaluator. Respond with JSON only."},
                    {"role": "user", "content": eval_prompt},
                ],
                llm_provider=llm_provider,
                llm_model=llm_model,
                organization_id=organization_id,
                db=db,
                temperature=0.3,
                max_tokens=500,
            )
            text = result.get("text", "").strip()
            if text.startswith("```"):
                text = text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(text)
            score = float(parsed.get("score", 0.5))
            feedback = parsed.get("feedback", "")
            return EvaluationResult(score=score, feedback=feedback)
        except Exception as e:
            logger.warning(f"GEPA evaluation failed: {e}")
            return EvaluationResult(score=0.5, feedback=f"Evaluation error: {e}")

    return evaluator_fn
