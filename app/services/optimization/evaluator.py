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

try:
    from gepa.adapters.default_adapter.default_adapter import EvaluationResult
except Exception:
    EvaluationResult = None  # type: ignore[assignment,misc]


def build_evaluator(
    metrics: List[Metric],
    ai_providers: List[AIProvider],
    organization_id: UUID,
    db,
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
        from app.models.database import ModelProvider

        provider = next(
            (p for p in ai_providers if p.provider.lower() in ("openai", "anthropic")),
            ai_providers[0] if ai_providers else None,
        )
        if not provider:
            return EvaluationResult(score=0.5, feedback="No AI provider available")

        try:
            result = llm_service.generate_response(
                messages=[
                    {"role": "system", "content": "You are an expert voice AI evaluator. Respond with JSON only."},
                    {"role": "user", "content": eval_prompt},
                ],
                llm_provider=ModelProvider(provider.provider.lower()),
                llm_model="gpt-4o",
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
