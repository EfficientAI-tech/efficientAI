"""Celery tasks for agent flowchart generation and prompt-section mapping."""

from __future__ import annotations

from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import PromptPartial
from app.models.schemas import AgentFlowGraph
from app.services.agent_flowchart import (
    apply_prompt_hash_staleness,
    generate_agent_flowchart,
    map_all_flow_nodes_to_prompt,
)
from app.services.imported_agent_constants import partial_supports_flowchart
from app.workers.config import celery_app


def _supports_flowchart(partial: PromptPartial) -> bool:
    return partial_supports_flowchart(partial.tags if isinstance(partial.tags, list) else None)


@celery_app.task(name="generate_agent_flowchart", bind=True, max_retries=0)
def generate_agent_flowchart_task(
    self,
    partial_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
):
    db = SessionLocal()
    partial: PromptPartial | None = None
    try:
        partial = (
            db.query(PromptPartial)
            .filter(PromptPartial.id == UUID(partial_id))
            .first()
        )
        if partial is None:
            logger.error("Agent flowchart: partial {} not found", partial_id)
            return
        if not _supports_flowchart(partial):
            raise ValueError("Flowchart generation is not available for this prompt partial")
        if partial.agent_flowchart_status != "generating":
            logger.info(
                "Agent flowchart: partial {} no longer generating (status={}), skipping",
                partial_id,
                partial.agent_flowchart_status,
            )
            return

        from app.services.usage.context import (
            llm_usage_context,
            usage_context_for_prompt_partial,
        )

        with llm_usage_context(usage_context_for_prompt_partial(partial)):
            graph, provider_enum, model_str = generate_agent_flowchart(
                prompt_text=partial.content,
                organization_id=partial.organization_id,
                db=db,
                provider=provider,
                model=model,
            )
        partial.agent_flowchart = graph.model_dump(mode="json")
        if isinstance(partial.agent_flowchart, dict):
            generated_at = graph.generated_at
            if generated_at is not None:
                partial.agent_flowchart["generated_at"] = generated_at.isoformat()
            partial.agent_flowchart["provider"] = provider_enum.value
            partial.agent_flowchart["model"] = model_str
            partial.agent_flowchart.pop("mapping_error", None)
            partial.agent_flowchart.pop("generation_error", None)
        partial.agent_flowchart_status = "completed"
        flag_modified(partial, "agent_flowchart")
        db.commit()
        from app.services.billing.flexprice_service import record_prompt_partial_ai_assisted

        record_prompt_partial_ai_assisted(
            partial.organization_id,
            uuid4(),
            workspace_id=partial.workspace_id,
            mode="flowchart",
            partial_id=partial.id,
            model=model_str,
        )
        logger.info(
            "Agent flowchart completed for partial {} ({} nodes)",
            partial_id,
            len(graph.nodes),
        )
    except Exception as exc:
        logger.exception(
            "Agent flowchart failed for partial {}: {}",
            partial_id,
            exc,
        )
        if partial is not None:
            flowchart_payload = (
                partial.agent_flowchart if isinstance(partial.agent_flowchart, dict) else {}
            )
            partial.agent_flowchart = {
                **flowchart_payload,
                "generation_error": str(exc),
            }
            partial.agent_flowchart_status = "failed"
            flag_modified(partial, "agent_flowchart")
            db.commit()
    finally:
        db.close()


@celery_app.task(name="map_agent_flowchart_prompt_sections", bind=True, max_retries=0)
def map_agent_flowchart_prompt_sections_task(
    self,
    partial_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
):
    db = SessionLocal()
    partial: PromptPartial | None = None
    try:
        partial = (
            db.query(PromptPartial)
            .filter(PromptPartial.id == UUID(partial_id))
            .first()
        )
        if partial is None:
            logger.error("Agent flowchart mapping: partial {} not found", partial_id)
            return
        if not _supports_flowchart(partial):
            raise ValueError("Prompt mapping is not available for this prompt partial")
        if partial.agent_flowchart_status != "mapping":
            logger.info(
                "Agent flowchart mapping: partial {} no longer mapping (status={}), skipping",
                partial_id,
                partial.agent_flowchart_status,
            )
            return
        if not isinstance(partial.agent_flowchart, dict) or not partial.agent_flowchart.get(
            "nodes"
        ):
            raise ValueError("Generate a flowchart before mapping prompt sections")

        from app.services.usage.context import (
            llm_usage_context,
            usage_context_for_prompt_partial,
        )

        graph = apply_prompt_hash_staleness(
            AgentFlowGraph.model_validate(partial.agent_flowchart),
            partial.content,
        )
        with llm_usage_context(usage_context_for_prompt_partial(partial)):
            mapped_graph = map_all_flow_nodes_to_prompt(
                prompt_text=partial.content,
                graph=graph,
                organization_id=partial.organization_id,
                db=db,
                provider=provider,
                model=model,
            )
        partial.agent_flowchart = mapped_graph.model_dump(mode="json")
        if isinstance(partial.agent_flowchart, dict):
            if mapped_graph.generated_at is not None:
                partial.agent_flowchart["generated_at"] = mapped_graph.generated_at.isoformat()
            partial.agent_flowchart.pop("mapping_error", None)
        partial.agent_flowchart_status = "completed"
        flag_modified(partial, "agent_flowchart")
        db.commit()
        from app.services.billing.flexprice_service import record_prompt_partial_ai_assisted

        record_prompt_partial_ai_assisted(
            partial.organization_id,
            uuid4(),
            workspace_id=partial.workspace_id,
            mode="flowchart_map",
            partial_id=partial.id,
        )
        logger.info("Agent flowchart prompt mapping completed for partial {}", partial_id)
    except Exception as exc:
        logger.exception(
            "Agent flowchart prompt mapping failed for partial {}: {}",
            partial_id,
            exc,
        )
        if partial is not None:
            flowchart_payload = (
                partial.agent_flowchart if isinstance(partial.agent_flowchart, dict) else {}
            )
            partial.agent_flowchart = {
                **flowchart_payload,
                "mapping_error": str(exc),
            }
            partial.agent_flowchart_status = "completed"
            flag_modified(partial, "agent_flowchart")
            db.commit()
    finally:
        db.close()
