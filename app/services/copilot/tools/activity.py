"""Workspace-wide evaluation activity: "how many evals ran this week, and which?"

Counts come from one ``GROUP BY status`` per evaluation table over
``(workspace_id, created_at)`` (indexed in migration 121), so they are exact
and cheap however much history a workspace has. Item lists are the most recent
N per kind, merged. The model never writes SQL.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth.capabilities import EVALS_VIEW
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    Evaluation,
    EvaluatorResult,
    SimulationRun,
)
from app.services.copilot.periods import PERIODS, resolve_period
from app.services.copilot.registry import CopilotTool, ToolContext, ToolError, register

Kind = Literal["import_evaluation", "simulation_run", "test_call", "audio_evaluation"]
Bucket = Literal["queued", "in_progress", "completed", "failed", "cancelled"]

KIND_LABELS = {
    "import_evaluation": "Import evaluations (imported calls)",
    "simulation_run": "Simulation runs",
    "test_call": "Test calls (evaluator results)",
    "audio_evaluation": "Audio evaluations",
}

_QUEUED = {"pending", "queued"}
_COMPLETED = {"completed", "complete", "succeeded", "success", "done"}


def status_bucket(raw: Optional[str]) -> str:
    """Collapse each table's status vocabulary into five buckets users understand."""
    value = (raw or "").strip().lower()
    if value in _QUEUED:
        return "queued"
    if value in _COMPLETED:
        return "completed"
    if "fail" in value or value == "error":
        return "failed"
    if "cancel" in value or value == "aborted":
        return "cancelled"
    return "in_progress"


class ActivityArgs(BaseModel):
    period: Literal[PERIODS] = Field(  # type: ignore[valid-type]
        "this_week",
        description="Time window, resolved in the user's time zone. Weeks start Monday.",
    )
    start_date: Optional[date] = Field(None, description="For period=custom: first day (YYYY-MM-DD).")
    end_date: Optional[date] = Field(None, description="For period=custom: last day, inclusive.")
    kinds: Optional[list[Kind]] = Field(
        None, description="Which kinds of evaluation to include. Omit for all."
    )
    statuses: Optional[list[Bucket]] = Field(
        None, description="Only list items in these statuses. Totals always cover every status."
    )
    limit: int = Field(10, ge=0, le=20, description="How many recent items to list (0 = counts only).")


class _KindSpec:
    def __init__(
        self,
        model: Any,
        describe: Callable[[Session, list[Any]], list[dict[str, Any]]],
    ):
        self.model = model
        self.describe = describe


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _describe_import_evals(db: Session, rows: list[CallImportEvaluation]) -> list[dict]:
    from app.services.call_imports.audit import emails_for_user_ids

    import_ids = {r.call_import_id for r in rows}
    files = dict(
        db.query(CallImport.id, CallImport.original_filename)
        .filter(CallImport.id.in_(import_ids))
        .all()
    ) if import_ids else {}
    emails = emails_for_user_ids(db, {r.created_by_user_id for r in rows if r.created_by_user_id})
    out = []
    for r in rows:
        source = files.get(r.call_import_id)
        out.append({
            "name": r.name or (f"Evaluation of {source}" if source else "Import evaluation"),
            "import": source,
            "started_by": emails.get(r.created_by_user_id),
            "progress": {
                "total_rows": r.total_rows,
                "completed_rows": r.completed_rows,
                "failed_rows": r.failed_rows,
            },
            "finished_at": _iso(r.finished_at),
            "link": f"/call-imports/{r.call_import_id}/evaluations/{r.id}",
        })
    return out


def _describe_simulation_runs(_db: Session, rows: list[SimulationRun]) -> list[dict]:
    return [
        {
            "name": r.name or f"Simulation run {r.run_id}",
            "finished_at": _iso(r.finished_at),
            "link": f"/simulations/{r.run_id}",
        }
        for r in rows
    ]


def _describe_test_calls(_db: Session, rows: list[EvaluatorResult]) -> list[dict]:
    return [
        {"name": r.name or f"Test call {r.result_id}", "link": f"/results/{r.result_id}"}
        for r in rows
    ]


