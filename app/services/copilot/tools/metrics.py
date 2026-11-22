"""Metric analytics across the workspace: "pass rate of X this week vs last
week", "which metrics got worse", per-day and per-source breakdowns.

Numbers come from aggregates that already exist, never from scanning scored
rows (those live on the data shards):

* imports: each evaluation's cached per-metric aggregate, combined across
  evaluations weighted by how many calls each scored;
* simulations: each finished run's ``summary.metrics`` (mean, pass_rate, n).

"Pass rate" keeps the platform's meaning. Simulation runs have pass rules and a
threshold; import evaluations don't, so for imports we report the share of
``true`` answers (boolean metrics), averages, or category shares, and say so.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth.capabilities import CALLS_VIEW, METRICS_VIEW
from app.models.database import Agent, CallImport, CallImportEvaluation, Metric, SimulationRun
from app.services.copilot.periods import PERIODS, ResolvedPeriod, resolve_period, safe_zone
from app.services.copilot.registry import CopilotTool, ToolContext, ToolError, register
from app.services.copilot.tools.workspace import _like

MAX_EVALUATIONS_PER_WINDOW = 200
MAX_UNCACHED_COMPUTES = 3  # per call: older evaluations without a fresh cache are skipped beyond this
MIN_SAMPLE = 5
_TRUE = frozenset({"true", "yes", "pass", "passed", "1", "y"})
_FALSE = frozenset({"false", "no", "fail", "failed", "0", "n"})

Source = Literal["imports", "simulations", "all"]


@dataclass
class _ImportStat:
    scored: int = 0
    mean_sum: float = 0.0
    mean_n: int = 0
    true_n: int = 0
    bool_n: int = 0
    values: Counter = field(default_factory=Counter)

    def add(self, agg: Any) -> None:
        count = int(getattr(agg, "count", 0) or 0)
        self.scored += count
        mean = getattr(agg, "mean", None)
        if mean is not None and count:
            self.mean_sum += float(mean) * count
            self.mean_n += count
        for vc in getattr(agg, "value_counts", None) or []:
            label = str(vc.label).strip().lower()
            self.values[str(vc.label)] += int(vc.count)
            if label in _TRUE:
                self.true_n += int(vc.count)
                self.bool_n += int(vc.count)
            elif label in _FALSE:
                self.bool_n += int(vc.count)

    def view(self) -> dict[str, Any]:
        out: dict[str, Any] = {"calls_scored": self.scored}
        if self.bool_n:
            out["true_rate"] = round(self.true_n / self.bool_n, 4)
        if self.mean_n:
            out["mean"] = round(self.mean_sum / self.mean_n, 3)
        if self.values and not self.bool_n:
            total = sum(self.values.values())
            out["shares"] = {k: round(v / total, 4) for k, v in self.values.most_common(8)}
        return out


@dataclass
class _SimStat:
    trials: int = 0
    mean_sum: float = 0.0
    pass_sum: float = 0.0
    pass_n: int = 0

    def add(self, entry: dict[str, Any]) -> None:
        n = int(entry.get("n") or 0)
        if not n:
            return
        self.trials += n
        if entry.get("mean") is not None:
            self.mean_sum += float(entry["mean"]) * n
        if entry.get("pass_rate") is not None:
            self.pass_sum += float(entry["pass_rate"]) * n
            self.pass_n += n

    def view(self) -> dict[str, Any]:
        out: dict[str, Any] = {"trials": self.trials}
        if self.trials:
            out["mean_score"] = round(self.mean_sum / self.trials, 4)
        if self.pass_n:
            out["pass_rate"] = round(self.pass_sum / self.pass_n, 4)
        return out


@dataclass
class _Window:
    imports: dict[str, _ImportStat] = field(default_factory=lambda: defaultdict(_ImportStat))
    sims: dict[str, _SimStat] = field(default_factory=lambda: defaultdict(_SimStat))
    names: dict[str, str] = field(default_factory=dict)
    evaluations_used: int = 0
    evaluations_skipped: int = 0
    runs_used: int = 0


def _aggregates(db: Session, evaluation: CallImportEvaluation, budget: list[int]) -> Optional[list]:
    from app.services.copilot.tools.imports import evaluation_aggregates

    cached = evaluation_aggregates(db, evaluation, compute=False)
    if cached is not None:
        return cached
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    return evaluation_aggregates(db, evaluation, compute=True)


def _collect(
    db: Session,
    ctx: ToolContext,
    period: ResolvedPeriod,
    source: Source,
    *,
    metric_ids: Optional[set[str]] = None,
    group_key=None,
) -> dict[Any, _Window]:
    """Per-metric stats in the window, optionally split by ``group_key(kind, row)``."""
    windows: dict[Any, _Window] = defaultdict(_Window)
    budget = [MAX_UNCACHED_COMPUTES]

    if source in ("imports", "all"):
        evaluations = (
            db.query(CallImportEvaluation)
            .filter(
                CallImportEvaluation.organization_id == ctx.organization_id,
                CallImportEvaluation.workspace_id == ctx.workspace_id,
                CallImportEvaluation.created_at >= period.start,
                CallImportEvaluation.created_at < period.end,
                CallImportEvaluation.completed_rows > 0,
            )
            .order_by(CallImportEvaluation.created_at.desc())
            .limit(MAX_EVALUATIONS_PER_WINDOW)
            .all()
        )
        for evaluation in evaluations:
            window = windows[group_key("import", evaluation) if group_key else None]
            metrics = _aggregates(db, evaluation, budget)
            if metrics is None:
                window.evaluations_skipped += 1
                continue
            window.evaluations_used += 1
            for agg in metrics:
                mid = str(agg.metric_id)
                if metric_ids and mid not in metric_ids:
                    continue
                window.imports[mid].add(agg)
                window.names.setdefault(mid, agg.metric_name)

    if source in ("simulations", "all"):
        runs = (
            db.query(SimulationRun)
            .filter(
                SimulationRun.organization_id == ctx.organization_id,
                SimulationRun.workspace_id == ctx.workspace_id,
                SimulationRun.created_at >= period.start,
                SimulationRun.created_at < period.end,
                SimulationRun.status == "completed",
            )
            .order_by(SimulationRun.created_at.desc())
            .limit(MAX_EVALUATIONS_PER_WINDOW)
            .all()
        )
        for run in runs:
            window = windows[group_key("simulation", run) if group_key else None]
            window.runs_used += 1
            for entry in (run.summary or {}).get("metrics") or []:
                mid = str(entry.get("metric_id"))
                if metric_ids and mid not in metric_ids:
                    continue
                window.sims[mid].add(entry)
                window.names.setdefault(mid, entry.get("name") or mid)
    return windows


def _metric_view(window: _Window, mid: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if mid in window.imports and window.imports[mid].scored:
        out["imports"] = window.imports[mid].view()
    if mid in window.sims and window.sims[mid].trials:
        out["simulations"] = window.sims[mid].view()
    return out


def _resolve_metric(db: Session, ctx: ToolContext, ref: str) -> Metric:
    q = db.query(Metric).filter(
        Metric.organization_id == ctx.organization_id,
        or_(Metric.workspace_id == ctx.workspace_id, Metric.workspace_id.is_(None)),
    )
    try:
        metric = q.filter(Metric.id == UUID(ref.strip())).first()
        if metric:
            return metric
    except ValueError:
        pass
    exact = q.filter(Metric.name.ilike(ref.strip())).all()
    if len(exact) == 1:
        return exact[0]
    matches = exact or q.filter(Metric.name.ilike(_like(ref), escape="\\")).limit(6).all()
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolError(f"No metric matches {ref!r}. Use list_metrics to find the right one.")
    raise ToolError(
        "Several metrics match; ask the user which one: "
        + "; ".join(f"{m.name} (id {m.id})" for m in matches)
    )


def _previous(period: ResolvedPeriod) -> ResolvedPeriod:
    length = period.end - period.start
    return ResolvedPeriod(
        label=f"previous {length.days} day(s)",
        start=period.start - length,
        end=period.start,
        timezone=period.timezone,
    )


def _resolve(args: Any, tz: str, which: str = "") -> ResolvedPeriod:
    try:
        return resolve_period(
            getattr(args, f"{which}period"),
            tz,
            start_date=getattr(args, f"{which}start_date", None),
            end_date=getattr(args, f"{which}end_date", None),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _compare_period(period: ResolvedPeriod, compare_to: str, tz: str) -> ResolvedPeriod:
    if compare_to == "previous":
        return _previous(period)
    try:
        return resolve_period(compare_to, tz)
    except ValueError as exc:
        raise ToolError(f"compare_to: {exc}") from exc


def _delta(cur: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src in ("imports", "simulations"):
        a, b = cur.get(src) or {}, prev.get(src) or {}
        for key in ("pass_rate", "true_rate", "mean", "mean_score"):
            if key in a and key in b:
                out[f"{src}.{key}"] = round(a[key] - b[key], 4)
    return out


class TrendArgs(BaseModel):
    metric: str = Field(..., max_length=255, description="Metric name or id.")
    period: Literal[PERIODS] = "this_week"  # type: ignore[valid-type]
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    compare_to: Optional[Literal["previous", "none"] | Literal[PERIODS]] = Field(  # type: ignore[valid-type]
        "previous",
        description="'previous' = the same-length window just before; or a period name like last_week.",
    )
    group_by: Literal["none", "day", "source"] = Field(
        "none", description="day = per day; source = per import file / per simulated agent."
    )
    source: Source = "all"


def _group_key_factory(db: Session, group_by: str, tz: str):
    if group_by == "day":
        zone = safe_zone(tz)
        return lambda kind, row: row.created_at.astimezone(zone).date().isoformat()
    if group_by == "source":
        import_names: dict[UUID, str] = {}
        agent_names: dict[UUID, str] = {}

        def key(kind: str, row: Any) -> str:
            if kind == "import":
                if row.call_import_id not in import_names:
                    import_names[row.call_import_id] = (
                        db.query(CallImport.original_filename).filter(CallImport.id == row.call_import_id).scalar()
                        or "import"
                    )
                return f"import: {import_names[row.call_import_id]}"
            if row.agent_id not in agent_names:
                agent_names[row.agent_id] = db.query(Agent.name).filter(Agent.id == row.agent_id).scalar() or "agent"
            return f"simulations: {agent_names[row.agent_id]}"

        return key
    return None


def metric_trend(ctx: ToolContext, db: Session, args: TrendArgs) -> dict:
    metric = _resolve_metric(db, ctx, args.metric)
    mid = str(metric.id)
    period = _resolve(args, ctx.timezone)
    current = _collect(db, ctx, period, args.source, metric_ids={mid}).get(None) or _Window()
    result: dict[str, Any] = {
        "metric": {"id": mid, "name": metric.name, "type": getattr(metric.metric_type, "value", metric.metric_type)},
        "range": period.as_dict(),
        "current": _metric_view(current, mid),
        "coverage": {
            "import_evaluations": current.evaluations_used,
            "import_evaluations_without_fresh_results": current.evaluations_skipped,
            "simulation_runs": current.runs_used,
        },
    }
    if args.compare_to and args.compare_to != "none":
        prev_period = _compare_period(period, args.compare_to, ctx.timezone)
        prev = _collect(db, ctx, prev_period, args.source, metric_ids={mid}).get(None) or _Window()
        result["compare_range"] = prev_period.as_dict()
        result["previous"] = _metric_view(prev, mid)
        result["change"] = _delta(result["current"], result["previous"])
    if args.group_by != "none":
        groups = _collect(
            db, ctx, period, args.source, metric_ids={mid},
            group_key=_group_key_factory(db, args.group_by, ctx.timezone),
        )
        result["breakdown"] = {
            str(k): _metric_view(w, mid) for k, w in sorted(groups.items(), key=lambda kv: str(kv[0]))
        }
    result["note"] = (
        "imports.true_rate = share of calls where the metric was true (imports have no pass threshold); "
        "simulations.pass_rate uses each run's pass rules. State the date ranges and sample sizes; "
        f"call results with fewer than {MIN_SAMPLE} calls unreliable."
    )
    return result


class CompareArgs(BaseModel):
    period: Literal[PERIODS] = "this_week"  # type: ignore[valid-type]
    compare_to: Literal["previous"] | Literal[PERIODS] = "previous"  # type: ignore[valid-type]
    source: Source = "all"
    limit: int = Field(10, ge=1, le=25)


_MEASURES = (
    ("simulations", "pass_rate"),
    ("imports", "true_rate"),
    ("simulations", "mean_score"),
)


def _common_measure(a: dict[str, Any], b: dict[str, Any]) -> Optional[tuple[str, float, float]]:
    """First measure both windows have, so a change is never computed across different measures."""
    for src, key in _MEASURES:
        va, vb = (a.get(src) or {}).get(key), (b.get(src) or {}).get(key)
        if va is not None and vb is not None:
            return f"{src}.{key}", va, vb
    return None


def _sample(view: dict[str, Any]) -> int:
    return int((view.get("imports") or {}).get("calls_scored", 0)) + int((view.get("simulations") or {}).get("trials", 0))


def compare_metrics(ctx: ToolContext, db: Session, args: CompareArgs) -> dict:
    period = _resolve(args, ctx.timezone)
    prev_period = _compare_period(period, args.compare_to, ctx.timezone)
    cur = _collect(db, ctx, period, args.source).get(None) or _Window()
    prev = _collect(db, ctx, prev_period, args.source).get(None) or _Window()
    changes = []
    for mid in set(cur.names) & set(prev.names):
        a, b = _metric_view(cur, mid), _metric_view(prev, mid)
        common = _common_measure(a, b)
        if common is None or min(_sample(a), _sample(b)) < MIN_SAMPLE:
            continue
        measure, now_value, before_value = common
        changes.append({
            "metric_id": mid,
            "metric": cur.names[mid],
            "measure": measure,
            "current": now_value,
            "previous": before_value,
            "change": round(now_value - before_value, 4),
            "sample": {"current": _sample(a), "previous": _sample(b)},
        })
    changes.sort(key=lambda c: c["change"])
    return {
        "range": period.as_dict(),
        "compare_range": prev_period.as_dict(),
        "got_worse": [c for c in changes if c["change"] < 0][: args.limit],
        "got_better": sorted((c for c in changes if c["change"] > 0), key=lambda c: -c["change"])[: args.limit],
        "metrics_compared": len(changes),
        "note": f"Only metrics with at least {MIN_SAMPLE} scored calls in both windows are compared.",
    }


# --- production calls -----------------------------------------------------------------


class CallsArgs(BaseModel):
    search: Optional[str] = Field(None, max_length=200)
    limit: int = Field(5, ge=0, le=15)


def production_calls(ctx: ToolContext, db: Session, args: CallsArgs) -> dict:
    import asyncio

    from app.api.v1.routes.observability import list_calls_hub

    page = asyncio.run(list_calls_hub(
        skip=0, limit=max(1, args.limit), status=None, search=args.search, event="all",
        organization_id=ctx.organization_id, workspace_id=ctx.workspace_id, api_key="", db=db,
    ))
    items = page.get("items", []) if isinstance(page, dict) else []
    return {
        "summary": page.get("summary") if isinstance(page, dict) else None,
        "recent": [
            {
                "kind": i.get("kind"),
                "at": i.get("sort_at"),
                "name": ((i.get("obs") or i.get("trace") or {}).get("display_name")),
                "status": ((i.get("obs") or i.get("trace") or {}).get("status")),
            }
            for i in items[: args.limit]
        ],
        "link": "/observability",
    }


for tool in (
    CopilotTool(
        name="get_metric_trend",
        description=(
            "How one metric is doing over time in this workspace, from import evaluations and simulation "
            "runs: pass rate / share true / average, compared with an earlier period, optionally per day "
            "or per source. Use for 'pass rate of X this week vs last week'."
        ),
        args_model=TrendArgs, handler=metric_trend, capability=METRICS_VIEW, group="analytics",
        statement_timeout_ms=20_000,
    ),
    CopilotTool(
        name="compare_metrics",
        description="Which metrics got worse or better between two periods (e.g. this week vs last week), ranked by change.",
        args_model=CompareArgs, handler=compare_metrics, capability=METRICS_VIEW, group="analytics",
        statement_timeout_ms=20_000,
    ),
    CopilotTool(
        name="get_production_calls",
        description="Volume and status of live production calls and traces (observability), with the most recent ones.",
        args_model=CallsArgs, handler=production_calls, capability=CALLS_VIEW, group="analytics",
    ),
):
    register(tool)
