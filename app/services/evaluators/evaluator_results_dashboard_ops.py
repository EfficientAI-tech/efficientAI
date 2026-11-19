"""Cost, model, and tool-call rollups for the evaluation results dashboard."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import (
    Agent,
    CallRecording,
    CallRecordingSource,
    Evaluator,
    EvaluatorResult,
    LLMUsageDaily,
    VoiceBundle,
)
from app.models.schemas import (
    DashboardOpsAgentDay,
    DashboardOpsAgentMetricCount,
    DashboardOpsCostByAgent,
    DashboardOpsDurationBucket,
    DashboardOpsModelDay,
    DashboardOpsModelLayer,
    DashboardOpsModelSpend,
    DashboardOpsProviderAgent,
    DashboardOpsProviderDay,
    DashboardOpsProviderTotal,
    DashboardOpsRunDay,
    DashboardOpsScenarioMetricMean,
    DashboardOpsScoreDay,
    DashboardOpsToolAgentDay,
    DashboardOpsToolByTool,
    DashboardOpsToolCallsPerRun,
    EvaluatorResultsDashboardOpsResponse,
)
from app.services.evaluators.evaluator_results_query import build_evaluator_results_query
from app.services.usage.context import LIVE_USAGE_SECTIONS, resolve_usage_role

_LAYER_KINDS = ("llm", "stt", "tts")
_DURATION_BUCKET_EDGES = (0, 60, 90, 120, 150, 180, 240, 86_400)


def _duration_buckets_from_query(result_query) -> List[DashboardOpsDurationBucket]:
    edges = _DURATION_BUCKET_EDGES
    counts = [0] * (len(edges) - 1)
    for (duration,) in result_query.with_entities(EvaluatorResult.duration_seconds).all():
        if duration is None:
            continue
        value = float(duration)
        for index in range(len(edges) - 1):
            if edges[index] <= value < edges[index + 1]:
                counts[index] += 1
                break
    return [
        DashboardOpsDurationBucket(
            start_seconds=edges[index],
            end_seconds=edges[index + 1],
            count=counts[index],
        )
        for index in range(len(counts))
        if counts[index] > 0
    ]
_MICRO = 1_000_000
_OPS_CACHE_TTL_SECONDS = 90
_OPS_CACHE_HISTORICAL_TTL_SECONDS = 900
_ops_redis_client = None


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
    result_id: Optional[UUID] = None


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
    suite_agent_scenarios: Optional[Set[tuple[UUID, str]]] = None,
    playground_result_ids: Optional[Set[UUID]] = None,
) -> bool:
    """Keep spend that belongs to the selected Simulations or Live mode."""
    context = _context_dict(row.context)
    explicit = _parse_uuid(context.get("evaluator_result_id"))
    if explicit is not None and playground_result_ids is not None:
        if (explicit in playground_result_ids) != playground:
            return False
    else:
        role = resolve_usage_role(row.product_section, context)
        if role is None:
            return False
        section = row.product_section or ""
        live = section in LIVE_USAGE_SECTIONS
        if playground != live:
            return False
    role = resolve_usage_role(row.product_section, context)
    if role is None:
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
    if suite_agent_scenarios is not None:
        scenario = str(context.get("scenario_id") or "")
        if not scenario or (row_agent, scenario) not in suite_agent_scenarios:
            return False
    return True


def rollup_usage(
    rows: Iterable[UsageSpendRow],
    *,
    playground: bool,
    agent_id: Optional[UUID] = None,
    scenario_ids: Optional[Set[str]] = None,
    suite_agent_scenarios: Optional[Set[tuple[UUID, str]]] = None,
    agent_names: Optional[Dict[UUID, str]] = None,
    playground_result_ids: Optional[Set[UUID]] = None,
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
            suite_agent_scenarios=suite_agent_scenarios,
            playground_result_ids=playground_result_ids,
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


def rollup_model_layers(
    rows: Iterable[UsageSpendRow],
    *,
    playground: bool,
    agent_id: Optional[UUID] = None,
    scenario_ids: Optional[Set[str]] = None,
    suite_agent_scenarios: Optional[Set[tuple[UUID, str]]] = None,
    playground_result_ids: Optional[Set[UUID]] = None,
) -> List[DashboardOpsModelLayer]:
    totals: Dict[Tuple[str, str], int] = defaultdict(int)
    for row in rows:
        if not usage_row_in_scope(
            row,
            playground=playground,
            agent_id=agent_id,
            scenario_ids=scenario_ids,
            suite_agent_scenarios=suite_agent_scenarios,
            playground_result_ids=playground_result_ids,
        ):
            continue
        layer = _layer(row.usage_kind)
        if layer is None or row.total_cost_micro_usd == 0:
            continue
        totals[(row.model or "Unknown model", layer)] += int(row.total_cost_micro_usd)
    layers = [
        DashboardOpsModelLayer(model=model, usage_kind=kind, cost_usd=_usd(micro))
        for (model, kind), micro in totals.items()
        if micro
    ]
    layers.sort(key=lambda item: (item.usage_kind, -item.cost_usd, item.model))
    return layers


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


@dataclass
class ToolRollup:
    agent_days: List[DashboardOpsToolAgentDay]
    by_tool: List[DashboardOpsToolByTool]
    per_run: List[DashboardOpsToolCallsPerRun]
    providers: List[DashboardOpsProviderTotal]
    provider_days: List[DashboardOpsProviderDay]
    provider_agents: List[DashboardOpsProviderAgent]
    calls_with_no_tools: int


def _provider_name(call: Dict[str, Any]) -> str:
    provider = str(call.get("provider") or "").strip()
    return provider or "unknown"


def _calendar_day(ts: datetime, tz_name: Optional[str]) -> date:
    """Calendar day in the dashboard timezone so chart days match the run list."""
    from zoneinfo import ZoneInfo

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    zone = timezone.utc
    if tz_name:
        try:
            zone = ZoneInfo(tz_name)
        except Exception:
            zone = timezone.utc
    return ts.astimezone(zone).date()


def rollup_tool_calls(
    rows: Iterable[ToolCallSource],
    *,
    agent_names: Optional[Dict[UUID, str]] = None,
    tz_name: Optional[str] = None,
) -> ToolRollup:
    """Count each run once per day, tool, and provider so charts match the run list."""
    names = agent_names or {}
    by_day: Dict[Tuple[date, UUID], Dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0})
    by_tool: Dict[Tuple[UUID, str], Dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0})
    runs: Dict[UUID, int] = defaultdict(int)
    calls_by_agent: Dict[UUID, int] = defaultdict(int)
    provider_totals: Dict[str, int] = defaultdict(int)
    provider_days: Dict[Tuple[date, str], int] = defaultdict(int)
    provider_agents: Dict[Tuple[UUID, str], int] = defaultdict(int)
    calls_with_no_tools = 0

    for row in rows:
        if row.agent_id is None or row.timestamp is None:
            continue
        day = _calendar_day(row.timestamp, tz_name)
        runs[row.agent_id] += 1
        production = [call for call in _tool_records(row.call_data) if _is_production_call(call)]
        if not production:
            calls_with_no_tools += 1
            continue
        day_bucket = by_day[(day, row.agent_id)]
        day_bucket["calls"] += 1
        if any(_is_error_call(call) for call in production):
            day_bucket["errors"] += 1
        seen_tools: Set[str] = set()
        seen_tool_errors: Set[str] = set()
        seen_providers: Set[str] = set()
        for call in production:
            calls_by_agent[row.agent_id] += 1
            tool = str(call.get("tool") or "tool")
            if tool not in seen_tools:
                seen_tools.add(tool)
                by_tool[(row.agent_id, tool)]["calls"] += 1
            if _is_error_call(call) and tool not in seen_tool_errors:
                seen_tool_errors.add(tool)
                by_tool[(row.agent_id, tool)]["errors"] += 1
            provider = _provider_name(call)
            if provider in seen_providers:
                continue
            seen_providers.add(provider)
            provider_totals[provider] += 1
            provider_days[(day, provider)] += 1
            provider_agents[(row.agent_id, provider)] += 1

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
    per_run = [
        DashboardOpsToolCallsPerRun(
            agent_id=owner,
            agent_name=names.get(owner, "Unknown agent"),
            runs=run_count,
            calls=calls_by_agent.get(owner, 0),
            avg_per_run=round(calls_by_agent.get(owner, 0) / run_count, 2) if run_count else 0,
        )
        for owner, run_count in runs.items()
    ]
    per_run.sort(key=lambda item: item.avg_per_run, reverse=True)
    providers = [
        DashboardOpsProviderTotal(provider=provider, calls=count)
        for provider, count in provider_totals.items()
        if count
    ]
    providers.sort(key=lambda item: item.calls, reverse=True)
    provider_day_rows = [
        DashboardOpsProviderDay(day=day, provider=provider, calls=count)
        for (day, provider), count in provider_days.items()
        if count
    ]
    provider_day_rows.sort(key=lambda item: (item.day, -item.calls, item.provider))
    provider_agent_rows = [
        DashboardOpsProviderAgent(
            agent_id=owner,
            agent_name=names.get(owner, "Unknown agent"),
            provider=provider,
            calls=count,
        )
        for (owner, provider), count in provider_agents.items()
        if count
    ]
    provider_agent_rows.sort(key=lambda item: (item.agent_name.lower(), -item.calls, item.provider))
    return ToolRollup(
        agent_days=agent_days,
        by_tool=tools,
        per_run=per_run,
        providers=providers,
        provider_days=provider_day_rows,
        provider_agents=provider_agent_rows,
        calls_with_no_tools=calls_with_no_tools,
    )


def _suite_agent_scenario_pairs(query: Any) -> Set[tuple[UUID, str]]:
    pairs: Set[tuple[UUID, str]] = set()
    for owner, scenario_id in query.with_entities(
        EvaluatorResult.agent_id,
        EvaluatorResult.scenario_id,
    ).distinct():
        if owner is None or scenario_id is None:
            continue
        pairs.add((owner, str(scenario_id)))
    return pairs


def _scenario_ids_for_filter(
    db: Session,
    *,
    scenario_id: Optional[UUID],
) -> Optional[Set[str]]:
    if scenario_id is None:
        return None
    return {str(scenario_id)}


def _usage_day(value: Optional[datetime]) -> Optional[date]:
    if value is None:
        return None
    return value.date()


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _tool_payload(tool_calls: Any, knowledge_calls: Any) -> Dict[str, Any]:
    """Keep the tool name, provider, and status. Leave the transcript behind."""
    payload: Dict[str, Any] = {}
    tools = _json_value(tool_calls)
    knowledge = _json_value(knowledge_calls)
    if tools is not None:
        payload["tool_calls"] = tools
    if knowledge is not None:
        payload["knowledge_base_tool_calls"] = knowledge
    return payload


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
    tz_name: Optional[str] = None,
    metric_id: Optional[str] = None,
) -> EvaluatorResultsDashboardOpsResponse:
    live = playground is True
    scenario_ids = None if suite_id is not None else _scenario_ids_for_filter(db, scenario_id=scenario_id)
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
        ToolCallSource(
            result_id=result_id,
            agent_id=row_agent_id,
            timestamp=timestamp,
            call_data=_tool_payload(tool_calls, knowledge_calls),
        )
        for result_id, row_agent_id, timestamp, tool_calls, knowledge_calls in result_query.with_entities(
            EvaluatorResult.id,
            EvaluatorResult.agent_id,
            EvaluatorResult.timestamp,
            EvaluatorResult.call_data["tool_calls"],
            EvaluatorResult.call_data["knowledge_base_tool_calls"],
        ).all()
    ]

    playground_result_ids: Optional[Set[UUID]] = None
    if playground is not None:
        candidate_result_ids: Set[UUID] = {
            rid for (rid,) in result_query.with_entities(EvaluatorResult.id).all()
        }
        for row in usage_rows:
            explicit = _parse_uuid(_context_dict(row.context).get("evaluator_result_id"))
            if explicit is not None:
                candidate_result_ids.add(explicit)
        playground_result_ids = set()
        if candidate_result_ids:
            playground_result_ids.update(
                rid
                for (rid,) in db.query(CallRecording.evaluator_result_id).filter(
                    CallRecording.organization_id == organization_id,
                    CallRecording.workspace_id == workspace_id,
                    CallRecording.source == CallRecordingSource.PLAYGROUND,
                    CallRecording.evaluator_result_id.in_(candidate_result_ids),
                ).all()
                if rid is not None
            )
            playground_result_ids.update(
                rid
                for (rid,) in db.query(EvaluatorResult.id).filter(
                    EvaluatorResult.organization_id == organization_id,
                    EvaluatorResult.workspace_id == workspace_id,
                    EvaluatorResult.evaluator_id.is_(None),
                    EvaluatorResult.id.in_(candidate_result_ids),
                ).all()
            )

    agent_ids = {row.agent_id for row in tool_rows if row.agent_id}
    for spend in usage_rows:
        parsed = _parse_uuid(_context_dict(spend.context).get("agent_id"))
        if parsed:
            agent_ids.add(parsed)
    agent_names: Dict[UUID, str] = {}
    if agent_ids:
        for agent in db.query(Agent).filter(Agent.id.in_(agent_ids)).all():
            agent_names[agent.id] = agent.name or "Unknown agent"

    usage_scenario_scope = scenario_ids if suite_id is None else None
    suite_usage_pairs = _suite_agent_scenario_pairs(result_query) if suite_id is not None else None
    cost_by_agent, cost_by_model_day, cost_by_agent_day = rollup_usage(
        usage_rows,
        playground=live,
        agent_id=agent_id,
        scenario_ids=usage_scenario_scope,
        suite_agent_scenarios=suite_usage_pairs,
        agent_names=agent_names,
        playground_result_ids=playground_result_ids,
    )
    model_layers = rollup_model_layers(
        usage_rows,
        playground=live,
        agent_id=agent_id,
        scenario_ids=usage_scenario_scope,
        suite_agent_scenarios=suite_usage_pairs,
        playground_result_ids=playground_result_ids,
    )
    model_layers = _with_s2s_models(db, agent_ids, model_layers)
    model_layers = _attach_catalog_rates(db, organization_id, model_layers)
    tools = rollup_tool_calls(tool_rows, agent_names=agent_names, tz_name=tz_name)
    duration_buckets = _duration_buckets_from_query(result_query)
    from app.services.evaluators.evaluator_result_daily import load_dashboard_series

    series = load_dashboard_series(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        scenario_ids=scenario_ids,
        suite_id=suite_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
        tz_name=tz_name,
    )
    aggregate = cached_evaluator_results_aggregate(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        suite_id=suite_id,
        agent_id=agent_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
    )
    overview = cached_evaluator_results_overview(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        suite_id=suite_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
    )
    return EvaluatorResultsDashboardOpsResponse(
        cost_by_agent=cost_by_agent,
        cost_by_model_day=cost_by_model_day,
        cost_by_agent_day=cost_by_agent_day,
        model_layers=model_layers,
        tool_calls_by_agent_day=tools.agent_days,
        tool_calls_by_tool=tools.by_tool,
        tool_calls_per_run=tools.per_run,
        providers=tools.providers,
        provider_by_day=tools.provider_days,
        provider_by_agent=tools.provider_agents,
        calls_with_no_tools=tools.calls_with_no_tools,
        run_days=[
            DashboardOpsRunDay(
                day=row.day,
                completed=row.completed,
                failed=row.failed,
                duration_seconds=row.duration_seconds,
                duration_count=row.duration_count,
            )
            for row in series.run_days
        ],
        score_days=[
            DashboardOpsScoreDay(
                day=row.day,
                metric_id=row.metric_id,
                score_sum=row.score_sum,
                score_count=row.score_count,
            )
            for row in series.score_days
        ],
        total_rows=aggregate.total_rows,
        completed_rows=aggregate.completed_rows,
        failed_rows=aggregate.failed_rows,
        metrics=aggregate.metrics,
        agents=overview.agents,
        agent_metric_counts=[
            DashboardOpsAgentMetricCount(agent_id=row.agent_id, metric_count=row.metric_count)
            for row in series.agent_metric_counts
        ],
        duration_buckets=duration_buckets,
        scenario_metric_means=_scenario_metric_means(result_query, metric_id),
    )


def _scenario_metric_means(result_query, metric_id: Optional[str]) -> List[DashboardOpsScenarioMetricMean]:
    metric_key = (metric_id or "").strip()
    if not metric_key:
        return []
    totals: Dict[UUID, List[float]] = defaultdict(lambda: [0.0, 0.0])
    for scenario_id, scores in result_query.with_entities(
        EvaluatorResult.scenario_id,
        EvaluatorResult.metric_scores,
    ).all():
        if scenario_id is None or not isinstance(scores, dict):
            continue
        cell = scores.get(metric_key)
        if not isinstance(cell, dict) or cell.get("skipped") or cell.get("error"):
            continue
        try:
            value = float(cell.get("value"))
        except (TypeError, ValueError):
            continue
        bucket = totals[scenario_id]
        bucket[0] += value
        bucket[1] += 1
    means = [
        DashboardOpsScenarioMetricMean(
            scenario_id=scenario_id,
            mean=bucket[0] / bucket[1],
            scored=int(bucket[1]),
        )
        for scenario_id, bucket in totals.items()
        if bucket[1]
    ]
    means.sort(key=lambda item: item.scored, reverse=True)
    return means


def _with_s2s_models(
    db: Session,
    agent_ids: Set[UUID],
    layers: List[DashboardOpsModelLayer],
) -> List[DashboardOpsModelLayer]:
    if not agent_ids:
        return layers
    rows = (
        db.query(VoiceBundle.s2s_model)
        .join(Agent, Agent.voice_bundle_id == VoiceBundle.id)
        .filter(Agent.id.in_(agent_ids), VoiceBundle.s2s_model.isnot(None))
        .all()
    )
    present = {(item.model, item.usage_kind) for item in layers}
    extra = list(layers)
    for (model,) in rows:
        name = str(model or "").strip()
        if not name or (name, "s2s") in present:
            continue
        present.add((name, "s2s"))
        extra.append(DashboardOpsModelLayer(model=name, usage_kind="s2s", cost_usd=0))
    return extra


def _attach_catalog_rates(
    db: Session,
    organization_id: UUID,
    layers: List[DashboardOpsModelLayer],
) -> List[DashboardOpsModelLayer]:
    if not layers:
        return layers
    try:
        from app.services.usage.pricing import PricingResolver
    except Exception:
        return layers
    resolver = PricingResolver(db)
    today = date.today()
    rated: List[DashboardOpsModelLayer] = []
    for layer in layers:
        per_minute = None
        per_million = None
        kind = "llm" if layer.usage_kind == "s2s" else layer.usage_kind
        try:
            card = resolver.resolve_rate(
                organization_id=organization_id,
                model=layer.model,
                usage_kind=kind,
                usage_date=today,
            )
        except Exception:
            card = None
        if card is not None:
            if card.audio_micro_usd_per_second:
                per_minute = round(card.audio_micro_usd_per_second * 60 / _MICRO, 6)
            if card.input_micro_usd_per_million:
                per_million = round(card.input_micro_usd_per_million / _MICRO, 6)
        rated.append(
            layer.model_copy(
                update={
                    "usd_per_minute": per_minute,
                    "usd_per_million_tokens": per_million,
                }
            )
        )
    return rated


def results_cache_key(
    kind: str,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    suite_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    playground: Optional[bool] = None,
    tz_name: Optional[str] = None,
    metric_id: Optional[str] = None,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id),
        "suite_id": str(suite_id) if suite_id else None,
        "agent_id": str(agent_id) if agent_id else None,
        "scenario_id": str(scenario_id) if scenario_id else None,
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "playground": playground,
        "tz_name": tz_name,
        "metric_id": metric_id,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
    return f"results:{kind}:{organization_id}:{workspace_id}:{digest}"


def dashboard_ops_cache_key(
    *,
    organization_id: UUID,
    workspace_id: UUID,
    suite_id: Optional[UUID],
    agent_id: Optional[UUID],
    scenario_id: Optional[UUID],
    since: Optional[datetime],
    until: Optional[datetime],
    playground: Optional[bool],
    tz_name: Optional[str] = None,
    metric_id: Optional[str] = None,
) -> str:
    return results_cache_key(
        "dashboard_ops",
        organization_id=organization_id,
        workspace_id=workspace_id,
        suite_id=suite_id,
        agent_id=agent_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
        tz_name=tz_name,
        metric_id=metric_id,
    )


def _ops_redis():
    global _ops_redis_client
    if _ops_redis_client is None:
        import redis
        from app.config import settings

        _ops_redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _ops_redis_client


def get_cached_dashboard_ops(cache_key: str) -> Optional[dict]:
    try:
        raw = _ops_redis().get(cache_key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def cache_dashboard_ops(
    cache_key: str,
    payload: dict,
    *,
    until: Optional[datetime],
) -> None:
    today = datetime.now(timezone.utc).date()
    historical = until is not None and until.date() < today
    ttl = _OPS_CACHE_HISTORICAL_TTL_SECONDS if historical else _OPS_CACHE_TTL_SECONDS
    try:
        _ops_redis().set(cache_key, json.dumps(payload, default=str), ex=ttl)
    except Exception:
        return


def cached_evaluator_results_aggregate(
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
):
    from app.models.schemas import EvaluatorResultsAggregateResponse
    from app.services.evaluators.evaluator_results_aggregate import compute_evaluator_results_aggregate

    cache_key = results_cache_key(
        "aggregate",
        organization_id=organization_id,
        workspace_id=workspace_id,
        suite_id=suite_id,
        agent_id=agent_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
    )
    cached = get_cached_dashboard_ops(cache_key)
    if cached is not None:
        return EvaluatorResultsAggregateResponse.model_validate(cached)
    result = compute_evaluator_results_aggregate(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        suite_id=suite_id,
        agent_id=agent_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
    )
    cache_dashboard_ops(cache_key, result.model_dump(mode="json"), until=until)
    return result


def cached_evaluator_results_overview(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    playground: Optional[bool] = None,
):
    from app.models.schemas import EvaluatorResultsOverviewResponse
    from app.services.evaluators.evaluator_results_overview import build_evaluator_results_overview

    cache_key = results_cache_key(
        "overview",
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        suite_id=suite_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
    )
    cached = get_cached_dashboard_ops(cache_key)
    if cached is not None:
        return EvaluatorResultsOverviewResponse.model_validate(cached)
    result = build_evaluator_results_overview(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        suite_id=suite_id,
        scenario_id=scenario_id,
        since=since,
        until=until,
        playground=playground,
    )
    cache_dashboard_ops(cache_key, result.model_dump(mode="json"), until=until)
    return result
