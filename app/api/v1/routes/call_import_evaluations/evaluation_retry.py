"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import statistics
from typing import Any, Dict, Iterator, List, Literal, Optional, Set, Tuple
from uuid import UUID, uuid4

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Float, case, cast, desc, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import Principal, get_principal
from app.core.auth.capabilities import REPORTS_GENERATE, capability_denied_message
from app.database import get_db
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.services.call_imports.audit import (
    actor_emails_for_evaluation,
    emails_for_user_ids,
    stamp_call_import_actor,
    stamp_evaluation_actor,
    user_ids_from_evaluations,
)
from app.services.workspace_rbac import resolve_workspace_capabilities
from app.models.database import (
    AIProvider,
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationReportSnapshot,
    CallImportEvaluationPdfReport,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    PromptPartial,
    Workspace,
)
from app.models.enums import CallImportRowStatus, ModelProvider
from app.models.schemas import (
    CallImportEvaluationAggregateResponse,
    CallImportEvaluationBulkDelete,
    CallImportEvaluationBulkActionResponse,
    CallImportEvaluationCreate,
    CallImportEvaluationExportJobResponse,
    CallImportEvaluationExportRequest,
    CallImportEvaluationListResponse,
    CallImportEvaluationResponse,
    CallImportEvaluationRetryRequest,
    CallImportEvaluationRetryResponse,
    CallImportEvaluationRetrySkippedItem,
    CallImportEvaluationRowListResponse,
    CallImportEvaluationRowResponse,
    CallImportEvaluationUpdate,
    CallImportClassificationFacetCounts,
    CallImportMetricAggregate,
    CallImportMetricHistogramBucket,
    CallImportMetricLabelPair,
    CallImportMetricSummary,
    CallImportMetricValueCount,
    DiscoveredLabelDeleteRequest,
    DiscoveredLabelItem,
    DiscoveredLabelMergeRequest,
    DiscoveredLabelsResponse,
    DiscoveredMetricDeleteRequest,
    DiscoveredMetricItem,
    DiscoveredMetricMergeRequest,
    DiscoveredMetricsResponse,
    EvaluationInsightsRequest,
    EvaluationTldrSummary,
    EvaluationMetricClustersRequest,
    EvaluationMetricClustersState,
    EvaluationPromptImprovementsRequest,
    EvaluationPromptImprovementsState,
    PromptImprovementReviewUpdate,
    PromptPushConfirm,
    PromptPushPreviewResponse,
    PromptPushResponse,
    MetricFailurePoliciesResponse,
    MetricFailurePoliciesSaveRequest,
    MetricFailurePolicy,
    MetricClusterEligibleRow,
    MetricClusterEligibleRowsResponse,
    EvaluationUserInsightsRequest,
    EvaluationUserInsightsState,
    MetricFlowEdge,
    MetricPeriodDelta,
    MetricFlowNode,
    MetricFlowResponse,
)
from app.services.reporting.call_import_evaluation_pdf_report import (
    call_import_evaluation_pdf_report_service,
)
from app.services.reporting.call_import_pdf_report_storage import (
    build_pdf_report_s3_key,
    compute_pdf_report_cache_fingerprint,
    compute_pdf_report_config_fingerprint,
    compute_pdf_report_content_fingerprint,
    config_summary_from_report_config,
    find_cached_pdf_report,
    presigned_urls_for_pdf_report,
)
from app.services.call_import_metric_clusters import (
    METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
    estimate_metric_clusters_llm_calls,
    filter_completed_row_pairs,
    list_eligible_cluster_rows,
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_from_raw,
    metric_clusters_state_to_db,
)
from app.services.classification_metric_scores import classification_facets_from_entry
from app.services.classification_metric_sql import (
    classification_choice_row_predicate,
    classification_level_row_predicate,
)
from app.services.metric_classification_validation import is_classification_metric
from app.services.metric_failure_policy import (
    aggregate_primary_percent,
    build_failure_policy_previews,
    effective_policies,
    failure_rate_percent_from_rows,
    failure_policies_to_db,
    has_clusterable_metrics,
    merge_clustering_policies,
    merge_failure_policies_into_raw,
    policies_from_evaluation_raw,
    validate_failure_policies_for_metrics,
)
from app.services.call_import_user_insights import (
    normalize_max_llm_calls,
    total_llm_calls_for_rows,
    user_insights_state_from_raw,
)


