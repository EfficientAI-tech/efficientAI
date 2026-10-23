"""DB side of a Harbor trial: one ``EvaluatorResult`` per trial (synchronous)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.database import (
    Agent,
    EvaluatorResult,
    EvaluatorResultStatus,
    Persona,
    Scenario,
    SimulationRun,
)
from app.models.enums import ModelProvider
from app.services.agents.chat_llm_config import ResolvedSimulationLlm
from app.services.agents.chat_production_leg import uses_live_production_leg
from app.services.evaluators.evaluator_run_service import generate_unique_result_id
from app.services.harbor.rewards import AGGREGATE_REWARD_KEY, compute_rewards, metric_reward_key
from app.services.harbor.tool_checks import check_tool_calls
from app.services.live_entity_storage import sync_evaluator_result
from app.services.testing.llm_to_llm_evaluator_simulation import (
    TextConversation,
    run_text_conversation,
    write_conversation_to_result,
)
from app.services.testing.simulation_llms import describe_simulation_llms
from app.services.testing.simulation_prompts import build_agent_system_prompt
from app.services.usage.context import (
    LLMUsageContext,
    LLMUsageProductSection,
    usage_context_for_test_agent_simulation,
)

ATIF_SCHEMA_VERSION = "ATIF-v1.7"
TRAJECTORY_AGENT_NAME = "efficientai-conversation"
TRAJECTORY_AGENT_VERSION = "1.0.0"


@dataclass(frozen=True)
class TrialRefs:
    simulation_run_id: UUID
    scenario_id: UUID
    persona_id: UUID
    trial_name: str


def llm_override(provider: Optional[str], model: Optional[str]) -> Optional[ResolvedSimulationLlm]:
    if not (provider or "").strip() or not (model or "").strip():
        return None
    return ResolvedSimulationLlm(
        provider=ModelProvider(provider.strip().lower()),
        model=model.strip(),
        llm_config=None,
        credential_id=None,
        source="simulation_run_override",
    )


def _commit(db: Session, result: EvaluatorResult) -> None:
    sync_evaluator_result(db, result)
    db.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atif_tool_fields(step_id: int, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """ATIF ``tool_calls`` + ``observation`` for one agent step from our call records."""
    atif_calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for index, call in enumerate(tool_calls, start=1):
        call_id = str(call.get("call_id") or f"call_{step_id}_{index}")
        atif_calls.append(
            {
                "tool_call_id": call_id,
                "function_name": str(call.get("tool") or "unknown"),
                "arguments": call.get("arguments") or {},
                "extra": {
                    "provider": call.get("provider"),
                    "status": call.get("status"),
                    "latency_ms": call.get("latency_ms"),
                },
            }
        )
        results.append(
            {
                "source_call_id": call_id,
                "content": call.get("result_preview") or "",
                "extra": {"status": call.get("status")},
            }
        )
    return {"tool_calls": atif_calls, "observation": {"results": results}}


class TrajectoryWriter:
    """Writes an ATIF trajectory (user = test agent, agent = production agent) after every turn."""

    def __init__(self, path: Path, *, model_name: Optional[str], extra: dict[str, Any]):
        self.path = path
        self.model_name = model_name
        self.extra = extra
        self.steps: list[dict[str, Any]] = []

    def add(
        self,
        source: str,
        message: str,
        *,
        latency_seconds: Optional[float] = None,
        tool_calls: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        step_id = len(self.steps) + 1
        step: dict[str, Any] = {
            "step_id": step_id,
            "timestamp": _now_iso(),
            "source": source,
            "message": message,
        }
        if source == "agent" and self.model_name:
            step["model_name"] = self.model_name
        if source == "agent" and tool_calls:
            step.update(_atif_tool_fields(step_id, tool_calls))
        if latency_seconds is not None:
            step["extra"] = {"latency_ms": round(latency_seconds * 1000)}
        self.steps.append(step)
        self.flush()

    def flush(self) -> None:
        payload = {
            "schema_version": ATIF_SCHEMA_VERSION,
            "agent": {
                "name": TRAJECTORY_AGENT_NAME,
                "version": TRAJECTORY_AGENT_VERSION,
                "model_name": self.model_name,
                "extra": self.extra,
            },
            "steps": self.steps,
            "final_metrics": {"total_steps": len(self.steps)},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n")


def _load_trial_entities(db: Session, refs: TrialRefs):
    run = db.query(SimulationRun).filter(SimulationRun.id == refs.simulation_run_id).first()
    if not run:
        raise ValueError(f"Simulation run {refs.simulation_run_id} not found")
    agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
    persona = db.query(Persona).filter(Persona.id == refs.persona_id).first()
    scenario = db.query(Scenario).filter(Scenario.id == refs.scenario_id).first()
    if not agent or not persona or not scenario:
        raise ValueError("Agent, persona or scenario for this trial no longer exists")
    return run, agent, persona, scenario


def upsert_trial_result(
    db: Session,
    *,
    run: SimulationRun,
    persona: Persona,
    scenario: Scenario,
    trial_name: str,
) -> EvaluatorResult:
    """Create the trial's result row, or reset it when Harbor retries the same trial."""
    result = (
        db.query(EvaluatorResult)
        .filter(
            EvaluatorResult.simulation_run_id == run.id,
            EvaluatorResult.harbor_trial_name == trial_name,
        )
        .first()
    )
    if result is None:
        result = EvaluatorResult(
            result_id=generate_unique_result_id(db),
            organization_id=run.organization_id,
            workspace_id=run.workspace_id,
            agent_id=run.agent_id,
            persona_id=persona.id,
            scenario_id=scenario.id,
            simulation_run_id=run.id,
            harbor_trial_name=trial_name,
            name=scenario.name,
            created_by=run.created_by,
        )
        db.add(result)
    result.status = EvaluatorResultStatus.CALL_IN_PROGRESS.value
    result.provider_platform = "internal"
    result.error_message = None
    result.transcription = None
    result.speaker_segments = None
    result.metric_scores = None
    result.call_data = None
    result.reward = None
    result.passed = None
    _commit(db, result)
    return result


