"""Operator diagnostics for call-import evaluation fair dispatch."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Workspace,
)
from app.models.enums import CallImportRowStatus
from app.workers.concurrency.fair_dispatch import read_fair_dispatch_state, read_workspace_eval_rr_cursor
from app.workers.concurrency.limits import (
    read_global_inflight,
    read_job_inflight,
    read_org_inflight,
    read_workspace_inflight,
)


def build_call_import_dispatch_diagnostics(
    db: Session,
    organization_id: UUID,
    *,
    workspace_id: Optional[UUID] = None,
    include_idle_workspaces: bool = False,
    max_evaluations_per_workspace: int = 10,
) -> dict:
    """Build a live snapshot of eval slot usage and pending dispatch state."""

    limits = {
        "global_limit": settings.EVAL_GLOBAL_INFLIGHT_LIMIT,
        "global_inflight": read_global_inflight(),
        "org_limit": settings.EVAL_ORG_INFLIGHT_LIMIT,
        "org_inflight": read_org_inflight(organization_id),
        "workspace_limit": settings.EVAL_WORKSPACE_INFLIGHT_LIMIT,
        "job_limit": settings.EVAL_JOB_INFLIGHT_LIMIT,
        "fair_dispatch_batch_size": settings.EVAL_FAIR_DISPATCH_BATCH_SIZE,
        "global_at_capacity": read_global_inflight()
        >= settings.EVAL_GLOBAL_INFLIGHT_LIMIT,
        "org_at_capacity": read_org_inflight(organization_id)
        >= settings.EVAL_ORG_INFLIGHT_LIMIT,
    }

    fair_dispatch = read_fair_dispatch_state()

    workspace_query = db.query(Workspace).filter(
        Workspace.organization_id == organization_id
    )
    if workspace_id is not None:
        workspace_query = workspace_query.filter(Workspace.id == workspace_id)
    org_workspaces = workspace_query.order_by(Workspace.name.asc()).all()
    workspace_by_id = {ws.id: ws for ws in org_workspaces}

    pending_dispatch_by_workspace = _pending_dispatch_rows_by_workspace(
        db, organization_id, workspace_id=workspace_id
    )
    pending_import_by_workspace = _pending_import_rows_by_workspace(
        db, organization_id, workspace_id=workspace_id
    )
    evaluation_snapshots_by_workspace = _evaluation_snapshots_by_workspace(
        db,
        organization_id,
        workspace_id=workspace_id,
        max_per_workspace=max_evaluations_per_workspace,
    )

    workspace_ids: set[UUID] = set(workspace_by_id.keys())
    workspace_ids.update(pending_dispatch_by_workspace.keys())
    workspace_ids.update(pending_import_by_workspace.keys())
    workspace_ids.update(evaluation_snapshots_by_workspace.keys())

    workspace_payloads: List[dict] = []
    for ws_id in sorted(workspace_ids, key=str):
        ws = workspace_by_id.get(ws_id)
        inflight = read_workspace_inflight(ws_id)
        pending_dispatch = pending_dispatch_by_workspace.get(ws_id, 0)
        pending_import = pending_import_by_workspace.get(ws_id, 0)
        evaluations = evaluation_snapshots_by_workspace.get(ws_id, [])
        has_activity = (
            inflight > 0
            or pending_dispatch > 0
            or pending_import > 0
            or bool(evaluations)
        )
        if not include_idle_workspaces and not has_activity:
            continue
        workspace_payloads.append(
            {
                "workspace_id": ws_id,
                "workspace_name": ws.name if ws is not None else None,
                "workspace_slug": ws.slug if ws is not None else None,
                "inflight": inflight,
                "inflight_at_capacity": inflight
                >= settings.EVAL_WORKSPACE_INFLIGHT_LIMIT,
                "pending_dispatch_rows": pending_dispatch,
                "pending_import_rows": pending_import,
                "eval_rr_cursor": read_workspace_eval_rr_cursor(ws_id),
                "active_evaluations": len(evaluations),
                "evaluations": evaluations,
            }
        )

    return {
        "limits": limits,
        "fair_dispatch": fair_dispatch,
        "workspaces": workspace_payloads,
        "generated_at": datetime.now(timezone.utc),
    }


def _pending_dispatch_rows_by_workspace(
    db: Session,
    organization_id: UUID,
    *,
    workspace_id: Optional[UUID] = None,
) -> Dict[UUID, int]:
    query = (
        db.query(
            CallImportEvaluation.workspace_id,
            func.count(CallImportEvaluationRow.id),
        )
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .filter(
            CallImportEvaluation.organization_id == organization_id,
            CallImportEvaluation.status != "cancelled",
            CallImportEvaluationRow.status == "pending",
            CallImportEvaluationRow.celery_task_id.is_(None),
        )
    )
    if workspace_id is not None:
        query = query.filter(CallImportEvaluation.workspace_id == workspace_id)
    rows = query.group_by(CallImportEvaluation.workspace_id).all()
    return {row[0]: int(row[1]) for row in rows if row[0] is not None}


def _pending_import_rows_by_workspace(
    db: Session,
    organization_id: UUID,
    *,
    workspace_id: Optional[UUID] = None,
) -> Dict[UUID, int]:
    """Import rows still waiting for the eval pipeline to fetch recordings."""
    query = (
        db.query(CallImportEvaluation.workspace_id, func.count(CallImportRow.id))
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .join(
            CallImportRow,
            CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
        )
        .filter(
            CallImportEvaluation.organization_id == organization_id,
            CallImportEvaluation.status.in_(("pending", "running", "partial")),
            CallImportEvaluationRow.status.in_(("pending", "running")),
            CallImportRow.status == CallImportRowStatus.PENDING,
        )
    )
    if workspace_id is not None:
        query = query.filter(CallImportEvaluation.workspace_id == workspace_id)
    rows = query.group_by(CallImportEvaluation.workspace_id).all()
    return {row[0]: int(row[1]) for row in rows if row[0] is not None}


def _evaluation_snapshots_by_workspace(
    db: Session,
    organization_id: UUID,
    *,
    workspace_id: Optional[UUID] = None,
    max_per_workspace: int,
) -> Dict[UUID, List[dict]]:
    pending_case = case(
        (CallImportEvaluationRow.status == "pending", 1),
        else_=0,
    )
    running_case = case(
        (CallImportEvaluationRow.status == "running", 1),
        else_=0,
    )
    stats = (
        db.query(
            CallImportEvaluation.id,
            CallImportEvaluation.call_import_id,
            CallImportEvaluation.workspace_id,
            CallImportEvaluation.status,
            CallImportEvaluation.total_rows,
            func.sum(pending_case).label("pending_rows"),
            func.sum(running_case).label("running_rows"),
        )
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .filter(
            CallImportEvaluation.organization_id == organization_id,
            CallImportEvaluation.status != "cancelled",
        )
        .group_by(
            CallImportEvaluation.id,
            CallImportEvaluation.call_import_id,
            CallImportEvaluation.workspace_id,
            CallImportEvaluation.status,
            CallImportEvaluation.total_rows,
        )
        .having(func.sum(pending_case) + func.sum(running_case) > 0)
    )
    if workspace_id is not None:
        stats = stats.filter(CallImportEvaluation.workspace_id == workspace_id)

    by_workspace: Dict[UUID, List[dict]] = {}
    for row in stats.all():
        eval_id = row[0]
        snapshot = {
            "evaluation_id": eval_id,
            "call_import_id": row[1],
            "status": row[3] or "pending",
            "total_rows": int(row[4] or 0),
            "pending_rows": int(row.pending_rows or 0),
            "running_rows": int(row.running_rows or 0),
            "job_inflight": read_job_inflight(eval_id),
            "job_at_capacity": read_job_inflight(eval_id)
            >= settings.EVAL_JOB_INFLIGHT_LIMIT,
        }
        ws_id = row[2]
        if ws_id is None:
            continue
        bucket = by_workspace.setdefault(ws_id, [])
        bucket.append(snapshot)

    for ws_id, evaluations in by_workspace.items():
        evaluations.sort(
            key=lambda item: (item["pending_rows"], item["running_rows"]),
            reverse=True,
        )
        by_workspace[ws_id] = evaluations[: max(1, max_per_workspace)]
    return by_workspace