from app.api.v1.routes.call_import_evaluations._router import router

from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _require_import,
    _rollup_evaluation_status,
    _to_evaluation_row_response,
)
from app.api.v1.routes.call_import_evaluations.discovered import (  # noqa: E402
    _is_metric_scores_meta_key,
)
from app.api.v1.routes.call_import_evaluations.evaluation_cancel import (  # noqa: E402
    _claim_evaluation_bulk_operation,
    _require_no_evaluation_bulk_operation,
)
def source_retry_assignments(
    source_row: CallImportRow,
    *,
    transcribe_overwrite: bool,
) -> dict:
    """Columns a retry should write. Empty when the source row is already reusable."""
    from app.api.v1.routes.call_imports import _is_stuck_pending_import_row
    from app.db_sharding.scatter_gather import row_text_present

    changes: dict = {}
    if (getattr(source_row, "celery_task_id", None) or "").strip():
        changes["celery_task_id"] = None

    no_audio = not (getattr(source_row, "recording_s3_key", None) or "").strip()
    status = getattr(source_row, "status", None)
    requeue = no_audio and status in (
        CallImportRowStatus.FAILED,
        CallImportRowStatus.PROCESSING,
    )
    if no_audio and status == CallImportRowStatus.PENDING:
        requeue = _is_stuck_pending_import_row(source_row)
    if requeue:
        if status != CallImportRowStatus.PENDING:
            changes["status"] = CallImportRowStatus.PENDING
        if getattr(source_row, "error_message", None) is not None:
            changes["error_message"] = None
        if (getattr(source_row, "attempts", 0) or 0) != 0:
            changes["attempts"] = 0

    has_dia = row_text_present(
        source_row, "diarised_transcript", "diarised_transcript_char_length"
    )
    if transcribe_overwrite and has_dia:
        changes["diarised_transcript"] = None
        has_dia = False

    dia_status = (
        getattr(source_row, "diarised_transcript_status", None) or ""
    ).strip().lower()
    if has_dia and not transcribe_overwrite:
        if dia_status != "completed":
            changes["diarised_transcript_status"] = "completed"
        if getattr(source_row, "diarised_transcript_error", None) is not None:
            changes["diarised_transcript_error"] = None
        return changes

    if dia_status in {"failed", "pending", "running", "idle"}:
        if dia_status != "idle":
            changes["diarised_transcript_status"] = "idle"
        if getattr(source_row, "diarised_transcript_error", None) is not None:
            changes["diarised_transcript_error"] = None
    return changes


def _prepare_source_row_for_retry(
    source_row: CallImportRow,
    *,
    transcribe_overwrite: bool,
) -> None:
    """Clear stale diarisation markers so retry dispatch can re-run the pipeline."""
    for column, value in source_retry_assignments(
        source_row,
        transcribe_overwrite=transcribe_overwrite,
    ).items():
        setattr(source_row, column, value)


def _metric_scores_for_retry(existing, metric_ids: Optional[List[UUID]]) -> dict:
    """Full retry clears every score. A metric subset removes only those keys."""
    if not metric_ids:
        return {}
    scores = existing if isinstance(existing, dict) else {}
    target_keys = {str(mid).lower() for mid in metric_ids}
    return {
        key: value
        for key, value in scores.items()
        if _is_metric_scores_meta_key(str(key))
        or str(key).lower() not in target_keys
    }


