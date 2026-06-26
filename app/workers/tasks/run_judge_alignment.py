"""
Celery task: execute a JudgeRun (LLM-judge against a JudgeDataset).

Loads the run + dataset + evaluator, picks samples for the requested
split (using sample ids stashed on the run by the API layer when
applicable), invokes `judge_runner.run_judge`, and persists status +
metrics. On failure the run is marked "failed" with the error message.
"""

from typing import List, Optional

from loguru import logger

from app.database import SessionLocal
from app.models.database import Evaluator, JudgeDataset, JudgeRun, JudgeSample
from app.workers.config import celery_app


@celery_app.task(bind=True, max_retries=1, time_limit=3600, name="run_judge_alignment")
def run_judge_alignment_task(
    self,
    judge_run_id: str,
    sample_ids: Optional[List[str]] = None,
):
    """
    Execute a Judge Alignment run asynchronously.

    Args:
        judge_run_id: UUID (string) of the JudgeRun row.
        sample_ids: Optional explicit list of JudgeSample ids to score.
                    Used for "dev" / "test" splits. When None and the run's
                    `split` is "all", every labeled sample in the dataset
                    is evaluated.
    """
    from app.services.judge_alignment.judge_runner import (
        run_judge,
        select_samples_for_split,
    )

    db = SessionLocal()
    try:
        run = db.query(JudgeRun).filter(JudgeRun.id == judge_run_id).first()
        if not run:
            logger.error(f"[JudgeAlignment] Run {judge_run_id} not found")
            return {"error": "JudgeRun not found"}

        run.celery_task_id = self.request.id
        run.status = "running"
        db.commit()

        dataset = db.query(JudgeDataset).filter(JudgeDataset.id == run.dataset_id).first()
        if not dataset:
            _fail(db, run, "Parent JudgeDataset not found")
            return {"error": "Dataset not found"}

        if not run.evaluator_id:
            _fail(db, run, "JudgeRun has no evaluator_id")
            return {"error": "Missing evaluator"}

        evaluator = db.query(Evaluator).filter(Evaluator.id == run.evaluator_id).first()
        if not evaluator:
            _fail(db, run, "Evaluator not found")
            return {"error": "Evaluator not found"}

        samples: List[JudgeSample] = select_samples_for_split(
            dataset_id=run.dataset_id,
            split=run.split,
            db=db,
            sample_ids=sample_ids,
        )

        if not samples:
            _fail(
                db,
                run,
                "No labeled samples available for this split. Label more rows "
                "and try again.",
            )
            return {"error": "No samples"}

        try:
            metrics = run_judge(run, dataset, evaluator, samples, db)
        except Exception as exc:
            logger.error(
                f"[JudgeAlignment] Run {judge_run_id} crashed: {exc}",
                exc_info=True,
            )
            _fail(db, run, str(exc))
            return {"error": str(exc)}

        from app.services.billing.flexprice_service import (
            record_judge_alignment_run_completed,
        )

        record_judge_alignment_run_completed(
            run.organization_id,
            run.id,
            workspace_id=run.workspace_id,
            dataset_id=run.dataset_id,
            samples_scored=len(samples),
        )

        return {"judge_run_id": judge_run_id, "metrics": metrics}

    finally:
        db.close()


def _fail(db, run: JudgeRun, message: str) -> None:
    run.status = "failed"
    run.error_message = message
    db.commit()
    logger.error(f"[JudgeAlignment] Run {run.id} failed: {message}")
