"""
Celery task: Run a GEPA prompt optimization for a voice agent.

Loads the optimization run config, collects training data from historical
evaluator results, invokes GEPAOptimizationService, and persists the
resulting candidates back to the database.
"""

from loguru import logger

from app.workers.config import celery_app
from app.database import SessionLocal
from app.models.database import (
    Agent,
    AIProvider,
    Evaluator,
    EvaluatorResult,
    Metric,
    PromptOptimizationCandidate,
    PromptOptimizationRun,
    VoiceBundle,
)
from app.models.enums import PromptOptimizationStatus


@celery_app.task(bind=True, max_retries=1, time_limit=3600, name="run_prompt_optimization")
def run_prompt_optimization_task(self, optimization_run_id: str):
    """
    Execute a GEPA prompt optimization run asynchronously.

    Args:
        optimization_run_id: UUID (as string) of the PromptOptimizationRun row.
    """
    db = SessionLocal()
    try:
        run = db.query(PromptOptimizationRun).filter(
            PromptOptimizationRun.id == optimization_run_id
        ).first()
        if not run:
            logger.error(f"[GEPA] Optimization run {optimization_run_id} not found")
            return

        run.status = PromptOptimizationStatus.RUNNING.value
        db.commit()

        agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
        if not agent:
            _fail_run(db, run, "Agent not found")
            return

        evaluator = None
        if run.evaluator_id:
            evaluator = db.query(Evaluator).filter(Evaluator.id == run.evaluator_id).first()

        voice_bundle = None
        if run.voice_bundle_id:
            voice_bundle = db.query(VoiceBundle).filter(VoiceBundle.id == run.voice_bundle_id).first()
        elif agent.voice_bundle_id:
            voice_bundle = db.query(VoiceBundle).filter(VoiceBundle.id == agent.voice_bundle_id).first()

        training_data = (
            db.query(EvaluatorResult)
            .filter(
                EvaluatorResult.organization_id == run.organization_id,
                EvaluatorResult.agent_id == run.agent_id,
                EvaluatorResult.transcription.isnot(None),
                EvaluatorResult.status == "completed",
            )
            .order_by(EvaluatorResult.created_at.desc())
            .limit(50)
            .all()
        )

        if not training_data:
            _fail_run(db, run, "No completed evaluator results with transcripts found for this agent")
            return

        enabled_metrics = (
            db.query(Metric)
            .filter(Metric.organization_id == run.organization_id, Metric.enabled == True)
            .all()
        )
        if not enabled_metrics:
            _fail_run(db, run, "No enabled metrics found for this organization")
            return

        ai_providers = (
            db.query(AIProvider)
            .filter(AIProvider.organization_id == run.organization_id, AIProvider.is_active == True)
            .all()
        )

        from app.services.optimization import run_optimization

        result = run_optimization(
            agent=agent,
            evaluator=evaluator,
            voice_bundle=voice_bundle,
            training_data=training_data,
            metrics=enabled_metrics,
            ai_providers=ai_providers,
            organization_id=run.organization_id,
            db=db,
            config=run.config,
        )

        run.best_prompt = result["best_candidate"]
        run.best_score = result["best_score"]
        run.metric_history = result["metric_history"]
        run.reflection_trace = None
        run.num_metric_calls = result.get("total_metric_calls") or len(result.get("metric_history", []))
        run.status = PromptOptimizationStatus.COMPLETED.value

        for i, cand in enumerate(result.get("candidates", [])):
            db.add(PromptOptimizationCandidate(
                optimization_run_id=run.id,
                prompt_text=cand["prompt_text"],
                score=cand.get("score"),
                reflection_summary=cand.get("reflection_summary"),
            ))

        db.commit()
        logger.info(
            f"[GEPA] Optimization run {optimization_run_id} completed. "
            f"Best score: {run.best_score}"
        )

    except Exception as e:
        logger.error(f"[GEPA] Optimization run {optimization_run_id} failed: {e}", exc_info=True)
        try:
            run = db.query(PromptOptimizationRun).filter(
                PromptOptimizationRun.id == optimization_run_id
            ).first()
            if run:
                _fail_run(db, run, str(e))
        except Exception:
            pass
    finally:
        db.close()


def _fail_run(db, run: PromptOptimizationRun, message: str):
    run.status = PromptOptimizationStatus.FAILED.value
    run.error_message = message
    db.commit()
    logger.error(f"[GEPA] Run {run.id} failed: {message}")