def _reset_eval_row_for_retry(
    eval_row: CallImportEvaluationRow,
    *,
    metric_ids: Optional[List[UUID]] = None,
    skip_revoke: bool = False,
    skip_chain: bool = False,
) -> None:
    """Wipe per-row state so the worker can re-run it cleanly.

    Mirrors the initial state used by ``create_call_import_evaluation``
    when it first inserts a row, with the addition of revoking any
    lingering Celery task id.

    When ``metric_ids`` is provided, this is a **metric-subset retry**:
    only the scores for those metrics are removed from
    ``metric_scores`` (other metrics' previously-computed values are
    preserved so the worker's partial-merge write keeps them intact).
    Otherwise the entire ``metric_scores`` dict is reset, matching the
    legacy behaviour.
    """
    if (
        not skip_revoke
        and eval_row.celery_task_id
        and eval_row.status in {"pending", "running"}
    ):
        try:
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(eval_row.celery_task_id, terminate=False)
        except Exception:  # noqa: BLE001 — revoke is best-effort
            pass
    eval_row.status = "pending"
    eval_row.error_message = None
    eval_row.metric_scores = _metric_scores_for_retry(
        eval_row.metric_scores,
        metric_ids,
    )
    eval_row.started_at = None
    eval_row.finished_at = None
    task_id = (eval_row.celery_task_id or "").strip()
    eval_row.celery_task_id = None
    if skip_chain or not task_id:
        return
    from app.workers.tasks.evaluate_call_import_row_audio import (
        clear_eval_audio_chain,
    )

    clear_eval_audio_chain(str(eval_row.id))


def _enqueue_eval_rows_with_optional_transcribe(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_rows_with_source: List[
        Tuple[CallImportEvaluationRow, CallImportRow]
    ],
    *,
    transcribe_overwrite: bool = False,
    restricted_metric_ids: Optional[List[UUID]] = None,
) -> Tuple[int, int]:
    """Schedule throttled evaluation dispatch for pending eval rows.

    Returns ``(evaluate_only_count, transcribe_then_evaluate_count)`` for
    logging/UI compatibility. Actual Celery fan-out is handled by
    :func:`dispatch_evaluation_rows_task` under Redis fair-share limits.
    """
    from app.workers.concurrency.eval_dispatch import _needs_transcribe_for_eval
    from app.workers.concurrency.fair_dispatch import (
        schedule_fair_dispatch,
        store_evaluation_transcribe_overwrite,
        store_row_restricted_metrics,
    )

    eval_only_count = 0
    transcribe_count = 0
    if eval_rows_with_source:
        for eval_row, source_row in eval_rows_with_source:
            if _needs_transcribe_for_eval(
                evaluation,
                source_row,
                transcribe_overwrite=transcribe_overwrite,
            ):
                transcribe_count += 1
            else:
                eval_only_count += 1

        restricted_metric_ids_str: Optional[List[str]] = (
            [str(mid) for mid in restricted_metric_ids]
            if restricted_metric_ids
            else None
        )
        if restricted_metric_ids_str:
            for eval_row, _ in eval_rows_with_source:
                store_row_restricted_metrics(eval_row.id, restricted_metric_ids_str)
    else:
        restricted_metric_ids_str = (
            [str(mid) for mid in restricted_metric_ids] if restricted_metric_ids else None
        )
    store_evaluation_transcribe_overwrite(
        evaluation.id,
        overwrite=transcribe_overwrite,
    )
    schedule_fair_dispatch(max_workspace_turns=999)
    return eval_only_count, transcribe_count


def _apply_telephony_retry_overrides(
    db: Session,
    *,
    call_import: CallImport,
    organization_id: UUID,
    payload: CallImportEvaluationRetryRequest,
) -> None:
    """Pin or clear telephony credentials on the batch for this retry pass."""
    fields_set = payload.model_fields_set
    if (
        "provider" not in fields_set
        and "telephony_integration_id" not in fields_set
    ):
        return

    from app.api.v1.routes.call_imports import (
        _resolve_telephony_integration,
        _validate_telephony_credentials_live,
    )

    if payload.telephony_integration_id is not None:
        integration = _resolve_telephony_integration(
            db,
            organization_id,
            payload.telephony_integration_id,
            payload.provider or "",
        )
        _validate_telephony_credentials_live(db, organization_id, integration)
        call_import.provider = integration.provider
        call_import.telephony_integration_id = integration.id
    else:
        call_import.provider = None
        call_import.telephony_integration_id = None
    db.flush()