def _describe_audio_evals(_db: Session, rows: list[Evaluation]) -> list[dict]:
    return [
        {"name": f"Audio evaluation ({r.model_name})" if r.model_name else "Audio evaluation",
         "finished_at": _iso(r.completed_at)}
        for r in rows
    ]


_KINDS: dict[str, _KindSpec] = {
    "import_evaluation": _KindSpec(CallImportEvaluation, _describe_import_evals),
    "simulation_run": _KindSpec(SimulationRun, _describe_simulation_runs),
    "test_call": _KindSpec(EvaluatorResult, _describe_test_calls),
    "audio_evaluation": _KindSpec(Evaluation, _describe_audio_evals),
}


def _scoped(db: Session, model: Any, ctx: ToolContext, start, end):
    return db.query(model).filter(
        model.organization_id == ctx.organization_id,
        model.workspace_id == ctx.workspace_id,
        model.created_at >= start,
        model.created_at < end,
    )


def evaluation_activity(ctx: ToolContext, db: Session, args: ActivityArgs) -> dict:
    try:
        period = resolve_period(
            args.period, ctx.timezone, start_date=args.start_date, end_date=args.end_date
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    kinds = list(dict.fromkeys(args.kinds or _KINDS.keys()))
    wanted = set(args.statuses or [])
    by_kind: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    candidates: list[tuple[Any, str, Any]] = []

    for kind in kinds:
        spec = _KINDS[kind]
        model = spec.model
        status_counts = (
            _scoped(db, model, ctx, period.start, period.end)
            .with_entities(model.status, func.count())
            .group_by(model.status)
            .all()
        )
        buckets: dict[str, int] = {}
        raw_in_wanted: list[str] = []
        for raw, count in status_counts:
            bucket = status_bucket(raw)
            buckets[bucket] = buckets.get(bucket, 0) + int(count)
            totals[bucket] = totals.get(bucket, 0) + int(count)
            if not wanted or bucket in wanted:
                raw_in_wanted.append(raw)
        by_kind[kind] = {"label": KIND_LABELS[kind], "total": sum(buckets.values()), **buckets}

        if args.limit and raw_in_wanted:
            rows = (
                _scoped(db, model, ctx, period.start, period.end)
                .filter(model.status.in_(raw_in_wanted))
                .order_by(model.created_at.desc())
                .limit(args.limit)
                .all()
            )
            details = spec.describe(db, rows)
            for row, detail in zip(rows, details):
                candidates.append((row.created_at, kind, {
                    "kind": kind,
                    "id": str(row.id),
                    "status": status_bucket(row.status),
                    "created_at": _iso(row.created_at),
                    **detail,
                }))

    candidates.sort(key=lambda c: c[0], reverse=True)
    items = [c[2] for c in candidates[: args.limit]]
    listed_total = sum(
        n for k in by_kind.values() for b, n in k.items() if b in (wanted or _ALL_BUCKETS)
    )
    return {
        "range": period.as_dict(),
        "total": sum(totals.values()),
        "by_status": totals,
        "by_kind": by_kind,
        "items": items,
        "items_shown": len(items),
        "items_matching": listed_total,
        "note": (
            "Counts are exact. 'items' lists the most recent matches only; "
            "say how many more exist when items_matching > items_shown."
        ),
    }


_ALL_BUCKETS = frozenset({"queued", "in_progress", "completed", "failed", "cancelled"})


register(CopilotTool(
    name="get_evaluation_activity",
    description=(
        "Count and list evaluation activity in the current workspace for a time period: "
        "import evaluations, simulation runs, test calls and audio evaluations, by status "
        "(queued, in_progress, completed, failed, cancelled). Use for questions like "
        "'how many evals ran this week' or 'what failed yesterday'. Always tell the user the "
        "resolved date range from `range`."
    ),
    args_model=ActivityArgs,
    handler=evaluation_activity,
    capability=EVALS_VIEW,
))