def run_trial_conversation(
    db: Session,
    *,
    refs: TrialRefs,
    trajectory_path: Path,
    production_override: Optional[ResolvedSimulationLlm],
    test_override: Optional[ResolvedSimulationLlm],
) -> dict[str, Any]:
    """Run one test-agent ↔ production-agent conversation for a Harbor trial."""
    run, agent, persona, scenario = _load_trial_entities(db, refs)
    result = upsert_trial_result(
        db, run=run, persona=persona, scenario=scenario, trial_name=refs.trial_name
    )
    ids = {
        "agent_id": str(agent.id),
        "persona_id": str(persona.id),
        "scenario_id": str(scenario.id),
        "evaluator_result_id": str(result.id),
        "simulation_run_id": str(run.id),
    }
    caller_ctx = usage_context_for_test_agent_simulation(
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        evaluator_result_id=result.id,
        provider_platform="internal",
    )
    agent_ctx = LLMUsageContext(
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        product_section=LLMUsageProductSection.EVALUATORS,
        resource_id=run.id,
        resource_type="simulation_run",
        extra={
            **ids,
            "synthetic_testing": "pre_prod",
            "simulation_leg": "production_agent",
            "provider_platform": "internal",
        },
    )
    production_model = (
        f"{production_override.provider.value}/{production_override.model}"
        if production_override
        else (f"{agent.main_llm_provider}/{agent.main_llm_model}" if agent.main_llm_model else None)
    )
    writer = TrajectoryWriter(trajectory_path, model_name=production_model, extra=ids)
    if not uses_live_production_leg(agent):
        writer.add("system", build_agent_system_prompt(agent))

    conversation = TextConversation()
    trial_call_data = {
        "simulation_run_id": str(run.id),
        "harbor_trial_name": refs.trial_name,
        "llms": describe_simulation_llms(
            db, agent=agent, production_override=production_override, test_override=test_override
        ),
    }

    def _on_turn(entry: dict[str, Any], latency_seconds: float) -> None:
        source = "agent" if entry["speaker"] == "Speaker 2" else "user"
        writer.add(
            source,
            entry["text"],
            latency_seconds=latency_seconds,
            tool_calls=entry.get("tool_calls"),
        )
        write_conversation_to_result(
            result, conversation, agent=agent, extra_call_data=trial_call_data
        )
        _commit(db, result)

    try:
        run_text_conversation(
            agent=agent,
            persona=persona,
            scenario=scenario,
            organization_id=run.organization_id,
            db=db,
            conversation=conversation,
            caller_ctx=caller_ctx,
            agent_ctx=agent_ctx,
            evaluator_result=result,
            test_llm_override=test_override,
            production_llm_override=production_override,
            on_turn=_on_turn,
        )
    except Exception as exc:
        db.rollback()
        if conversation.transcript:
            write_conversation_to_result(
                result, conversation, agent=agent, extra_call_data=trial_call_data
            )
        result.status = EvaluatorResultStatus.FAILED.value
        result.error_message = str(exc)
        _commit(db, result)
        raise

    write_conversation_to_result(result, conversation, agent=agent, extra_call_data=trial_call_data)
    result.call_data["partial"] = False
    result.status = EvaluatorResultStatus.EVALUATING.value
    _commit(db, result)
    return {**ids, "exchanges": conversation.exchanges, "turns": len(conversation.transcript)}