def _apply_retry_overrides(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    payload: CallImportEvaluationRetryRequest,
) -> None:
    """Validate + persist the LLM/STT override fields on the run.

    Mirrors the validation in ``create_call_import_evaluation`` but
    only touches the fields the caller actually sent — leaving any
    field ``None`` preserves the run's existing value. Raises
    ``HTTPException(400)`` on bad input so the route handler can let
    FastAPI turn it into a clean 400 response.
    """
    # --- LLM provider + model (must be sent together) ---
    if payload.llm_provider is not None or payload.llm_model is not None:
        if not (payload.llm_provider and payload.llm_model):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Both llm_provider and llm_model are required when "
                    "overriding the run LLM on retry."
                ),
            )
        try:
            evaluation.llm_provider = ModelProvider(
                payload.llm_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown LLM provider '{payload.llm_provider}'. "
                    "Valid keys are documented in ModelProvider."
                ),
            )
        new_model = payload.llm_model.strip() or None
        if not new_model:
            raise HTTPException(
                status_code=400, detail="llm_model cannot be empty."
            )
        evaluation.llm_model = new_model

    # --- LLM credential pin ---
    if payload.llm_credential_id is not None:
        cred = (
            db.query(AIProvider)
            .filter(
                AIProvider.id == payload.llm_credential_id,
                AIProvider.organization_id == organization_id,
            )
            .first()
        )
        if not cred:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The provided llm_credential_id does not exist in "
                    "this organization."
                ),
            )
        evaluation.llm_credential_id = payload.llm_credential_id

    if payload.llm_config is not None:
        evaluation.llm_config = payload.llm_config

    # --- Per-metric LLM overrides ---
    # We accept the same dict shape as the create endpoint but
    # constrain keys to leaf metrics that are actually in this run.
    # Passing an empty dict explicitly clears existing overrides.
    if payload.metric_llm_overrides is not None:
        valid_leaf_ids = {
            str(mid) for mid in (evaluation.selected_metric_ids or [])
        }
        overrides_payload: Dict[str, Dict[str, Any]] = {}
        for metric_id, override in payload.metric_llm_overrides.items():
            if metric_id not in valid_leaf_ids:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "metric_llm_overrides references metric "
                        f"{metric_id} which is not a leaf metric in "
                        "this run."
                    ),
                )
            override_dict: Dict[str, Any] = {}
            if override.provider is not None:
                if not override.model:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Override for metric {metric_id} has a "
                            "provider but no model."
                        ),
                    )
                try:
                    override_dict["provider"] = ModelProvider(
                        override.provider.lower()
                    ).value
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Override for metric {metric_id} uses "
                            f"unknown provider '{override.provider}'."
                        ),
                    )
                override_dict["model"] = override.model.strip()
            elif override.model:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Override for metric {metric_id} has a model "
                        "but no provider."
                    ),
                )
            if override.credential_id is not None:
                override_dict["credential_id"] = str(override.credential_id)
            if override.llm_config is not None:
                override_dict["llm_config"] = override.llm_config
            if override_dict:
                overrides_payload[metric_id] = override_dict
        evaluation.metric_llm_overrides = overrides_payload or None

    # --- STT provider + model (must be sent together) ---
    if payload.stt_provider is not None or payload.stt_model is not None:
        if not (payload.stt_provider and payload.stt_model):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Both stt_provider and stt_model are required "
                    "when overriding the run STT on retry."
                ),
            )
        try:
            evaluation.stt_provider = ModelProvider(
                payload.stt_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown STT provider '{payload.stt_provider}'.",
            )
        new_stt_model = payload.stt_model.strip() or None
        if not new_stt_model:
            raise HTTPException(
                status_code=400, detail="stt_model cannot be empty."
            )
        evaluation.stt_model = new_stt_model

    # --- STT credential pin ---
    if payload.stt_credential_id is not None:
        evaluation.stt_credential_id = payload.stt_credential_id

    # --- LLM diariser provider + model (must be sent together) ---
    if (
        payload.diarization_llm_provider is not None
        or payload.diarization_llm_model is not None
    ):
        if not (
            payload.diarization_llm_provider
            and payload.diarization_llm_model
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Both diarization_llm_provider and "
                    "diarization_llm_model are required when overriding "
                    "the run diariser on retry."
                ),
            )
        try:
            evaluation.diarisation_llm_provider = ModelProvider(
                payload.diarization_llm_provider.lower()
            ).value
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unknown diarisation LLM provider "
                    f"'{payload.diarization_llm_provider}'."
                ),
            )
        new_diariser_model = (
            payload.diarization_llm_model.strip() or None
        )
        if not new_diariser_model:
            raise HTTPException(
                status_code=400,
                detail="diarization_llm_model cannot be empty.",
            )
        evaluation.diarisation_llm_model = new_diariser_model

    if payload.diarization_llm_credential_id is not None:
        evaluation.diarisation_llm_credential_id = (
            payload.diarization_llm_credential_id
        )

    # ``diarization_prompt`` semantics: None = leave untouched;
    # empty string = clear (fall back to the canonical default at
    # worker time); anything else = persist verbatim.
    if payload.diarization_prompt is not None:
        cleaned = payload.diarization_prompt.strip()
        evaluation.diarisation_prompt = cleaned or None

    if payload.transcribe_mode is not None:
        mode = payload.transcribe_mode.strip().lower()
        if mode not in {"stt_llm", "llm_only"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown transcribe_mode '{payload.transcribe_mode}'. "
                    "Valid values are 'stt_llm' and 'llm_only'."
                ),
            )
        evaluation.transcribe_mode = mode


