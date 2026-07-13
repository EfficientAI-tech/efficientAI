"""Queue evaluator runs (web bridge via Celery)."""

import random
from typing import List, Tuple
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Evaluator, EvaluatorResult, EvaluatorResultStatus, Scenario
from app.models.schemas import EvaluatorResultResponse
from app.services.evaluators.evaluator_helpers import is_custom_evaluator


def generate_unique_result_id(db: Session) -> str:
    max_attempts = 100
    for _ in range(max_attempts):
        candidate_id = f"{random.randint(100000, 999999)}"
        existing = db.query(EvaluatorResult).filter(EvaluatorResult.result_id == candidate_id).first()
        if not existing:
            return candidate_id
    raise HTTPException(status_code=500, detail="Failed to generate unique result ID")


def queue_evaluator_runs(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    evaluator_ids: List[UUID],
) -> Tuple[List[str], List[EvaluatorResultResponse]]:
    """Create EvaluatorResult rows and dispatch Celery run_evaluator tasks."""
    from app.workers.celery_app import run_evaluator_task

    if not evaluator_ids:
        raise HTTPException(status_code=400, detail="No evaluator IDs provided")

    unique_evaluator_ids = list(set(evaluator_ids))
    evaluators = (
        db.query(Evaluator)
        .filter(
            Evaluator.id.in_(unique_evaluator_ids),
            Evaluator.organization_id == organization_id,
            Evaluator.workspace_id == workspace_id,
        )
        .all()
    )
    if len(evaluators) != len(unique_evaluator_ids):
        raise HTTPException(
            status_code=404,
            detail=(
                f"One or more evaluators not found. "
                f"Found {len(evaluators)} of {len(unique_evaluator_ids)} unique evaluators"
            ),
        )

    evaluator_map = {str(e.id): e for e in evaluators}
    task_ids: List[str] = []
    evaluator_results: List[EvaluatorResultResponse] = []

    for evaluator_id in evaluator_ids:
        evaluator = evaluator_map.get(str(evaluator_id))
        if not evaluator:
            continue

        try:
            if is_custom_evaluator(evaluator):
                raise HTTPException(
                    status_code=400,
                    detail="Custom evaluators cannot be run via the live bridge",
                )
            if not evaluator.agent_id:
                raise HTTPException(status_code=400, detail="Evaluator has no agent configured")

            scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
            scenario_name = scenario.name if scenario else "Unknown Scenario"

            result_id = generate_unique_result_id(db)
            evaluator_result = EvaluatorResult(
                result_id=result_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                evaluator_id=evaluator.id,
                agent_id=evaluator.agent_id,
                persona_id=evaluator.persona_id,
                scenario_id=evaluator.scenario_id,
                name=scenario_name,
                status=EvaluatorResultStatus.QUEUED.value,
                audio_s3_key=None,
            )
            db.add(evaluator_result)
            db.commit()
            db.refresh(evaluator_result)

            task = run_evaluator_task.delay(str(evaluator.id), str(evaluator_result.id))
            task_ids.append(task.id)

            evaluator_result.celery_task_id = task.id
            db.commit()

            evaluator_results.append(EvaluatorResultResponse.model_validate(evaluator_result))
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating task for evaluator {evaluator.id}: {repr(e)}", exc_info=True)
            continue

    if not task_ids:
        raise HTTPException(status_code=500, detail="Failed to create any tasks")

    return task_ids, evaluator_results