def score_trial(
    db: Session,
    *,
    simulation_run_id: UUID,
    trial_name: str,
    pass_threshold: float,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Score a trial's transcript with platform metrics; returns Harbor rewards + details."""
    from app.workers.tasks.process_evaluator_result import evaluate_transcript_metrics

    result = (
        db.query(EvaluatorResult)
        .filter(
            EvaluatorResult.simulation_run_id == simulation_run_id,
            EvaluatorResult.harbor_trial_name == trial_name,
        )
        .first()
    )
    if result is None or not (result.transcription or "").strip():
        raise ValueError(f"No transcript recorded for trial {trial_name}")
    run = db.query(SimulationRun).filter(SimulationRun.id == simulation_run_id).first()
    agent = db.query(Agent).filter(Agent.id == result.agent_id).first()
    persona = db.query(Persona).filter(Persona.id == result.persona_id).first()
    scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()

    metric_scores, metrics = evaluate_transcript_metrics(
        db,
        result=result,
        agent=agent,
        persona=persona,
        scenario=scenario,
        metric_ids=run.metric_ids if run else None,
    )
    criteria = (run.metric_success_criteria if run else None) or []
    if criteria:
        from app.models.database import Metric
        from app.services.metrics.evaluation_scope import (
            load_agent_link_map,
            load_scenario_link_map,
            metric_applies_to_agent,
            metric_applies_to_scenario,
        )

        parent_ids = {UUID(str(c["metric_id"])) for c in criteria if c.get("metric_id")}
        parents = (
            db.query(Metric)
            .filter(
                Metric.id.in_(parent_ids),
                Metric.organization_id == result.organization_id,
            )
            .all()
        )
        agent_link_map = load_agent_link_map(db, parent_ids)
        scenario_link_map = load_scenario_link_map(db, parent_ids)
        parents_by_id = {p.id: p for p in parents}
        filtered: list[dict] = []
        for c in criteria:
            raw_id = c.get("metric_id")
            if not raw_id:
                continue
            parent = parents_by_id.get(UUID(str(raw_id)))
            if parent is None:
                continue
            if not metric_applies_to_agent(
                parent,
                result.agent_id,
                link_map=agent_link_map,
            ):
                continue
            if not metric_applies_to_scenario(
                parent,
                result.scenario_id,
                link_map=scenario_link_map,
            ):
                continue
            filtered.append(c)
        criteria = filtered
    if criteria:
        from app.services.harbor.success_criteria import (
            _load_metric_context,
            apply_success_criteria,
        )

        metric_ids_for_ctx = [str(c.get("metric_id")) for c in criteria if c.get("metric_id")]
        metrics_by_id, children_by_parent = _load_metric_context(
            db, agent.organization_id, metric_ids_for_ctx
        )
        trial_passed, aggregate, metric_scores = apply_success_criteria(
            metric_scores,
            criteria,
            metrics_by_id,
            children_by_parent,
        )
        _, rewards, metric_ids_by_key = compute_rewards(metric_scores, metrics)
        result.passed = trial_passed
        result.error_message = (
            None if aggregate is not None else "No metrics apply to this trial"
        )
    else:
        aggregate, rewards, metric_ids_by_key = compute_rewards(metric_scores, metrics)
        result.passed = aggregate is not None and aggregate >= pass_threshold
        result.error_message = (
            None if aggregate is not None else "No metrics apply to this trial"
        )

    tool_report = check_tool_calls(
        (result.call_data or {}).get("tool_calls"),
        getattr(scenario, "expected_tool_calls", None),
    )
    taken = {AGGREGATE_REWARD_KEY, *rewards}
    for name, value in tool_report.rewards().items():
        rewards[metric_reward_key(name, taken)] = value
    if tool_report.has_expectations:
        # Expected tool calls gate the pass; with no scorable metrics they are the score.
        if aggregate is None:
            aggregate = tool_report.expectation_score
            result.error_message = None
            result.passed = tool_report.all_expectations_met
        else:
            result.passed = bool(result.passed) and tool_report.all_expectations_met
    call_data = dict(result.call_data or {})
    call_data["tool_evaluation"] = tool_report.as_dict()
    result.call_data = call_data

    result.metric_scores = metric_scores
    flag_modified(result, "metric_scores")
    flag_modified(result, "call_data")
    result.reward = aggregate
    result.status = EvaluatorResultStatus.COMPLETED.value
    _commit(db, result)
    logger.info(
        "[Harbor] Trial {} scored reward={} passed={} ({} metrics)",
        trial_name,
        aggregate,
        result.passed,
        len(rewards),
    )
    details = {
        "evaluator_result_id": str(result.id),
        "pass_threshold": pass_threshold,
        "passed": result.passed,
        "metric_ids": metric_ids_by_key,
        "metric_scores": metric_scores,
        "tool_evaluation": tool_report.as_dict(),
    }
    return {AGGREGATE_REWARD_KEY: aggregate if aggregate is not None else 0.0, **rewards}, details