def _gather_retry_targets(
    db: Session,
    evaluation: CallImportEvaluation,
    requested_ids: Optional[List[UUID]],
    *,
    include_completed: bool = False,
) -> Tuple[
    List[Tuple[CallImportEvaluationRow, CallImportRow]],
    List[CallImportEvaluationRetrySkippedItem],
]:
    """Resolve which rows to retry + reasons for any we refuse.

    When ``requested_ids`` is None we retry every row whose status is
    ``failed`` (or every row when ``include_completed`` is also set —
    used by the metric-subset retry path which legitimately wants to
    recompute a metric on already-successful rows). When the caller
    passes ids explicitly we still filter out rows that are currently
    in flight; ``include_completed`` controls whether previously-
    successful rows are eligible.
    """
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        from app.db_sharding.eval_rows import gather_retry_targets_sharded

        return gather_retry_targets_sharded(
            db,
            evaluation,
            requested_ids,
            include_completed=include_completed,
        )

    from app.db_sharding.eval_rows import _collect_retry_targets_on_session

    targets, skipped, found = _collect_retry_targets_on_session(
        db,
        evaluation,
        requested_ids,
        include_completed=include_completed,
    )
    if requested_ids is not None:
        for missing in set(requested_ids) - found:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=missing,
                    reason="unknown",
                )
            )
    return targets, skipped


