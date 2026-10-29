"""CSV-driven call import routes (package)."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from loguru import logger
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import Principal, get_principal
from app.core.auth.rbac import require_admin
from app.database import get_db
from app.db_sharding.sessions import is_sharding_enabled
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.services.billing.flexprice_service import record_call_import_batch_created
from app.services.call_imports.audit import (
    actor_emails_for_call_import,
    emails_for_user_ids,
    stamp_call_import_actor,
    user_ids_from_call_imports,
)
from app.services.call_imports.dispatch_diagnostics import (
    build_call_import_dispatch_diagnostics,
)
from app.services.call_imports import diarisation_route_helpers as diarisation_helpers
from app.services.call_imports import manual_audio_route_helpers as manual_audio_helpers
from app.services.call_imports import present as call_import_present
from app.services.call_imports import source_parse as call_import_source_parse
from app.models.database import (
    CallImport,
    CallImportRow,
    CallImportSchema,
    CallImportSchemaParameter,
    CallImportTag,
    TelephonyIntegration,
)
from app.models.enums import (
    CallImportParameterType,
    CallImportRowStatus,
    CallImportStatus,
)
from app.models.schemas import (
    CallImportCancelDiarisationRequest,
    CallImportCancelDiarisationResponse,
    CallImportDetailResponse,
    CallImportDeleteResponse,
    CallImportDiarisationPromptDefaultResponse,
    CallImportDispatchDiagnosticsResponse,
    CallImportInsightsMetric,
    CallImportInsightsResponse,
    CallImportInsightsRunPoint,
    CallImportListResponse,
    CallImportMappingUpdate,
    CallImportManualAudioCompleteRequest,
    CallImportManualAudioCompleteResponse,
    CallImportManualAudioPresignRequest,
    CallImportManualAudioPresignResponse,
    CallImportManualAudioPresignUploadItem,
    CallImportMetricAggregate,
    CallImportPreviewResponse,
    CallImportPreviewSheet,
    CallImportRetryFailedRowsRequest,
    CallImportRetryFailedRowsResponse,
    CallImportResponse,
    CallImportRowIdsResponse,
    CallImportRowBulkDelete,
    CallImportRowBulkDeleteResponse,
    CallImportRowResponse,
    CallImportStartRequest,
    CallImportSourceStageCompleteRequest,
    CallImportSourceStagePresignRequest,
    CallImportSourceStagePresignResponse,
    CallImportTranscribeRequest,
    CallImportTranscribeResponse,
    CallImportUpdate,
    CallImportUploadResponse,
    PlatformImportAgentRef,
)

from app.api.v1.routes.call_imports._router import router

from app.api.v1.routes.call_imports.core_routes import (
    _apply_diarisation_cancel,
    _cancellable_diarisation_states,
    _locate_call_import_row_or_404,
    _render_diarised_segments_text,
)

def _select_rows_for_transcription(
    db: Session,
    call_import: CallImport,
    payload: CallImportTranscribeRequest,
    requested_row_ids: Optional[List[UUID]] = None,
) -> tuple[List[CallImportRow], Dict[str, int]]:
    """Pick which rows to enqueue for diarisation (delegates to bulk_ops)."""
    from app.services.call_imports.bulk_ops import select_rows_for_transcription

    try:
        return select_rows_for_transcription(
            db, call_import, payload, requested_row_ids=requested_row_ids
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/{call_import_id}/transcribe",
    response_model=CallImportTranscribeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="transcribeCallImport",
)
async def transcribe_call_import(
    call_import_id: UUID,
    payload: CallImportTranscribeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportTranscribeResponse:
    """Fan out diarization tasks for many rows in a single call.

    Returns a summary with how many rows were queued and how many were
    skipped (broken down by reason) so the UI can show a meaningful
    toast even when nothing actually got enqueued (e.g. "All 12 rows
    already have transcripts").
    """

    del api_key

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

    from app.workers.tasks.call_import_bulk_ops import bulk_diarize_call_import_task

    stamp_call_import_actor(call_import, principal)
    db.commit()

    bulk_diarize_call_import_task.delay(
        str(call_import_id),
        str(organization_id),
        payload.model_dump(mode="json"),
        [str(rid) for rid in payload.row_ids] if payload.row_ids else None,
    )

    return CallImportTranscribeResponse(
        queued=0,
        skipped_rows=0,
        skipped_reason_counts={},
        accepted=True,
    )


@router.post(
    "/{call_import_id}/rows/{row_id}/transcribe",
    response_model=CallImportTranscribeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="transcribeCallImportRow",
)
async def transcribe_call_import_row(
    call_import_id: UUID,
    row_id: UUID,
    payload: CallImportTranscribeRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportTranscribeResponse:
    """Diarize / transcribe a single row.

    Thin wrapper over the batch endpoint that hard-codes a single
    ``row_ids`` filter. Skip counts still surface so the UI can render
    "Skipped — transcript present" diagnostics consistently.
    """

    del api_key

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

    from app.services.call_imports.bulk_ops import execute_bulk_diarization

    try:
        result = execute_bulk_diarization(
            db,
            call_import,
            payload,
            requested_row_ids=[row_id],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    stamp_call_import_actor(call_import, principal)
    db.commit()

    return CallImportTranscribeResponse(
        queued=result.queued,
        skipped_rows=result.skipped_rows,
        skipped_reason_counts=result.skipped_reason_counts,
    )


# ---------------------------------------------------------------------------
# Cancel-in-flight diarisation
# ---------------------------------------------------------------------------
#
# Long-running multimodal LLM diarisation calls (especially LLM-only mode on
# slow audio) can sit in ``pending`` / ``running`` for tens of minutes when an
# upstream provider stalls. Without an abort affordance the operator's only
# recourse is to wait for Celery's ``time_limit`` to fire — which can be
# several minutes — or to manually mutate the DB. These helpers + the two
# endpoints below give the UI a first-class "Stop diarisation" button.
#
# Why ``terminate=True``: the legacy ``_revoke_pending_tasks`` helper uses
# ``terminate=False`` because it's called from delete-flow paths where the
# task may simply not get to run (a worker pulls it off the queue and drops
# it). For a user-initiated cancel we want SIGTERM to interrupt the worker
# mid-LLM call so the audio HTTP request actually aborts. ``terminate=True``
# routes SIGTERM to the executing process; ``signal="SIGTERM"`` is the
# default but we spell it out so the intent is obvious to reviewers.

# Cancel helpers live in ``app.services.call_imports.diarisation_route_helpers``
# (re-exported at module top for ``bulk_ops`` / evaluation routes).

@router.post(
    "/{call_import_id}/rows/{row_id}/cancel-diarisation",
    response_model=CallImportRowResponse,
    status_code=status.HTTP_200_OK,
    operation_id="cancelCallImportRowDiarisation",
)
async def cancel_call_import_row_diarisation(
    call_import_id: UUID,
    row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportRowResponse:
    """Abort an in-flight (or queued) diarisation for a single row.

    Idempotent: calling on a row that's already terminal (``completed``
    / ``failed`` / ``idle``) returns the row unchanged with a 200, so
    the UI can fire this from a "Stop" button without having to
    pre-check the state.

    Race notes:

    * The row's ``diarised_transcript_status`` is flipped to ``failed``
      with :data:`CANCELLED_BY_USER_ERROR` BEFORE the Celery revoke,
      so the polling UI sees the cancel immediately.
    * If the worker happens to finish between our DB flip and the
      SIGTERM landing, its finaliser will detect the cancelled
      sentinel on the row and skip its own status / score writes
      (see :mod:`app.workers.tasks.transcribe_call_import_row`).
    """
    del api_key

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

    from app.db_sharding.row_ops import close_row_sessions

    row_db, row, extra_catalog = _locate_call_import_row_or_404(
        db,
        call_import_id=call_import_id,
        row_id=row_id,
        organization_id=organization_id,
    )
    try:
        _apply_diarisation_cancel([row])
        row_db.commit()
        stamp_call_import_actor(call_import, principal)
        db.commit()
        row_db.refresh(row)
        return CallImportRowResponse.model_validate(row)
    finally:
        close_row_sessions(row_db, extra_catalog)


@router.post(
    "/{call_import_id}/cancel-diarisation",
    response_model=CallImportCancelDiarisationResponse,
    status_code=status.HTTP_200_OK,
    operation_id="cancelCallImportDiarisation",
)
async def cancel_call_import_diarisation(
    call_import_id: UUID,
    payload: Optional[CallImportCancelDiarisationRequest] = None,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportCancelDiarisationResponse:
    """Abort in-flight diarisation for many rows in a single call.

    Default body (no ``row_ids``) cancels every row in this import
    whose ``diarised_transcript_status`` is ``pending`` or
    ``running`` — the "stop everything" button. Pass ``row_ids`` to
    scope the cancel to the rows the operator has selected.

    Returns ``(cancelled, skipped)`` so the UI can render a tight
    toast ("Cancelled 3 rows · 1 skipped (already completed)").
    """
    del api_key

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

    base_query = db.query(CallImportRow).filter(
        CallImportRow.call_import_id == call_import_id
    )

    requested_ids = (
        payload.row_ids if payload and payload.row_ids is not None else None
    )
    row_filter = payload.row_filter if payload else None
    if row_filter is not None and requested_ids is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pass either row_ids or row_filter, not both.",
        )

    cancelled = 0
    skipped = 0
    skipped_missing = 0

    if row_filter is not None:
        from app.services.call_imports.row_selection import normalize_row_selection_filter
        from app.db_sharding.scatter_gather import fetch_call_import_rows_filtered_page

        search_term, diarised_status = normalize_row_selection_filter(row_filter)
        offset = 0
        page_size = 500
        while True:
            page = fetch_call_import_rows_filtered_page(
                db,
                call_import_id,
                offset=offset,
                limit=page_size,
                search_term=search_term,
                diarised_status_filter=diarised_status,
            )
            if not page:
                break
            page_cancelled, page_skipped = _apply_diarisation_cancel(page)
            cancelled += page_cancelled
            skipped += page_skipped
            if len(page) < page_size:
                break
            offset += page_size
    elif requested_ids is not None:
        if not requested_ids:
            return CallImportCancelDiarisationResponse(cancelled=0, skipped=0)
        rows = base_query.filter(CallImportRow.id.in_(requested_ids)).all()
        found_ids = {r.id for r in rows}
        missing = [rid for rid in requested_ids if rid not in found_ids]
        skipped_missing = len(missing)
        cancelled, skipped = _apply_diarisation_cancel(rows)
    else:
        rows = base_query.filter(
            CallImportRow.diarised_transcript_status.in_(
                list(_cancellable_diarisation_states())
            )
        ).all()
        cancelled, skipped = _apply_diarisation_cancel(rows)

    stamp_call_import_actor(call_import, principal)
    db.commit()
    return CallImportCancelDiarisationResponse(
        cancelled=cancelled,
        skipped=skipped + skipped_missing,
    )


@router.post(
    "/{call_import_id}/rows/{row_id}/diarised-speaker-swap",
    response_model=CallImportRowResponse,
    operation_id="toggleCallImportRowSpeakerSwap",
)
async def toggle_call_import_row_speaker_swap(
    call_import_id: UUID,
    row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportRowResponse:
    """Flip the user <-> agent mapping on a diarised row.

    The worker's "first speaker is the agent" heuristic is right most of
    the time but does fail on inbound recordings where the customer
    greets first, on recordings where the agent stays silent for the
    intro, etc. Rather than rerun the (expensive) STT + pyannote
    pipeline for those cases, we let reviewers flip the mapping in
    place: the structured ``diarised_segments`` are the source of truth
    and we re-render the plain-text ``diarised_transcript`` from them
    with the swap applied. The next CSV export will then show the
    corrected labels.

    Returns the updated row so the frontend can refresh without an
    extra round-trip.
    """

    del api_key

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

    from app.db_sharding.row_ops import close_row_sessions

    row_db, row, extra_catalog = _locate_call_import_row_or_404(
        db,
        call_import_id=call_import_id,
        row_id=row_id,
        organization_id=organization_id,
    )
    try:
        segments = (
            row.diarised_segments if isinstance(row.diarised_segments, list) else None
        )
        if not segments:
            # Without structured turns the swap toggle would have nothing to
            # re-render — surface a clear error rather than silently
            # flipping a flag the UI never read.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This row has no structured diarised segments to swap. "
                    "Re-run diarisation to generate per-speaker turns first."
                ),
            )

        new_swap = not bool(row.diarised_speaker_swap)
        row.diarised_speaker_swap = new_swap
        row.diarised_transcript = (
            _render_diarised_segments_text(segments, swap=new_swap) or None
        )
        row_db.commit()
        stamp_call_import_actor(call_import, principal)
        db.commit()
        row_db.refresh(row)
        return CallImportRowResponse.model_validate(row)
    finally:
        close_row_sessions(row_db, extra_catalog)

