"""Cost, model, and tool-call rollups for the evaluation results dashboard."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, Evaluator, EvaluatorResult, LLMUsageDaily
from app.models.schemas import (
    DashboardOpsAgentDay,
    DashboardOpsCostByAgent,
    DashboardOpsModelDay,
    DashboardOpsModelSpend,
    DashboardOpsToolAgentDay,
    DashboardOpsToolByTool,
    EvaluatorResultsDashboardOpsResponse,
)
from app.services.evaluators.evaluator_results_query import build_evaluator_results_query
from app.services.usage.context import LIVE_USAGE_SECTIONS, resolve_usage_role

_LAYER_KINDS = ("llm", "stt", "tts")
_MICRO = 1_000_000


@dataclass
class UsageSpendRow:
    product_section: str
    model: str
    usage_kind: str
    usage_date: date
    context: Dict[str, Any]
    total_cost_micro_usd: int


@dataclass
class ToolCallSource:
    agent_id: Optional[UUID]
    timestamp: Optional[datetime]
    call_data: Any


@dataclass
class _AgentCost:
    llm: int = 0
    stt: int = 0
    tts: int = 0
    by_role: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    models: Dict[Tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))


def _usd(micro: int) -> float:
    return round(micro / _MICRO, 6)


def _layer(kind: str) -> Optional[str]:
    normalized = (kind or "llm").lower()
    if normalized in _LAYER_KINDS:
        return normalized
    return None


def _context_dict(raw: Any) -> Dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _parse_uuid(raw: Any) -> Optional[UUID]:
    if isinstance(raw, UUID):
        return raw
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def usage_row_in_scope(
    row: UsageSpendRow,
    *,
    playground: bool,
    agent_id: Optional[UUID],
    scenario_ids: Optional[Set[str]],
) -> bool:
    """Keep spend that belongs to the selected Simulations or Live mode."""
    context = _context_dict(row.context)
    role = resolve_usage_role(row.product_section, context)
    if role is None:
        return False
    section = row.product_section or ""
    live = section in LIVE_USAGE_SECTIONS
    if playground != live:
        return False
    row_agent = _parse_uuid(context.get("agent_id"))
    if row_agent is None:
        return False
    if agent_id is not None and row_agent != agent_id:
        return False
    if scenario_ids is not None:
        scenario = str(context.get("scenario_id") or "")
        if not scenario or scenario not in scenario_ids:
            return False
    return True


def rollup_usage(
    rows: Iterable[UsageSpendRow],
    *,
    playground: bool,
    agent_id: Optional[UUID] = None,
    scenario_ids: Optional[Set[str]] = None,
    agent_names: Optional[Dict[UUID, str]] = None,
) -> Tuple[List[DashboardOpsCostByAgent], List[DashboardOpsModelDay], List[DashboardOpsAgentDay]]:
    names = agent_names or {}
    agents: Dict[UUID, _AgentCost] = defaultdict(_AgentCost)
    model_days: Dict[Tuple[date, str], int] = defaultdict(int)
    agent_days: Dict[Tuple[date, UUID, str], Dict[str, int]] = defaultdict(
        lambda: {"llm": 0, "stt": 0, "tts": 0}
    )

    for row in rows:
        if not usage_row_in_scope(
            row,
            playground=playground,
            agent_id=agent_id,
            scenario_ids=scenario_ids,
        ):
            continue
        layer = _layer(row.usage_kind)
        if layer is None or row.total_cost_micro_usd == 0:
            continue
        context = _context_dict(row.context)
        role = resolve_usage_role(row.product_section, context)
        owner = _parse_uuid(context.get("agent_id"))
        if role is None or owner is None:
            continue
        micro = int(row.total_cost_micro_usd)
        bucket = agents[owner]
        setattr(bucket, layer, getattr(bucket, layer) + micro)
        bucket.by_role[role] += micro
        model_name = row.model or "Unknown model"
        bucket.models[(model_name, role)] += micro
        model_days[(row.usage_date, model_name)] += micro
        agent_days[(row.usage_date, owner, role)][layer] += micro

    cost_by_agent: List[DashboardOpsCostByAgent] = []
    for owner, bucket in agents.items():
        total = bucket.llm + bucket.stt + bucket.tts
        models = [
            DashboardOpsModelSpend(model=model, role=role, cost_usd=_usd(micro))
            for (model, role), micro in bucket.models.items()
            if micro
        ]
        models.sort(key=lambda item: item.cost_usd, reverse=True)
        cost_by_agent.append(
            DashboardOpsCostByAgent(
                agent_id=owner,
                agent_name=names.get(owner, "Unknown agent"),
                llm_usd=_usd(bucket.llm),
                stt_usd=_usd(bucket.stt),
                tts_usd=_usd(bucket.tts),
                total_usd=_usd(total),
                agent_usd=_usd(bucket.by_role.get("agent", 0)),
                simulator_usd=_usd(bucket.by_role.get("simulator", 0)),
                judge_usd=_usd(bucket.by_role.get("judge", 0)),
                models=models,
            )
        )
    cost_by_agent.sort(key=lambda item: item.total_usd, reverse=True)

    cost_by_model_day = [
        DashboardOpsModelDay(day=day, model=model, cost_usd=_usd(micro))
        for (day, model), micro in model_days.items()
        if micro
    ]
    cost_by_model_day.sort(key=lambda item: (item.day, -item.cost_usd, item.model))

    cost_by_agent_day = [
        DashboardOpsAgentDay(
            day=day,
            agent_id=owner,
            role=role,
            llm_usd=_usd(layers["llm"]),
            stt_usd=_usd(layers["stt"]),
            tts_usd=_usd(layers["tts"]),
        )
        for (day, owner, role), layers in agent_days.items()
        if layers["llm"] or layers["stt"] or layers["tts"]
    ]
    cost_by_agent_day.sort(key=lambda item: (item.day, str(item.agent_id), item.role))
    return cost_by_agent, cost_by_model_day, cost_by_agent_day


def _tool_records(call_data: Any) -> List[Dict[str, Any]]:
    if not isinstance(call_data, dict):
        return []
    calls = call_data.get("tool_calls")
    if isinstance(calls, list) and calls:
        return [call for call in calls if isinstance(call, dict)]
    knowledge = call_data.get("knowledge_base_tool_calls")
    if isinstance(knowledge, list):
        return [call for call in knowledge if isinstance(call, dict)]
    return []


def _is_production_call(call: Dict[str, Any]) -> bool:
    return str(call.get("side") or "production") == "production"


def _is_error_call(call: Dict[str, Any]) -> bool:
    return str(call.get("status") or "") == "error"


def rollup_tool_calls(
    rows: Iterable[ToolCallSource],
    *,
    agent_names: Optional[Dict[UUID, str]] = None,
) -> Tuple[List[DashboardOpsToolAgentDay], List[DashboardOpsToolByTool]]:
    names = agent_names or {}
    by_day: Dict[Tuple[date, UUID], Dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0})
    by_tool: Dict[Tuple[UUID, str], Dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0})

    for row in rows:
        if row.agent_id is None or row.timestamp is None:
            continue
        day = row.timestamp.date()
        for call in _tool_records(row.call_data):
            if not _is_production_call(call):
                continue
            error = _is_error_call(call)
            day_bucket = by_day[(day, row.agent_id)]
            day_bucket["calls"] += 1
            if error:
                day_bucket["errors"] += 1
            tool = str(call.get("tool") or "tool")
            tool_bucket = by_tool[(row.agent_id, tool)]
            tool_bucket["calls"] += 1
            if error:
                tool_bucket["errors"] += 1

    agent_days = [
        DashboardOpsToolAgentDay(
            day=day,
            agent_id=owner,
            agent_name=names.get(owner, "Unknown agent"),
            calls=counts["calls"],
            errors=counts["errors"],
        )
        for (day, owner), counts in by_day.items()
        if counts["calls"]
    ]
    agent_days.sort(key=lambda item: (item.day, item.agent_name.lower()))
    tools = [
        DashboardOpsToolByTool(
            agent_id=owner,
            agent_name=names.get(owner, "Unknown agent"),
            tool=tool,
            calls=counts["calls"],
            errors=counts["errors"],
        )
        for (owner, tool), counts in by_tool.items()
        if counts["calls"]
    ]
    tools.sort(key=lambda item: (item.agent_name.lower(), -item.calls, item.tool))
    return agent_days, tools


def _scenario_ids_for_filter(
    db: Session,
    *,
    suite_id: Optional[UUID],
    scenario_id: Optional[UUID],
) -> Optional[Set[str]]:
    if suite_id is None and scenario_id is None:
        return None
    allowed: Set[str] = set()
    if suite_id is not None:
        rows = (
            db.query(Evaluator.scenario_id)
            .filter(Evaluator.suite_id == suite_id, Evaluator.scenario_id.isnot(None))
            .all()
        )
        allowed.update(str(row[0]) for row in rows)
    if scenario_id is not None:
        scenario = str(scenario_id)
        if suite_id is None:
            return {scenario}
        return {scenario} if scenario in allowed else set()
    return allowed


def _usage_day(value: Optional[datetime]) -> Optional[date]:
    if value is None:
        return None
    return value.date()


def compute_evaluator_results_dashboard_ops(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    suite_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    playground: Optional[bool] = None,
) -> EvaluatorResultsDashboardOpsResponse:
    live = playground is True
    scenario_ids = _scenario_ids_for_filter(db, suite_id=suite_id, scenario_id=scenario_id)
    start_day = _usage_day(since)
    end_day = _usage_day(until)

    usage_query = db.query(LLMUsageDaily).filter(
        LLMUsageDaily.organization_id == organization_id,
        LLMUsageDaily.workspace_id == workspace_id,
    )
    if start_day is not None:
        usage_query = usage_query.filter(LLMUsageDaily.usage_date >= start_day)
    if end_day is not None:
        usage_query = usage_query.filter(LLMUsageDaily.usage_date <= end_day)

    usage_rows = [
        UsageSpendRow(
            product_section=row.product_section,
            model=row.model,
            usage_kind=row.usage_kind,
            usage_date=row.usage_date,
            context=_context_dict(row.context),
            total_cost_micro_usd=int(row.total_cost_micro_usd or 0),
        )
        for row in usage_query.all()
    ]

    result_query = build_evaluator_results_query(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=str(agent_id) if agent_id else None,
        suite_id=str(suite_id) if suite_id else None,
        scenario_id=str(scenario_id) if scenario_id else None,
        since=since,
        until=until,
        playground=playground,
    )
    tool_rows = [
        ToolCallSource(agent_id=agent_id, timestamp=timestamp, call_data=call_data)
        for agent_id, timestamp, call_data in result_query.with_entities(
            EvaluatorResult.agent_id,
            EvaluatorResult.timestamp,
            EvaluatorResult.call_data,
        ).all()
    ]

    agent_ids = {row.agent_id for row in tool_rows if row.agent_id}
    for spend in usage_rows:
        parsed = _parse_uuid(_context_dict(spend.context).get("agent_id"))
        if parsed:
            agent_ids.add(parsed)
    agent_names: Dict[UUID, str] = {}
    if agent_ids:
        for agent in db.query(Agent).filter(Agent.id.in_(agent_ids)).all():
            agent_names[agent.id] = agent.name or "Unknown agent"

    cost_by_agent, cost_by_model_day, cost_by_agent_day = rollup_usage(
        usage_rows,
        playground=live,
        agent_id=agent_id,
        scenario_ids=scenario_ids,
        agent_names=agent_names,
    )
    tool_by_day, tool_by_tool = rollup_tool_calls(tool_rows, agent_names=agent_names)
    return EvaluatorResultsDashboardOpsResponse(
        cost_by_agent=cost_by_agent,
        cost_by_model_day=cost_by_model_day,
        cost_by_agent_day=cost_by_agent_day,
        tool_calls_by_agent_day=tool_by_day,
        tool_calls_by_tool=tool_by_tool,
    )