@router.post(
    "/{eval_id}/retry",
    response_model=CallImportEvaluationRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="retryCallImportEvaluation",
)
async def retry_call_import_evaluation(
    call_import_id: UUID,
    eval_id: UUID,
    payload: Optional[CallImportEvaluationRetryRequest] = Body(default=None),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRetryResponse:
    """Re-enqueue failed rows in an evaluation run.

    Default behavior (no body) is "retry every row that failed". Pass
    ``eval_row_ids`` to scope the retry to a specific subset (e.g. the
    single row a user clicked in the UI). Rows that are still
    in-flight or already completed are returned in ``skipped`` rather
    than re-enqueued, so this endpoint is always safe to call.

    When ``metric_ids`` is set in the payload, this is a **metric-
    subset retry**: only the listed metrics are recomputed (and merged
    into the row's existing ``metric_scores`` — other metrics' values
    are preserved). The route auto-flips ``include_completed=True`` in
    that case so previously-successful rows are eligible for re-
    scoring; without it the call would no-op because every row would
    be skipped as ``completed``.

    The worker contract is the same as the create endpoint:
    ``evaluate_call_import_row_task(eval_row_id, [restricted_metric_ids])``.
    When the run is configured for diarised transcripts and the row's
    diarised transcript is missing, we chain through
    ``transcribe_call_import_row_task`` first — matching the
    auto-transcribe behavior of POST ``/evaluations``.
    """
    del api_key
    call_import = _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(
            status_code=404, detail="Call import evaluation not found"
        )

    requested_ids = payload.eval_row_ids if payload else None
    retry_filter = payload.row_filter if payload else None
    _MAX_EXPLICIT_EVAL_RETRY_IDS = 500
    if requested_ids is not None and len(requested_ids) > _MAX_EXPLICIT_EVAL_RETRY_IDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"At most {_MAX_EXPLICIT_EVAL_RETRY_IDS} eval_row_ids per request; "
                "use row_filter for bulk retry."
            ),
        )
    # Metric-subset retry: validate that every metric is something this
    # run actually scored. Empty list is rejected too — callers that
    # want a full re-run should omit the field entirely.
    #
    # ``selected_metric_ids`` holds the LEAVES only (children for
    # hierarchical / category metrics, standalone metrics otherwise) —
    # see ``leaf_metric_ids`` in :func:`create_call_import_evaluation`.
    # Parent IDs for hierarchical metrics live separately in
    # ``selected_metric_groups`` (``{parent_id: [child_ids]}``) so the
    # UI can reconstruct the tree without round-tripping through the
    # metric table.
    #
    # The Re-run-metrics modal surfaces PARENTS for hierarchical
    # metrics (it suppresses individual children via
    # ``childrenInGroups`` in ``CallImportEvaluationDetail.tsx``), so a
    # naive ``metric_ids Γèå selected_metric_ids`` check rejects every
    # parent-ID request with a misleading "unknown ids" 400. We accept
    # both shapes here and then EXPAND any parent IDs into
    # ``{parent_id, *child_ids}`` so the downstream helpers see the
    # full set of keys that need clearing + the full set of leaves
    # that need re-scoring.
    metric_ids: Optional[List[UUID]] = (
        payload.metric_ids if payload else None
    )
    if metric_ids is not None:
        metric_ids = [
            mid for mid in metric_ids if not _is_metric_scores_meta_key(str(mid))
        ]
        if not metric_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "metric_ids must be a non-empty list of metric UUIDs. "
                    "Omit the field to re-run all metrics."
                ),
            )

        leaf_set: Set[str] = {
            str(item).lower()
            for item in (evaluation.selected_metric_ids or [])
        }
        # ``selected_metric_groups`` is a dict ``{parent_id_str:
        # [child_id_str, ...]}`` (see line ~487 in
        # ``create_call_import_evaluation``). We tolerate stale data
        # (string / UUID / non-dict) without crashing the retry path —
        # if it's malformed we just treat it as "no parents" and fall
        # back to the leaf-only check.
        groups_raw = (
            evaluation.selected_metric_groups
            if isinstance(evaluation.selected_metric_groups, dict)
            else {}
        )
        parent_to_children_str: Dict[str, List[str]] = {}
        for parent_key, children_raw in groups_raw.items():
            if not isinstance(children_raw, (list, tuple)):
                continue
            children_norm = [
                str(c).lower() for c in children_raw if c is not None
            ]
            parent_to_children_str[str(parent_key).lower()] = children_norm
        parent_set = set(parent_to_children_str.keys())

        unknown = [
            mid for mid in metric_ids
            if str(mid).lower() not in leaf_set
            and str(mid).lower() not in parent_set
        ]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    "metric_ids must be a subset of this evaluation's "
                    f"selected metrics; unknown ids: {[str(u) for u in unknown]}."
                ),
            )

        # Expand parent IDs into ``{parent, *children}`` so:
        #   * ``_reset_eval_row_for_retry`` strips BOTH the parent
        #     entry (with ``chosen_child_id`` / rationale) AND every
        #     per-child boolean entry that the LLM evaluator wrote
        #     under each child's ID (see
        #     ``app/workers/tasks/helpers/llm_evaluation.py`` lines
        #     1584 and 1649).
        #   * ``_enqueue_eval_rows_with_optional_transcribe`` →
        #     ``evaluate_call_import_row_task`` filters the work-list
        #     off ``selected_metric_ids`` (leaves), so we MUST hand it
        #     the child IDs for the parent to actually get re-scored.
        # Leaves pass through unchanged.
        expanded: List[UUID] = []
        seen: Set[str] = set()
        for mid in metric_ids:
            mid_norm = str(mid).lower()
            children_str = parent_to_children_str.get(mid_norm)
            if children_str is not None:
                # Parent: include the parent ID itself (so the parent
                # entry in ``metric_scores`` is also cleared) and all
                # of its children.
                candidates = [mid_norm, *children_str]
            else:
                candidates = [mid_norm]
            for candidate in candidates:
                if candidate in seen:
                    continue
                try:
                    expanded.append(UUID(candidate))
                except (TypeError, ValueError):
                    # Defensive: skip junk values rather than 500.
                    continue
                seen.add(candidate)
        metric_ids = expanded

    # ``include_completed`` is auto-enabled when the caller asked for a
    # metric subset (otherwise the metric-subset retry would always
    # no-op on a green run, which is the whole reason this feature
    # exists). The explicit payload flag wins for full-row retries.
    include_completed = bool(
        (payload.include_completed if payload else False)
        or (metric_ids is not None)
    )

    transcribe_overwrite = bool(
        payload.transcribe_overwrite if payload else False
    )

    skipped: List[CallImportEvaluationRetrySkippedItem] = []
    retry_search = (retry_filter.q or "").strip() if retry_filter else ""
    retry_status = (
        (retry_filter.status or "").strip().lower() if retry_filter and retry_filter.status else None
    )
    if requested_ids is None:
        from app.db_sharding.eval_rows import (
            count_evaluation_retry_targets,
            count_evaluation_rows_for_run,
        )
        from app.db_sharding.sessions import is_sharding_enabled

        if retry_filter is not None or retry_search:
            if retry_status and include_completed and retry_status not in {
                "failed",
                "completed",
            }:
                statuses = [retry_status]
            elif retry_status:
                statuses = [retry_status]
            else:
                statuses = (
                    ["failed", "completed"] if include_completed else ["failed"]
                )
            target_count = count_evaluation_retry_targets(
                db,
                eval_id,
                statuses=statuses,
                search_term=retry_search,
            )
        elif is_sharding_enabled():
            statuses = (
                ["failed", "completed"] if include_completed else ["failed"]
            )
            target_count = count_evaluation_rows_for_run(
                db, eval_id, statuses=statuses
            )
        else:
            from sqlalchemy import func

            count_query = db.query(func.count(CallImportEvaluationRow.id)).filter(
                CallImportEvaluationRow.evaluation_id == eval_id
            )
            if include_completed:
                count_query = count_query.filter(
                    CallImportEvaluationRow.status.in_(["failed", "completed"])
                )
            else:
                count_query = count_query.filter(
                    CallImportEvaluationRow.status == "failed"
                )
            target_count = int(count_query.scalar() or 0)
        if target_count == 0:
            return CallImportEvaluationRetryResponse(
                requeued=0,
                transcribe_requeued=0,
                skipped=skipped,
            )
    else:
        targets, skipped = _gather_retry_targets(
            db,
            evaluation,
            requested_ids,
            include_completed=include_completed,
        )
        if not targets:
            return CallImportEvaluationRetryResponse(
                requeued=0,
                transcribe_requeued=0,
                skipped=skipped,
            )
        target_count = len(targets)

    # Apply LLM / STT overrides BEFORE enqueueing so the persisted run
    # config is correct by the time the worker reads it.
    if payload is not None:
        _apply_retry_overrides(db, evaluation, organization_id, payload)
        _apply_telephony_retry_overrides(
            db,
            call_import=call_import,
            organization_id=organization_id,
            payload=payload,
        )

    evaluation.error_message = None
    evaluation.finished_at = None
    evaluation.status = "running"
    if not evaluation.started_at:
        from datetime import datetime, timezone

        evaluation.started_at = datetime.now(timezone.utc)

    _claim_evaluation_bulk_operation(eval_id, "retry")
    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    from app.workers.tasks.call_import_bulk_ops import (
        retry_call_import_evaluation_task,
    )

    retry_call_import_evaluation_task.delay(
        str(eval_id),
        {
            "eval_row_ids": [str(rid) for rid in requested_ids]
            if requested_ids
            else None,
            "metric_ids": [str(mid) for mid in metric_ids] if metric_ids else None,
            "include_completed": include_completed,
            "transcribe_overwrite": transcribe_overwrite,
            "retry_search_term": retry_search or None,
            "retry_status_filter": retry_status,
        },
    )

    return CallImportEvaluationRetryResponse(
        requeued=target_count,
        transcribe_requeued=0,
        skipped=skipped,
    )


