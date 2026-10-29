"""Read paths for call-import batches and rows."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportStatus
from app.models.schemas import (
    CallImportDetailResponse,
    CallImportInsightsMetric,
    CallImportInsightsResponse,
    CallImportInsightsRunPoint,
    CallImportListResponse,
    CallImportMetricAggregate,
    CallImportRowIdsResponse,
    CallImportRowResponse,
)
from app.services.call_imports.audit import (
    emails_for_user_ids,
    user_ids_from_call_imports,
)
from app.services.call_imports.dispatch_diagnostics import (
    build_call_import_dispatch_diagnostics,
)
from app.services.call_imports.present import (
    _call_import_row_list_response,
    _imported_agent_partial_id,
    _remember_platform_agent_names,
    _serialize_call_import,
)


def get_call_import_for_org_or_404(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
) -> CallImport:
    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if not call_import:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import not found",
        )
    return call_import


def locate_call_import_row_or_404(
    catalog_db: Session,
    *,
    call_import_id: UUID,
    row_id: UUID,
    organization_id: UUID,
) -> Tuple[Session, CallImportRow, Optional[Session]]:
    from app.db_sharding.row_ops import close_row_sessions, locate_call_import_row

    try:
        row_db, located_catalog, row, _shard_id = locate_call_import_row(row_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import row not found",
        ) from None
    if (
        row.call_import_id != call_import_id
        or row.organization_id != organization_id
    ):
        close_row_sessions(
            row_db,
            located_catalog if located_catalog is not row_db else None,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import row not found",
        )
    extra_catalog = located_catalog if located_catalog is not row_db else None
    return row_db, row, extra_catalog


def list_call_imports_page(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    *,
    page: int,
    page_size: int,
    status_filter: Optional[CallImportStatus] = None,
    dataset: Optional[str] = None,
    tag_id: Optional[List[UUID]] = None,
    source_format: Optional[str] = None,
    content_modality: Optional[str] = None,
) -> CallImportListResponse:
    query = (
        db.query(CallImport)
        .filter(
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
        )
    )
    if status_filter is not None:
        query = query.filter(CallImport.status == status_filter)

    source_filter = (source_format or "").strip().lower()
    if source_filter == "__non_audio__":
        query = query.filter(
            or_(
                CallImport.source_format.is_(None),
                CallImport.source_format.notin_(["audio", "platform"]),
            )
        )
    elif source_filter:
        query = query.filter(func.lower(CallImport.source_format) == source_filter)

    modality_filter = (content_modality or "").strip().lower()
    if modality_filter == "chat":
        query = query.filter(func.lower(CallImport.content_modality) == "chat")
    elif modality_filter in ("__voice__", "voice"):
        query = query.filter(
            or_(
                CallImport.content_modality.is_(None),
                func.lower(CallImport.content_modality) != "chat",
            )
        )

    if dataset is not None:
        if dataset == "__none__":
            query = query.filter(CallImport.dataset.is_(None))
        elif dataset.strip():
            query = query.filter(
                func.lower(CallImport.dataset) == dataset.strip().lower()
            )

    if tag_id:
        from app.models.database import CallImportTagAssignment

        for single_tag_id in tag_id:
            sub = (
                db.query(CallImportTagAssignment.call_import_id)
                .filter(CallImportTagAssignment.tag_id == single_tag_id)
                .subquery()
            )
            query = query.filter(CallImport.id.in_(sub))

    total = query.count()
    items = (
        query.order_by(desc(CallImport.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    email_map = emails_for_user_ids(db, user_ids_from_call_imports(items))
    return CallImportListResponse(
        items=[
            _serialize_call_import(db, item, user_emails=email_map)
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_call_import_dispatch_diagnostics_payload(
    db: Session,
    organization_id: UUID,
    *,
    workspace_id: Optional[UUID] = None,
    include_idle_workspaces: bool = False,
) -> dict:
    return build_call_import_dispatch_diagnostics(
        db,
        organization_id,
        workspace_id=workspace_id,
        include_idle_workspaces=include_idle_workspaces,
    )


def list_call_import_dataset_labels(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
) -> List[str]:
    rows = (
        db.query(CallImport.dataset)
        .filter(
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
            CallImport.dataset.isnot(None),
            CallImport.dataset != "",
        )
        .distinct()
        .order_by(CallImport.dataset.asc())
        .all()
    )
    return [row[0] for row in rows if row[0]]


def get_call_import_detail(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    *,
    row_limit: int,
    row_offset: int,
    q: Optional[str] = None,
    diarised_status: Optional[str] = None,
) -> CallImportDetailResponse:
    call_import = get_call_import_for_org_or_404(db, call_import_id, organization_id)

    if call_import.status == CallImportStatus.PROCESSING:
        from app.services.call_imports.bulk_ops import rollup_call_import_batch_status

        prior_status = call_import.status
        rollup_call_import_batch_status(db, call_import)
        if call_import.status != prior_status:
            db.commit()
            db.refresh(call_import)

    if (
        (call_import.source_format or "") == "platform"
        and _imported_agent_partial_id(call_import) is None
    ):
        from app.services.platform_import_imported_agent import (
            ensure_imported_agent_for_platform_import,
        )

        try:
            if ensure_imported_agent_for_platform_import(db, call_import, None):
                db.commit()
                db.refresh(call_import)
        except Exception:
            db.rollback()

    search_term = (q or "").strip()
    diarised_status_filter = (diarised_status or "").strip() or None
    filtered_total_rows: Optional[int] = None
    has_row_filters = bool(search_term or diarised_status_filter)

    if has_row_filters:
        if is_sharding_enabled():
            from app.db_sharding.scatter_gather import count_call_import_rows_filtered

            filtered_total_rows = count_call_import_rows_filtered(
                db,
                call_import.id,
                search_term=search_term,
                diarised_status_filter=diarised_status_filter,
            )
        else:
            rows_query = db.query(CallImportRow).filter(
                CallImportRow.call_import_id == call_import.id
            )
            if search_term:
                rows_query = rows_query.filter(
                    CallImportRow.conversation_id.ilike(f"%{search_term}%")
                )
            if diarised_status_filter:
                rows_query = rows_query.filter(
                    CallImportRow.diarised_transcript_status == diarised_status_filter
                )
            filtered_total_rows = rows_query.count()

    if row_limit == 0:
        rows: List[CallImportRow] = []
    elif is_sharding_enabled():
        from app.db_sharding.scatter_gather import (
            fetch_call_import_rows_filtered_page,
            fetch_call_import_rows_page,
        )

        if has_row_filters:
            rows = fetch_call_import_rows_filtered_page(
                db,
                call_import.id,
                search_term=search_term,
                diarised_status_filter=diarised_status_filter,
                offset=row_offset,
                limit=row_limit,
            )
        else:
            rows = fetch_call_import_rows_page(
                db,
                call_import.id,
                offset=row_offset,
                limit=row_limit,
            )
    else:
        rows_query = db.query(CallImportRow).filter(
            CallImportRow.call_import_id == call_import.id
        )
        if search_term:
            rows_query = rows_query.filter(
                CallImportRow.conversation_id.ilike(f"%{search_term}%")
            )
        if diarised_status_filter:
            rows_query = rows_query.filter(
                CallImportRow.diarised_transcript_status == diarised_status_filter
            )
        from app.db_sharding.scatter_gather import defer_call_import_row_text

        rows = (
            rows_query.options(*defer_call_import_row_text())
            .order_by(CallImportRow.row_index)
            .offset(row_offset)
            .limit(row_limit)
            .all()
        )

    if is_sharding_enabled():
        from app.db_sharding.scatter_gather import aggregate_diarised_transcript_counts

        diarised_status_counts = aggregate_diarised_transcript_counts(
            db, call_import.id
        )
    else:
        diarised_status_counts: Dict[str, int] = {}
        for status_value, count in (
            db.query(CallImportRow.diarised_transcript_status, func.count())
            .filter(CallImportRow.call_import_id == call_import.id)
            .group_by(CallImportRow.diarised_transcript_status)
            .all()
        ):
            if isinstance(status_value, str):
                diarised_status_counts[status_value] = int(count or 0)

    if (call_import.source_format or "").lower() == "platform":
        _remember_platform_agent_names(db, call_import)
    detail = CallImportDetailResponse.model_validate(
        _serialize_call_import(db, call_import).model_dump()
    )
    detail.rows = [_call_import_row_list_response(r) for r in rows]
    detail.filtered_total_rows = filtered_total_rows
    detail.diarised_pending_rows = diarised_status_counts.get("pending", 0)
    detail.diarised_running_rows = diarised_status_counts.get("running", 0)
    detail.diarised_completed_rows = diarised_status_counts.get("completed", 0)
    detail.diarised_failed_rows = diarised_status_counts.get("failed", 0)
    if (call_import.source_format or "").lower() == "platform":
        from app.services.call_imports.platform_import_progress import (
            build_platform_import_progress,
        )

        detail.platform_progress = build_platform_import_progress(db, call_import)
    return detail


def list_call_import_row_ids(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    *,
    q: Optional[str] = None,
    diarised_status: Optional[str] = None,
) -> CallImportRowIdsResponse:
    call_import = get_call_import_for_org_or_404(db, call_import_id, organization_id)

    search_term = (q or "").strip()
    status_filter = (diarised_status or "").strip() or None

    if is_sharding_enabled():
        from app.db_sharding.scatter_gather import list_call_import_row_ids_filtered

        ids = list_call_import_row_ids_filtered(
            db,
            call_import.id,
            search_term=search_term,
            diarised_status_filter=status_filter,
        )
        return CallImportRowIdsResponse(ids=ids, total=len(ids))

    rows_query = db.query(CallImportRow.id).filter(
        CallImportRow.call_import_id == call_import.id
    )
    if search_term:
        rows_query = rows_query.filter(
            CallImportRow.conversation_id.ilike(f"%{search_term}%")
        )
    if status_filter:
        rows_query = rows_query.filter(
            CallImportRow.diarised_transcript_status == status_filter
        )

    ids = [
        row_id
        for (row_id,) in rows_query.order_by(CallImportRow.row_index).all()
    ]
    return CallImportRowIdsResponse(ids=ids, total=len(ids))


def get_call_import_row(
    db: Session,
    call_import_id: UUID,
    row_id: UUID,
    organization_id: UUID,
) -> CallImportRowResponse:
    if not is_sharding_enabled():
        row = (
            db.query(CallImportRow)
            .filter(
                CallImportRow.id == row_id,
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.organization_id == organization_id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Call import row not found",
            )
        return CallImportRowResponse.model_validate(row)

    from app.db_sharding.row_ops import close_row_sessions

    row_db, row, extra_catalog = locate_call_import_row_or_404(
        db,
        call_import_id=call_import_id,
        row_id=row_id,
        organization_id=organization_id,
    )
    try:
        return CallImportRowResponse.model_validate(row)
    finally:
        close_row_sessions(row_db, extra_catalog)


def build_call_import_insights(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
) -> CallImportInsightsResponse:
    get_call_import_for_org_or_404(db, call_import_id, organization_id)

    from app.models.database import CallImportEvaluation, Metric

    from app.db_sharding.scatter_gather import (
        aggregate_transcript_coverage,
        load_evaluation_score_rows,
    )

    (
        total_rows,
        rows_with_transcript,
        rows_without_transcript,
        source_counts,
    ) = aggregate_transcript_coverage(db, call_import_id)

    evaluations = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .order_by(CallImportEvaluation.created_at.asc())
        .all()
    )

    from app.api.v1.routes.call_import_evaluations import (
        _compute_metric_aggregates,
    )

    metric_history: Dict[str, List[CallImportInsightsRunPoint]] = {}
    metric_meta: Dict[str, Metric] = {}
    metric_latest: Dict[str, CallImportMetricAggregate] = {}

    for evaluation in evaluations:
        eval_rows = load_evaluation_score_rows(db, evaluation.id)
        aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
        for agg in aggregates:
            if agg.metric_id not in metric_meta:
                try:
                    metric_uuid = UUID(agg.metric_id)
                except (ValueError, AttributeError, TypeError):
                    metric_uuid = None
                if metric_uuid is not None:
                    metric_obj = (
                        db.query(Metric)
                        .filter(
                            Metric.id == metric_uuid,
                            Metric.organization_id == organization_id,
                        )
                        .first()
                    )
                    if metric_obj is not None:
                        metric_meta[agg.metric_id] = metric_obj
            history = metric_history.setdefault(agg.metric_id, [])
            history.append(
                CallImportInsightsRunPoint(
                    evaluation_id=evaluation.id,
                    name=evaluation.name,
                    created_at=evaluation.created_at,
                    mean=agg.mean,
                    completed_rows=agg.count,
                )
            )
            metric_latest[agg.metric_id] = agg

    metrics_payload: List[CallImportInsightsMetric] = []
    for metric_id, latest in metric_latest.items():
        meta = metric_meta.get(metric_id)
        metrics_payload.append(
            CallImportInsightsMetric(
                metric_id=metric_id,
                metric_name=(meta.name if meta else latest.metric_name),
                metric_type=(meta.metric_type if meta else latest.metric_type),
                latest=latest,
                trend=metric_history.get(metric_id, []),
            )
        )

    return CallImportInsightsResponse(
        call_import_id=call_import_id,
        total_rows=total_rows,
        rows_with_transcript=rows_with_transcript,
        rows_without_transcript=rows_without_transcript,
        transcript_source_counts=source_counts,
        evaluation_count=len(evaluations),
        metrics=metrics_payload,
    )
