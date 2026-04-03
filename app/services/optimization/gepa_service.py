"""
GEPA Prompt Optimization Service -- orchestrator.

Wires together LM resolution, data preparation, evaluation, and the GEPA
engine.  Each concern lives in its own module; this file is the thin
entry-point consumed by the Celery task.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

import litellm
from loguru import logger

from app.models.database import (
    Agent,
    AIProvider,
    Evaluator,
    EvaluatorResult,
    Metric,
    VoiceBundle,
)
from app.services.optimization.data_preparation import build_trainset
from app.services.optimization.evaluator import build_evaluator
from app.services.optimization.lm_resolver import resolve_api_key, resolve_lm

GEPA_AVAILABLE = False
_gepa_import_error: str | None = None

try:
    from gepa import optimize as gepa_optimize
    from gepa.adapters.default_adapter.default_adapter import DefaultAdapter

    GEPA_AVAILABLE = True
except Exception as _exc:
    _gepa_import_error = str(_exc)
    logger.warning(f"GEPA not available: {_exc}")


def run_optimization(
    agent: Agent,
    evaluator: Optional[Evaluator],
    voice_bundle: Optional[VoiceBundle],
    training_data: List[EvaluatorResult],
    metrics: List[Metric],
    ai_providers: List[AIProvider],
    organization_id: UUID,
    db,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run a full GEPA optimization loop.

    Returns a dict with keys: ``best_candidate``, ``best_score``,
    ``candidates``, ``metric_history``, ``total_metric_calls``.
    """
    if not GEPA_AVAILABLE:
        detail = f" Import error: {_gepa_import_error}" if _gepa_import_error else ""
        raise ImportError(
            "GEPA is not available. Install with: pip install -e '.[gepa]' "
            f"(local dev) or pip install 'efficientai[gepa]' (production).{detail}"
        )

    config = config or {}
    max_metric_calls = config.get("max_metric_calls", 20)
    minibatch_size = config.get("minibatch_size", 5)

    seed_prompt = agent.provider_prompt or agent.description or ""
    lm_identifier = resolve_lm(voice_bundle, evaluator)
    api_key = resolve_api_key(lm_identifier, ai_providers)

    trainset = build_trainset(training_data, metrics)
    if not trainset:
        raise ValueError("No evaluator results with transcripts available for optimization")

    evaluator_fn = build_evaluator(metrics, ai_providers, organization_id, db)

    logger.info(
        f"[GEPA] Starting optimization for agent '{agent.name}' "
        f"with {len(trainset)} training examples, LM={lm_identifier}"
    )

    adapter = DefaultAdapter(
        model=lm_identifier,
        evaluator=evaluator_fn,
        litellm_batch_completion_kwargs={"api_key": api_key},
    )

    def reflection_lm(prompt: str) -> str:
        resp = litellm.completion(
            model=lm_identifier,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
        )
        return resp.choices[0].message.content

    result = gepa_optimize(
        seed_candidate={"system_prompt": seed_prompt},
        trainset=trainset,
        adapter=adapter,
        reflection_lm=reflection_lm,
        max_metric_calls=max_metric_calls,
        reflection_minibatch_size=min(minibatch_size, len(trainset)),
        candidate_selection_strategy="pareto",
    )

    return _format_result(result, seed_prompt)


def _format_result(result, seed_prompt: str) -> Dict[str, Any]:
    """Normalise a ``GEPAResult`` into a serialisable dict."""
    candidates = []
    for i, cand_dict in enumerate(result.candidates):
        prompt_text = cand_dict.get("system_prompt", next(iter(cand_dict.values()), ""))
        candidates.append({
            "prompt_text": prompt_text,
            "score": result.val_aggregate_scores[i] if i < len(result.val_aggregate_scores) else None,
            "parent_idx": result.parents[i] if i < len(result.parents) else None,
            "reflection_summary": None,
        })

    best = result.best_candidate
    best_prompt = best.get("system_prompt", next(iter(best.values()), seed_prompt))
    best_score = result.val_aggregate_scores[result.best_idx]

    return {
        "best_candidate": best_prompt,
        "best_score": best_score,
        "candidates": candidates,
        "metric_history": [
            {"candidate_idx": i, "score": s}
            for i, s in enumerate(result.val_aggregate_scores)
        ],
        "total_metric_calls": result.total_metric_calls,
    }