@router.post(
    "/{eval_id}/rows/{eval_row_id}/retry",
    response_model=CallImportEvaluationRowResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="retryCallImportEvaluationRow",
)
async def retry_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    eval_row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowResponse:
    """Re-enqueue a single failed evaluation row.

    Convenience wrapper around ``retry_call_import_evaluation`` for the
    "Retry this row" affordance in the row table. Returns the
    refreshed row so the UI can update its badge immediately, without
    waiting for the next polling tick.
    """
    del api_key
    _require_import(db, call_import_id, organization_id)

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not evaluation:
        raise HTTPException(
            status_code=404, detail="Call import evaluation not found"
        )

    _require_no_evaluation_bulk_operation(eval_id)

    from app.db_sharding.eval_rows import (
        evaluation_row_session,
        find_evaluation_row_in_run,
    )
    from app.db_sharding.sessions import is_sharding_enabled

    eval_row, _source_stub = find_evaluation_row_in_run(db, eval_id, eval_row_id)
    if eval_row is None:
        raise HTTPException(
            status_code=404, detail="Evaluation row not found in this run"
        )

    if eval_row.status in {"pending", "running"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "This row is still in progress — wait for it to finish "
                "before retrying."
            ),
        )

    targets, _ = _gather_retry_targets(db, evaluation, [eval_row.id])
    if not targets:
        raise HTTPException(
            status_code=409,
            detail=(
                "This row cannot be retried in its current state "
                f"(status={eval_row.status})."
            ),
        )

    if is_sharding_enabled():
        with evaluation_row_session(eval_row_id) as (
            row_db,
            _catalog_db,
            eval_row,
            source_row,
            _shard_id,
        ):
            _prepare_source_row_for_retry(source_row, transcribe_overwrite=False)
            _reset_eval_row_for_retry(eval_row)
            row_db.commit()
            targets = [(eval_row, source_row)]
    else:
        for er, source_row in targets:
            _prepare_source_row_for_retry(source_row, transcribe_overwrite=False)
            _reset_eval_row_for_retry(er)

    evaluation.error_message = None
    evaluation.finished_at = None
    evaluation.status = "running"
    if not evaluation.started_at:
        from datetime import datetime, timezone

        evaluation.started_at = datetime.now(timezone.utc)
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    stamp_evaluation_actor(evaluation, principal)
    db.commit()

    try:
        _enqueue_eval_rows_with_optional_transcribe(db, evaluation, targets)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to re-enqueue retry for evaluation row {}", eval_row_id
        )
        if is_sharding_enabled():
            with evaluation_row_session(eval_row_id) as (
                row_db,
                _catalog_db,
                eval_row,
                _source_row,
                _shard_id,
            ):
                eval_row.status = "failed"
                eval_row.error_message = f"Failed to re-enqueue retry: {exc}"
                row_db.commit()
        else:
            eval_row.status = "failed"
            eval_row.error_message = f"Failed to re-enqueue retry: {exc}"
        _rollup_evaluation_status(evaluation, db)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to re-enqueue retry: {exc}",
        )

    if is_sharding_enabled():
        with evaluation_row_session(eval_row_id) as (
            _row_db,
            _catalog_db,
            eval_row,
            source_row,
            _shard_id,
        ):
            return _to_evaluation_row_response(eval_row, source_row, evaluation)

    db.refresh(eval_row)
    source_row = targets[0][1]
    return _to_evaluation_row_response(eval_row, source_row, evaluation)
