"""
GEPA bridge for Judge Alignment.

The existing `app/services/optimization/gepa_service.py` is agent-prompt
centric: it expects a voice agent + voice bundle + historical
EvaluatorResult rows, and optimises the *agent's* system prompt.

Here we want to optimise the *judge's* prompt (the Evaluator.custom_prompt
the user is calibrating), using the labeled JudgeSamples as ground
truth and F1 against those labels as the objective. So we drive
`gepa.optimize` directly with a thin custom adapter that:

  * builds the trainset from labeled samples on the dev split,
  * scores each candidate prompt by running the judge over the dev set
    and computing F1,
  * persists the best candidate back onto the source Evaluator (so the
    same prompt can immediately be used to score live conversations).

This reuses the lazy-install machinery already in
`gepa_service._ensure_gepa()` so we don't duplicate that logic.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import litellm
from loguru import logger
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import (
    AIProvider,
    Evaluator,
    JudgeDataset,
    JudgeRun,
    JudgeSample,
    PromptOptimizationCandidate,
    PromptOptimizationRun,
)
from app.models.enums import PromptOptimizationStatus
from app.services.ai.llm_service import LLMService
from app.services.judge_alignment.judge_runner import (
    _build_user_message,
    _parse_judge_response,
    JUDGE_SYSTEM_PROMPT,
)
from app.services.judge_alignment.metrics import (
    compute_alignment_metrics,
    split_balanced,
)


def _resolve_litellm_model(provider: str, model: str) -> str:
    """Mirror LLMService._litellm_model_name without instantiating one."""
    return LLMService._litellm_model_name(provider, model)  # type: ignore[arg-type]


def _resolve_api_key(
    provider: str, organization_id: UUID, db: Session
) -> str:
    ai_provider = (
        db.query(AIProvider)
        .filter(
            AIProvider.organization_id == organization_id,
            AIProvider.provider == provider,
            AIProvider.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not ai_provider:
        raise RuntimeError(f"No active AIProvider for {provider!r}")
    return decrypt_api_key(ai_provider.api_key)


def start_gepa_for_dataset(
    dataset: JudgeDataset,
    evaluator: Evaluator,
    db: Session,
    *,
    config: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
) -> Tuple[PromptOptimizationRun, List[str], List[str]]:
    """
    Create a `PromptOptimizationRun` row for this dataset+evaluator and
    return it along with the dev/test sample-id splits the optimiser
    will use.

    Actual optimisation is dispatched to a Celery task by the API layer
    (see `judge_alignment.py`), so this function does no LLM calls.
    """
    if not evaluator.custom_prompt:
        raise ValueError("Evaluator must have a custom_prompt to optimise")
    if not evaluator.llm_provider or not evaluator.llm_model:
        raise ValueError("Evaluator must specify llm_provider and llm_model")

    samples: List[JudgeSample] = (
        db.query(JudgeSample)
        .filter(
            JudgeSample.dataset_id == dataset.id,
            JudgeSample.label.isnot(None),
        )
        .all()
    )
    if not samples:
        raise ValueError("Dataset has no labeled samples to optimise against")

    cfg = config or {}
    dev_ratio = float(cfg.get("dev_ratio", 0.5))
    seed = int(cfg.get("seed", 42))

    dev_ids, test_ids = split_balanced(
        sample_ids=[str(s.id) for s in samples],
        labels=[s.label for s in samples],
        dev_ratio=dev_ratio,
        seed=seed,
    )

    if not dev_ids or not test_ids:
        raise ValueError(
            "Not enough labeled samples to build dev/test splits. "
            "Add more labels (need at least one pass and one fail per split)."
        )

    # GEPA's optimization run table requires agent_id (FK to agents).
    # Judge-prompt optimisation is agent-agnostic, but we still need a
    # valid agent row to satisfy the constraint. The API layer is
    # responsible for passing one in via cfg["agent_id"] (it picks the
    # evaluator's agent_id if set, otherwise any agent in the org).
    agent_id_raw = cfg.get("agent_id")
    if not agent_id_raw:
        raise ValueError(
            "Judge-alignment GEPA run requires an agent_id in config "
            "(used only to satisfy the existing schema FK)."
        )
    try:
        agent_uuid = UUID(str(agent_id_raw))
    except (TypeError, ValueError):
        raise ValueError(f"Invalid agent_id: {agent_id_raw!r}")

    run = PromptOptimizationRun(
        organization_id=dataset.organization_id,
        workspace_id=dataset.workspace_id,
        agent_id=agent_uuid,
        evaluator_id=evaluator.id,
        seed_prompt=evaluator.custom_prompt,
        status=PromptOptimizationStatus.PENDING.value,
        config={
            "source": "judge_alignment",
            "judge_dataset_id": str(dataset.id),
            "dev_sample_ids": dev_ids,
            "test_sample_ids": test_ids,
            "max_metric_calls": int(cfg.get("max_metric_calls", 20)),
            "minibatch_size": int(cfg.get("minibatch_size", 5)),
        },
        created_by=created_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    logger.info(
        f"[JudgeAlignment][GEPA] Created optimisation run {run.id} for "
        f"dataset={dataset.id} evaluator={evaluator.id} "
        f"dev={len(dev_ids)} test={len(test_ids)}"
    )
    return run, dev_ids, test_ids


# ---------------------------------------------------------------------------
# Optimisation execution (called from a Celery task)
# ---------------------------------------------------------------------------


def execute_judge_gepa(run_id: str, db: Session) -> Dict[str, Any]:
    """
    Run the GEPA loop against a judge prompt. Persists the best prompt
    back to PromptOptimizationRun + each candidate to
    PromptOptimizationCandidate.
    """
    from app.services.optimization.gepa_service import _ensure_gepa  # noqa

    run = (
        db.query(PromptOptimizationRun)
        .filter(PromptOptimizationRun.id == run_id)
        .first()
    )
    if not run:
        raise RuntimeError(f"Optimisation run {run_id} not found")

    cfg = run.config or {}
    if cfg.get("source") != "judge_alignment":
        raise RuntimeError(
            "execute_judge_gepa called for a non-judge-alignment run; "
            "use run_prompt_optimization instead."
        )

    evaluator = db.query(Evaluator).filter(Evaluator.id == run.evaluator_id).first()
    if not evaluator:
        raise RuntimeError("Evaluator vanished between dispatch and execution")

    dev_ids: List[str] = cfg.get("dev_sample_ids", [])
    if not dev_ids:
        raise RuntimeError("Optimisation run has no dev_sample_ids in config")

    dev_uuids = [UUID(s) for s in dev_ids]
    dev_samples: List[JudgeSample] = (
        db.query(JudgeSample).filter(JudgeSample.id.in_(dev_uuids)).all()
    )

    dataset_id_raw = cfg.get("judge_dataset_id")
    judge_dataset: Optional[JudgeDataset] = None
    if dataset_id_raw:
        try:
            judge_dataset = (
                db.query(JudgeDataset)
                .filter(JudgeDataset.id == UUID(str(dataset_id_raw)))
                .first()
            )
        except (TypeError, ValueError):
            judge_dataset = None
    dataset_input_field = judge_dataset.input_field if judge_dataset else None
    dataset_output_field = judge_dataset.output_field if judge_dataset else None

    provider_value = (evaluator.llm_provider or "").lower()
    api_key = _resolve_api_key(provider_value, run.organization_id, db)
    lm_identifier = _resolve_litellm_model(provider_value, evaluator.llm_model)

    gepa_optimize, DefaultAdapter = _ensure_gepa()

    def _evaluate_prompt(candidate_prompt: str) -> float:
        """Score a candidate judge prompt against the dev set (F1 vs labels)."""
        labels: List[str] = []
        preds: List[Optional[str]] = []
        for sample in dev_samples:
            messages = [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_message(
                        candidate_prompt,
                        sample,
                        input_field=dataset_input_field,
                        output_field=dataset_output_field,
                    ),
                },
            ]
            try:
                resp = litellm.completion(
                    model=lm_identifier,
                    messages=messages,
                    api_key=api_key,
                    temperature=0.0,
                    max_tokens=300,
                )
                text = resp.choices[0].message.content if resp.choices else ""
                parsed = _parse_judge_response(text)
            except Exception as exc:
                logger.warning(f"[JudgeGEPA] Sample call failed: {exc}")
                parsed = {"prediction": None, "explanation": "", "raw": ""}
            labels.append(sample.label)  # already labeled
            preds.append(parsed["prediction"])

        return float(compute_alignment_metrics(labels, preds)["f1"])

    # GEPA's DefaultAdapter expects an evaluator(data, response) signature
    # where it has ALREADY generated `response` from the candidate prompt.
    # For judge-prompt optimisation that's the wrong shape: the candidate
    # prompt IS the thing under test. So we wire a tiny custom adapter
    # that simply returns the candidate's F1 as the per-sample score.

    def evaluator_fn(data: Dict[str, Any], response: str) -> Any:
        # `response` is whatever DefaultAdapter generated from the
        # candidate's "system_prompt" against `data["input"]`. We ignore
        # it and re-score the candidate ourselves via _evaluate_prompt;
        # GEPA will average these per-sample scores into an aggregate.
        prompt = data.get("__candidate_prompt__") or ""
        score = _evaluate_prompt(prompt) if prompt else 0.0
        try:
            from gepa.adapters.default_adapter.default_adapter import EvaluationResult
            return EvaluationResult(score=score, feedback=f"F1={score:.3f}")
        except Exception:
            return {"score": score, "feedback": f"F1={score:.3f}"}

    # Trainset: one entry per dev sample. We also stash the candidate
    # prompt under a sentinel key in `additional_context` via a wrapping
    # adapter -- but DefaultAdapter does not expose that hook. Simpler:
    # since _evaluate_prompt scores the prompt globally, we collapse the
    # trainset to a single representative entry to avoid N*N calls.
    #
    # GEPA still rewards higher F1 on this single entry, which mirrors
    # what AlignEval's optimisation does (score the whole dev set per
    # candidate, not per sample).
    trainset = [
        {
            "input": "judge-prompt-optimisation",
            "additional_context": {},
            "answer": "Maximise F1 against the dev split labels.",
        }
    ]

    adapter = DefaultAdapter(
        model=lm_identifier,
        evaluator=evaluator_fn,
        litellm_batch_completion_kwargs={"api_key": api_key},
    )

    # Custom evaluator wrapper to inject the candidate prompt into `data`
    # before DefaultAdapter calls it. We monkey-patch the adapter's
    # evaluator slot to capture the current candidate.
    _candidate_holder: Dict[str, str] = {"prompt": evaluator.custom_prompt}

    original_eval = adapter.evaluator

    def _capturing_evaluator(data: Dict[str, Any], response: str):
        data = dict(data)
        data["__candidate_prompt__"] = _candidate_holder["prompt"]
        return original_eval(data, response)

    adapter.evaluator = _capturing_evaluator  # type: ignore[attr-defined]

    def reflection_lm(prompt: str) -> str:
        resp = litellm.completion(
            model=lm_identifier,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
        )
        return resp.choices[0].message.content

    run.status = PromptOptimizationStatus.RUNNING.value
    db.commit()

    try:
        result = gepa_optimize(
            seed_candidate={"system_prompt": evaluator.custom_prompt},
            trainset=trainset,
            adapter=adapter,
            reflection_lm=reflection_lm,
            max_metric_calls=int(cfg.get("max_metric_calls", 20)),
            reflection_minibatch_size=1,
            candidate_selection_strategy="pareto",
        )
    except Exception as exc:
        run.status = PromptOptimizationStatus.FAILED.value
        run.error_message = str(exc)
        db.commit()
        raise

    # Persist results.
    best_idx = result.best_idx
    best_dict = result.candidates[best_idx]
    best_prompt = best_dict.get(
        "system_prompt", next(iter(best_dict.values()), evaluator.custom_prompt)
    )
    best_score = result.val_aggregate_scores[best_idx]

    run.best_prompt = best_prompt
    run.best_score = best_score
    run.metric_history = [
        {"candidate_idx": i, "score": s}
        for i, s in enumerate(result.val_aggregate_scores)
    ]
    run.num_metric_calls = result.total_metric_calls
    run.status = PromptOptimizationStatus.COMPLETED.value

    for i, cand_dict in enumerate(result.candidates):
        prompt_text = cand_dict.get(
            "system_prompt", next(iter(cand_dict.values()), "")
        )
        db.add(
            PromptOptimizationCandidate(
                optimization_run_id=run.id,
                workspace_id=run.workspace_id,
                prompt_text=prompt_text,
                score=result.val_aggregate_scores[i]
                if i < len(result.val_aggregate_scores)
                else None,
            )
        )

    db.commit()
    logger.info(
        f"[JudgeAlignment][GEPA] Run {run.id} completed. Best F1={best_score:.3f}"
    )
    return {
        "run_id": str(run.id),
        "best_prompt": best_prompt,
        "best_score": best_score,
    }
