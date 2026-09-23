"""Celery task: run evaluator (bridge test agent to voice AI and record conversation)."""

import asyncio
import time
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import EvaluatorResult, EvaluatorResultStatus

from app.workers.config import celery_app


@celery_app.task(name="run_evaluator", bind=True, max_retries=3)
def run_evaluator_task(self, evaluator_id: str, evaluator_result_id: str):
    """
    Celery task to run an evaluator: bridge test agent to Voice AI agent and record conversation.

    Args:
        self: Task instance
        evaluator_id: Evaluator ID as string
        evaluator_result_id: Pre-created EvaluatorResult ID as string

    Returns:
        Dictionary with execution results
    """
    db = SessionLocal()
    task_start_time = time.time()

    try:
        from app.models.database import Evaluator, Agent
        from app.services.testing.test_agent_bridge_service import test_agent_bridge_service

        evaluator_uuid = UUID(evaluator_id)
        result_uuid = UUID(evaluator_result_id)

        evaluator = db.query(Evaluator).filter(Evaluator.id == evaluator_uuid).first()
        if not evaluator:
            logger.error(f"[RunEvaluator {evaluator_id}] Evaluator not found")
            return {"error": "Evaluator not found"}

        result = db.query(EvaluatorResult).filter(EvaluatorResult.id == result_uuid).first()
        if not result:
            logger.error(f"[RunEvaluator {evaluator_id}] EvaluatorResult not found")
            return {"error": "EvaluatorResult not found"}

        agent = db.query(Agent).filter(Agent.id == evaluator.agent_id).first()
        if not agent:
            logger.error(f"[RunEvaluator {evaluator_id}] Agent not found")
            result.status = EvaluatorResultStatus.FAILED.value
            result.error_message = "Agent not found"
            db.commit()
            return {"error": "Agent not found"}

        logger.info(f"[RunEvaluator {evaluator.evaluator_id}] Starting task (Result: {result.result_id})")

        result.celery_task_id = self.request.id
        if result.status != EvaluatorResultStatus.QUEUED.value:
            logger.warning(f"[RunEvaluator {evaluator.evaluator_id}] Status was {result.status}, expected QUEUED")
        db.commit()

        has_voice_bundle = agent.voice_bundle_id is not None
        has_voice_ai_integration = (
            agent.voice_ai_integration_id is not None and agent.voice_ai_agent_id is not None
        )
        from app.services.agents.chat_llm_config import (
            agent_has_chat_simulation_config,
            should_use_llm_text_simulation,
        )

        call_medium = (agent.call_medium or "phone_call").lower()
        use_llm_text_simulation = should_use_llm_text_simulation(
            agent,
            has_voice_bundle=has_voice_bundle,
            has_voice_ai_integration=has_voice_ai_integration,
        )

        if has_voice_bundle and has_voice_ai_integration and not use_llm_text_simulation:
            try:
                result.status = EvaluatorResultStatus.CALL_INITIATING.value
                result.call_event = "task_started"
                db.commit()

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    bridge_result = loop.run_until_complete(
                        test_agent_bridge_service.bridge_test_agent_to_voice_agent(
                            evaluator_id=evaluator_uuid,
                            evaluator_result_id=result_uuid,
                            organization_id=evaluator.organization_id,
                            db=db,
                        )
                    )
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)

                db.refresh(result)

                if result.error_message and result.error_message.startswith("call_id:"):
                    pass

                db.commit()

                return {
                    "evaluator_id": evaluator_id,
                    "result_id": evaluator_result_id,
                    "status": "initiated",
                    "bridge_result": bridge_result,
                }

            except Exception as bridge_error:
                logger.error(
                    f"[RunEvaluator {evaluator.evaluator_id}] Bridge service error: {bridge_error}",
                    exc_info=True,
                )
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = str(bridge_error)
                result.call_event = "bridge_error"
                db.commit()
                raise

        elif use_llm_text_simulation:
            from app.models.database import Persona, Scenario
            from app.services.testing.llm_to_llm_evaluator_simulation import (
                run_llm_to_llm_evaluator_simulation,
            )

            persona = (
                db.query(Persona).filter(Persona.id == evaluator.persona_id).first()
                if evaluator.persona_id
                else None
            )
            scenario = (
                db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
                if evaluator.scenario_id
                else None
            )
            if not persona or not scenario:
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = "Evaluator requires persona and scenario for voice-bundle simulation"
                db.commit()
                return {"error": "Missing persona or scenario"}

            try:
                result.status = EvaluatorResultStatus.CALL_INITIATING.value
                result.call_event = "llm_simulation_started"
                db.commit()

                run_llm_to_llm_evaluator_simulation(
                    evaluator=evaluator,
                    result=result,
                    agent=agent,
                    persona=persona,
                    scenario=scenario,
                    organization_id=evaluator.organization_id,
                    db=db,
                )
                result.status = EvaluatorResultStatus.QUEUED.value
                result.call_event = "llm_simulation_completed"
                db.commit()

                from app.workers.celery_app import process_evaluator_result_task

                task = process_evaluator_result_task.delay(str(result.id))
                result.celery_task_id = task.id
                db.commit()

                return {
                    "evaluator_id": evaluator_id,
                    "result_id": evaluator_result_id,
                    "status": "simulated",
                    "provider_platform": "internal",
                }
            except Exception as sim_error:
                logger.error(
                    f"[RunEvaluator {evaluator.evaluator_id}] LLM simulation error: {sim_error}",
                    exc_info=True,
                )
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = str(sim_error)
                result.call_event = "llm_simulation_error"
                db.commit()
                raise

        else:
            logger.error(f"[RunEvaluator {evaluator.evaluator_id}] Agent missing required configuration")
            result.status = EvaluatorResultStatus.FAILED.value
            has_main_llm = agent_has_chat_simulation_config(agent)
            result.error_message = (
                "Agent missing required configuration for this run. "
                f"call_medium={call_medium}, main_llm_connection={has_main_llm}, "
                f"voice_bundle={has_voice_bundle}, voice_ai_integration={has_voice_ai_integration}. "
                "Chat agents need call_medium=chat with main LLM on the connection layer "
                "(or restart Celery workers after upgrading). Voice agents need a voice bundle or integration."
            )
            result.call_event = "configuration_error"
            db.commit()
            return {"error": "Agent does not have required configuration for bridging"}

    except Exception as exc:
        logger.error(f"[RunEvaluator {evaluator_id}] Task failed: {exc}", exc_info=True)
        try:
            result = db.query(EvaluatorResult).filter(
                EvaluatorResult.id == UUID(evaluator_result_id)
            ).first()
            if result:
                result.status = EvaluatorResultStatus.FAILED.value
                result.error_message = str(exc)
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
