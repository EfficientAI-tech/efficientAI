"""LLM plumbing for red team runs: which model attacks / judges, and JSON calls."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Agent, RedTeamRun
from app.models.enums import ModelProvider
from app.services.agents.chat_llm_config import ResolvedSimulationLlm, resolve_simulation_llm
from app.services.usage.context import LLMUsageContext, LLMUsageProductSection

_JSON_TASK_DEFAULTS = {"temperature": 0.2, "max_tokens": 4096}
_ATTACK_TASK_DEFAULTS = {"temperature": 0.9, "max_tokens": 1024}


class RedTeamLlmError(RuntimeError):
    """The attacker / judge LLM could not produce usable output."""


@dataclass(frozen=True)
class RunLlms:
    attacker: ResolvedSimulationLlm
    judge: ResolvedSimulationLlm


def _override(provider: Optional[str], model: Optional[str], source: str) -> Optional[ResolvedSimulationLlm]:
    if not (provider or "").strip() or not (model or "").strip():
        return None
    return ResolvedSimulationLlm(
        provider=ModelProvider(provider.strip().lower()),
        model=model.strip(),
        llm_config=None,
        credential_id=None,
        source=source,
    )


def resolve_run_llms(
    db: Session,
    *,
    agent: Agent,
    attacker_provider: Optional[str] = None,
    attacker_model: Optional[str] = None,
    judge_provider: Optional[str] = None,
    judge_model: Optional[str] = None,
) -> RunLlms:
    """Attacker defaults to the agent's test LLM (the simulated caller); judge defaults to the attacker.

    Raises ``ValueError`` when the agent has no test LLM and no override is given.
    """
    attacker = _override(attacker_provider, attacker_model, "red_team_override")
    if attacker is None:
        attacker = resolve_simulation_llm(db, agent=agent, organization_id=agent.organization_id, leg="test")
    judge = _override(judge_provider, judge_model, "red_team_judge_override") or attacker
    return RunLlms(attacker=attacker, judge=judge)


def run_llms_for(db: Session, run: RedTeamRun, agent: Agent) -> RunLlms:
    return resolve_run_llms(
        db,
        agent=agent,
        attacker_provider=run.attacker_llm_provider,
        attacker_model=run.attacker_llm_model,
        judge_provider=run.judge_llm_provider,
        judge_model=run.judge_llm_model,
    )


def describe_run_llms(llms: RunLlms) -> dict[str, Any]:
    def _one(llm: ResolvedSimulationLlm) -> dict[str, Any]:
        return {"provider": llm.provider.value, "model": llm.model, "source": llm.source}

    return {"attacker": _one(llms.attacker), "judge": _one(llms.judge)}


def usage_context(run: RedTeamRun, *, leg: str, attack_id: Optional[UUID] = None) -> LLMUsageContext:
    extra = {"red_team_leg": leg, "agent_id": str(run.agent_id)}
    if attack_id:
        extra["red_team_attack_id"] = str(attack_id)
    return LLMUsageContext(
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        product_section=LLMUsageProductSection.RED_TEAM,
        resource_id=run.id,
        resource_type="red_team_run",
        extra=extra,
    )


def complete(
    db: Session,
    *,
    organization_id: UUID,
    llm: ResolvedSimulationLlm,
    messages: list[dict[str, str]],
    json_mode: bool = False,
) -> str:
    """One completion; raises ``RedTeamLlmError`` on empty output or refusal."""
    from app.services.ai.llm_service import llm_service

    try:
        result = llm_service.generate_response(
            messages=messages,
            llm_provider=llm.provider,
            llm_model=llm.model,
            organization_id=organization_id,
            db=db,
            llm_config=llm.llm_config,
            task_defaults=_JSON_TASK_DEFAULTS if json_mode else _ATTACK_TASK_DEFAULTS,
            credential_id=llm.credential_id,
        )
    except Exception as exc:  # provider / credential errors
        raise RedTeamLlmError(f"{llm.provider.value}/{llm.model} failed: {exc}") from exc
    text = (result.get("text") or "").strip()
    if not text:
        refusal = (result.get("refusal") or "").strip()
        raise RedTeamLlmError(
            f"{llm.provider.value}/{llm.model} returned no text"
            + (f" (refusal: {refusal})" if refusal else f" (finish_reason={result.get('finish_reason')})")
        )
    return text


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """First JSON object in ``text``; tolerates code fences, prose around it and truncation."""
    from app.workers.tasks.helpers.json_utils import repair_truncated_json

    cleaned = _FENCE_RE.sub("", (text or "").strip()).strip()
    start = cleaned.find("{")
    if start < 0:
        raise RedTeamLlmError("No JSON object in LLM output")
    candidate = cleaned[start:]
    end = candidate.rfind("}")
    for attempt in (candidate[: end + 1] if end >= 0 else None, candidate):
        if not attempt:
            continue
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    repaired = repair_truncated_json(candidate)
    if repaired:
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    raise RedTeamLlmError("Could not parse JSON from LLM output")


def complete_json(
    db: Session,
    *,
    organization_id: UUID,
    llm: ResolvedSimulationLlm,
    messages: list[dict[str, str]],
    retries: int = 2,
) -> dict[str, Any]:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            text = complete(db, organization_id=organization_id, llm=llm, messages=messages, json_mode=True)
            return parse_json_object(text)
        except RedTeamLlmError as exc:
            last_error = exc
            logger.warning("[RedTeam] JSON call failed (attempt {}/{}): {}", attempt + 1, retries, exc)
    raise RedTeamLlmError(str(last_error))
