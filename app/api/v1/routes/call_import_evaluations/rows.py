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
    _pick_evaluation_row_transcript,
    _require_import,
    _rollup_evaluation_status,
    _to_evaluation_row_response,
)
from app.api.v1.routes.call_import_evaluations.evaluation_cancel import (  # noqa: E402
    _apply_evaluation_cancel,
    _cancel_eval_row_with_source_diarisation,
    _revoke_eval_task,
)

def _apply_classification_metric_filters(
    query,
    metric_id: UUID,
    *,
    yes_no: Optional[str] = None,
    choice: Optional[str] = None,
    level: Optional[str] = None,
):
    """Restrict rows by Jev classification facets under ``metric_scores``."""
    mid = str(metric_id)
    scores = CallImportEvaluationRow.metric_scores

    if yes_no and yes_no.strip():
        yn = yes_no.strip().lower()
        if yn in ("yes", "no"):
            noul_txt = func.json_extract_path_text(
                scores, mid, "answers", "noul", "noul"
            )
            noul_f = cast(noul_txt, Float)
            derived = case(
                (noul_f >= 0.5, "Yes"),
                (noul_f.isnot(None), "No"),
                else_=None,
            )
            effective = func.coalesce(
                func.json_extract_path_text(scores, mid, "classification_yes_no"),
                derived,
            )
            query = query.filter(func.lower(effective) == yn)

    if choice and choice.strip():
        query = query.filter(classification_choice_row_predicate(mid, choice))

    if level and level.strip():
        query = query.filter(classification_level_row_predicate(mid, level))

    return query


@router.get(
    "/{eval_id}/rows",
    response_model=CallImportEvaluationRowListResponse,
    operation_id="listCallImportEvaluationRows",
)
async def list_call_import_evaluation_rows(
    call_import_id: UUID,
    eval_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    q: Optional[str] = Query(
        None,
        description=(
            "Free-text search across conversation_id and transcript "
            "(case-insensitive substring match)."
        ),
    ),
    metric_id: Optional[UUID] = Query(
        None,
        description=(
            "If set, only return rows whose ``metric_scores[metric_id].value`` "
            "exactly matches ``metric_value`` (string-compared). "
            "Use together with ``metric_value``."
        ),
    ),
    metric_value: Optional[str] = Query(
        None,
        description="Value to match against metric_id (string compare).",
    ),
    classification_yes_no: Optional[str] = Query(
        None,
        description=(
            "With ``metric_id``, filter classification metrics by Yes/No "
            "(case-insensitive)."
        ),
    ),
    classification_choice: Optional[str] = Query(
        None,
        description=(
            "With ``metric_id``, filter classification metrics by category "
            "choice (case-insensitive)."
        ),
    ),
    classification_level: Optional[str] = Query(
        None,
        description=(
            "With ``metric_id``, filter classification metrics by level label "
            "(case-insensitive)."
        ),
    ),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Restrict to rows with this evaluation row status.",
    ),
    flow_parent_id: Optional[UUID] = Query(
        None,
        description=(
            "Parent (category) metric whose ``sequence`` array should be "
            "checked against ``flow_node`` and ``flow_edge_target``. Used "
            "to drill into the calls behind a flow-chart node or edge."
        ),
    ),
    flow_node: Optional[str] = Query(
        None,
        description=(
            "If set together with ``flow_parent_id``, only return rows "
            "whose sequence under that parent contains this step. Accepts "
            "either a child metric UUID (resolved to slug(name)), a "
            "``disc:<slug>`` discovered-label id, or a raw slug."
        ),
    ),
    flow_edge_target: Optional[str] = Query(
        None,
        description=(
            "Optional companion to ``flow_node``: when set, restrict to "
            "rows whose sequence contains the directed transition "
            "``flow_node -> flow_edge_target`` (immediately adjacent). "
            "Same id format as ``flow_node``."
        ),
    ),
    discovered_parent_id: Optional[UUID] = Query(
        None,
        description=(
            "Parent (category) metric that defines the discovery scope "
            "for ``discovered_label_key`` / ``has_discovered``."
        ),
    ),
    discovered_label_key: Optional[str] = Query(
        None,
        description=(
            "If set together with ``discovered_parent_id``, only return "
            "rows whose ``metric_scores[parent].discovered_labels`` "
            "list contains an entry with this slug (after applying "
            "evaluation-level merge aliases)."
        ),
    ),
    has_discovered: Optional[bool] = Query(
        None,
        description=(
            "If true together with ``discovered_parent_id``, only return "
            "rows that have at least one LLM-discovered label for the "
            "parent. Useful to triage which calls produced novel labels."
        ),
    ),
    sort_by: Optional[str] = Query(
        None,
        description=(
            "Column to sort by. Accepted values: ``row_index`` (default "
            "when omitted), ``conversation_id``, ``status`` (the "
            "evaluation-row status), or ``metric:<metric_uuid>`` to sort "
            "by ``metric_scores[<uuid>].value``. Metric sorts compare "
            "the extracted JSON text — adequate for booleans, enum "
            "labels, and 0-1 ratings; large integer values may sort "
            "lexicographically (10 before 2)."
        ),
    ),
    sort_dir: Optional[str] = Query(
        "asc",
        description="Sort direction: ``asc`` (default) or ``desc``.",
    ),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowListResponse:
    del api_key
    _require_import(db, call_import_id, organization_id)

    eval_row = (
        db.query(CallImportEvaluation)
        .filter(
            CallImportEvaluation.id == eval_id,
            CallImportEvaluation.call_import_id == call_import_id,
            CallImportEvaluation.organization_id == organization_id,
        )
        .first()
    )
    if not eval_row:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    query = (
        db.query(CallImportEvaluationRow, CallImportRow)
        .join(CallImportRow, CallImportRow.id == CallImportEvaluationRow.call_import_row_id)
        .filter(CallImportEvaluationRow.evaluation_id == eval_id)
    )

    # --- Filters ----------------------------------------------------------
    if q and q.strip():
        needle = f"%{q.strip()}%"
        # Search across both transcript columns so a hit in either the
        # production or the diarised version surfaces the row,
        # independent of which source the evaluation actually scored.
        query = query.filter(
            or_(
                CallImportRow.conversation_id.ilike(needle),
                CallImportRow.transcript.ilike(needle),
                CallImportRow.diarised_transcript.ilike(needle),
            )
        )

    if status_filter:
        # The CallImportEvaluationRow.status column is a string in PG so a
        # plain == filter works; we lowercase to match the stored values.
        query = query.filter(
            CallImportEvaluationRow.status == status_filter.strip().lower()
        )

    if metric_id is not None and metric_value is not None:
        # ``metric_scores`` is a JSONB column shaped like
        # ``{"<metric_id>": {"value": <X>, "type": "boolean", ...}}``. We
        # extract the nested ``value`` as text and compare to the user
        # input as a string — that handles bool/int/enum without needing
        # per-type casts. ``metric_value`` is matched case-insensitively
        # so chart clicks on labels like "True" survive any casing drift
        # between worker output and the chart label.
        path_value = func.json_extract_path_text(
            CallImportEvaluationRow.metric_scores,
            str(metric_id),
            "value",
        )
        query = query.filter(func.lower(path_value) == metric_value.strip().lower())

    if metric_id is not None and (
        (classification_yes_no and classification_yes_no.strip())
        or (classification_choice and classification_choice.strip())
        or (classification_level and classification_level.strip())
    ):
        query = _apply_classification_metric_filters(
            query,
            metric_id,
            yes_no=classification_yes_no,
            choice=classification_choice,
            level=classification_level,
        )

    # --- Flow chart drilldown filter -------------------------------------
    # Translates a clicked node (or edge) on the flow chart into a
    # SQL filter against ``metric_scores[<parent>].sequence``. The
    # frontend sends either a child UUID, a ``disc:<slug>`` discovered
    # node id, or a raw slug — we normalize all three to the slug that
    # actually appears in stored ``sequence`` arrays.
    if flow_parent_id is not None and flow_node and flow_node.strip():
        parent_id_str_local = str(flow_parent_id)
        alias_map_flow = _alias_map_for_parent(eval_row, flow_parent_id)

        def _flow_node_to_slug(raw: str) -> Optional[str]:
            raw_clean = raw.strip()
            if not raw_clean:
                return None
            if raw_clean == _FLOW_START_NODE_ID:
                # The synthetic START node isn't a real sequence entry;
                # filtering on it is meaningless so we skip silently.
                return None
            if raw_clean.startswith(_DISCOVERED_NODE_PREFIX):
                return _resolve_alias(
                    alias_map_flow,
                    _slug_label(raw_clean[len(_DISCOVERED_NODE_PREFIX) :]),
                )
            # Try to interpret as a child metric UUID first; fall back
            # to treating it as a slug.
            try:
                child_uuid = UUID(raw_clean)
            except (TypeError, ValueError):
                return _resolve_alias(alias_map_flow, _slug_label(raw_clean))
            child = (
                db.query(Metric.name)
                .filter(
                    Metric.id == child_uuid,
                    Metric.organization_id == organization_id,
                )
                .first()
            )
            if child and child[0]:
                return _resolve_alias(alias_map_flow, _slug_label(child[0]))
            return _resolve_alias(alias_map_flow, _slug_label(raw_clean))

        from_slug = _flow_node_to_slug(flow_node)
        target_slug: Optional[str] = None
        if flow_edge_target and flow_edge_target.strip():
            target_slug = _flow_node_to_slug(flow_edge_target)

        if from_slug:
            # The ``metric_scores`` column is declared as ``Column(JSON)``
            # in the model so on databases where the table was created
            # from the model (rather than the migration) the physical
            # type is ``json``, not ``jsonb``. The JSONB-only operators
            # below (``jsonb_exists``, ``jsonb_array_elements_text``,
            # ``@>``) require a JSONB input — we cast once up front so
            # the same SQL works regardless of which path created the
            # table.
            scores_jsonb = (
                "(call_import_evaluation_rows.metric_scores)::jsonb"
            )
            if target_slug:
                # Edge filter: rows whose sequence under this parent
                # contains ``from_slug`` immediately followed by
                # ``target_slug``. Implemented as a correlated EXISTS
                # over ``jsonb_array_elements_text`` with ORDINALITY,
                # which is the portable way to express "next array
                # index" against a JSONB array in Postgres.
                edge_filter_sql = text(
                    f"""
                    EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(
                            COALESCE(
                                {scores_jsonb} -> :p_id -> 'sequence',
                                '[]'::jsonb
                            )
                        ) WITH ORDINALITY AS s1(elem, ord)
                        JOIN jsonb_array_elements_text(
                            COALESCE(
                                {scores_jsonb} -> :p_id -> 'sequence',
                                '[]'::jsonb
                            )
                        ) WITH ORDINALITY AS s2(elem, ord)
                          ON s2.ord = s1.ord + 1
                        WHERE s1.elem = :from_slug
                          AND s2.elem = :to_slug
                    )
                    """
                ).bindparams(
                    p_id=parent_id_str_local,
                    from_slug=from_slug,
                    to_slug=target_slug,
                )
                query = query.filter(edge_filter_sql)
            else:
                # Node filter: rows whose ``metric_scores -> parent ->
                # 'sequence'`` array contains ``from_slug``. We use the
                # function form ``jsonb_exists`` rather than the ``?``
                # operator to avoid psycopg2 mistaking the question
                # mark for a parameter placeholder.
                node_filter_sql = text(
                    f"""
                    jsonb_exists(
                        COALESCE(
                            {scores_jsonb} -> :p_id -> 'sequence',
                            '[]'::jsonb
                        ),
                        :slug
                    )
                    """
                ).bindparams(p_id=parent_id_str_local, slug=from_slug)
                query = query.filter(node_filter_sql)

    # --- Discovered label filters ---------------------------------------
    # Surfaces "which calls produced THIS LLM-discovered label" and the
    # broader "which calls produced ANY LLM-discovered label". Both
    # operate on ``metric_scores[<parent>].discovered_labels`` (a list
    # of dicts) plus the same ``sequence`` array — covering both legacy
    # rows where the slug only made it into ``sequence`` and newer
    # rows where it landed in both.
    if discovered_parent_id is not None and (
        discovered_label_key or has_discovered
    ):
        d_parent_str = str(discovered_parent_id)
        alias_map_disc = _alias_map_for_parent(eval_row, discovered_parent_id)
        # See note above: cast once so the JSONB operators don't reject
        # the column when it's typed as ``json`` in the database.
        scores_jsonb = "(call_import_evaluation_rows.metric_scores)::jsonb"
        if discovered_label_key and discovered_label_key.strip():
            target = _resolve_alias(
                alias_map_disc, _slug_label(discovered_label_key)
            )
            if target:
                # Match rows whose discovered_labels list has an entry
                # ``{"key": <target>}`` OR whose sequence array still
                # contains the slug. The latter covers older rows that
                # were rewritten by a merge in the discovered_labels
                # blob but whose sequence may have lagged.
                contains_json = json.dumps(
                    {d_parent_str: {"discovered_labels": [{"key": target}]}}
                )
                disc_filter_sql = text(
                    f"""
                    (
                        {scores_jsonb} @> CAST(:contains AS JSONB)
                        OR
                        jsonb_exists(
                            COALESCE(
                                {scores_jsonb} -> :p_id -> 'sequence',
                                '[]'::jsonb
                            ),
                            :slug
                        )
                    )
                    """
                ).bindparams(
                    contains=contains_json,
                    p_id=d_parent_str,
                    slug=target,
                )
                query = query.filter(disc_filter_sql)
        elif has_discovered:
            # No specific slug — just rows that surfaced any candidate
            # under this parent. We coalesce missing paths to ``[]`` so
            # ``jsonb_array_length`` always sees an array (it raises on
            # non-array inputs, but our shape guarantees a list when
            # the key is present).
            has_disc_sql = text(
                f"""
                jsonb_array_length(
                    COALESCE(
                        {scores_jsonb} -> :p_id -> 'discovered_labels',
                        '[]'::jsonb
                    )
                ) > 0
                """
            ).bindparams(p_id=d_parent_str)
            query = query.filter(has_disc_sql)

    # --- Sorting ----------------------------------------------------------
    # Column-click sorting from the UI. Falls back to ``row_index`` so
    # paging stays stable when the user clears the sort. We always add a
    # secondary ``row_index`` tiebreaker so duplicate sort keys (e.g.
    # many rows with ``status = 'completed'``) keep a deterministic
    # order across page boundaries — without this, pagination can
    # double-show or skip rows when Postgres picks a different physical
    # order on each query.
    direction_desc = (sort_dir or "asc").strip().lower() == "desc"

    def _apply_direction(column_expr):
        return column_expr.desc() if direction_desc else column_expr.asc()

    # Whether the caller's ``sort_by`` resolved to a known column. We
    # use this flag to decide whether ``sort_dir`` is honoured on the
    # fallback path: unrecognized columns (typos, stale UI state) fall
    # back to the implicit ``row_index ASC`` default and intentionally
    # ignore ``sort_dir`` so users don't get a surprise reverse order
    # from a typo'd column name.
    sort_recognized = False
    sort_by_clean = (sort_by or "").strip()
    primary_sort = None
    metric_uuid: Optional[UUID] = None
    if sort_by_clean == "row_index":
        sort_recognized = True
        # Falls through to the default ``order_by`` below with
        # ``primary_sort`` still None — but ``sort_recognized=True``
        # tells the fallback branch to apply the requested direction.
    elif sort_by_clean == "conversation_id":
        sort_recognized = True
        primary_sort = _apply_direction(CallImportRow.conversation_id)
    elif sort_by_clean == "status":
        sort_recognized = True
        primary_sort = _apply_direction(CallImportEvaluationRow.status)
    elif sort_by_clean.startswith("metric:"):
        raw_metric_id = sort_by_clean.split(":", 1)[1].strip()
        try:
            metric_uuid = UUID(raw_metric_id)
        except (TypeError, ValueError):
            metric_uuid = None
        if metric_uuid is not None:
            sort_recognized = True
            # ``metric_scores`` is JSON-typed but the helper functions
            # for path extraction differ between Postgres (production)
            # and SQLite (default test backend). Branch on the active
            # dialect so we can use the right primitive:
            #   * Postgres → ``json_extract_path_text(col, key, "value")``
            #     which returns the value as TEXT for both ``json`` and
            #     ``jsonb`` columns.
            #   * SQLite   → ``json_extract(col, '$."<uuid>".value')``
            #     using JSONPath syntax. ``metric_uuid`` is already
            #     validated above (``UUID(raw_metric_id)``), so the
            #     interpolated path is safe from injection.
            # NULL values (rows where the metric wasn't scored) sort
            # to the END regardless of direction so un-scored rows
            # don't crowd the top of an ascending sort.
            dialect_name = (
                db.bind.dialect.name if db.bind is not None else "postgresql"
            )
            if dialect_name == "sqlite":
                json_path = f'$."{metric_uuid}".value'
                path_value = func.json_extract(
                    CallImportEvaluationRow.metric_scores,
                    json_path,
                )
            else:
                path_value = func.json_extract_path_text(
                    CallImportEvaluationRow.metric_scores,
                    str(metric_uuid),
                    "value",
                )
            primary_sort = (
                path_value.desc().nullslast()
                if direction_desc
                else path_value.asc().nullslast()
            )

    if primary_sort is not None:
        query = query.order_by(primary_sort, CallImportRow.row_index.asc())
    elif sort_recognized:
        # Explicit ``sort_by=row_index`` request — honour direction.
        query = query.order_by(_apply_direction(CallImportRow.row_index))
    else:
        # No sort requested OR unrecognized column — safe default of
        # ``row_index ASC``. We deliberately ignore ``sort_dir`` here
        # so a typo'd / stale ``sort_by`` doesn't quietly invert the
        # default order.
        query = query.order_by(CallImportRow.row_index.asc())
    from app.db_sharding.eval_rows import fetch_evaluation_row_pairs_page
    from app.db_sharding.sessions import is_sharding_enabled

    def _pair_row_index(
        pair: Tuple[CallImportEvaluationRow, CallImportRow],
    ) -> int:
        return int(pair[1].row_index or 0)

    def _directed_string(value: Optional[str], desc: bool) -> Tuple[int, ...]:
        text = value or ""
        if not desc:
            return (0, *text.encode("utf-8"))
        return (1, *(-byte for byte in text.encode("utf-8")))

    if sort_by_clean == "conversation_id":
        def _pair_sort_key(
            pair: Tuple[CallImportEvaluationRow, CallImportRow],
        ) -> Tuple[Any, ...]:
            return (
                _directed_string(pair[1].conversation_id, direction_desc),
                _pair_row_index(pair),
            )
    elif sort_by_clean == "status":
        def _pair_sort_key(
            pair: Tuple[CallImportEvaluationRow, CallImportRow],
        ) -> Tuple[Any, ...]:
            return (
                _directed_string(pair[0].status, direction_desc),
                _pair_row_index(pair),
            )
    elif sort_by_clean.startswith("metric:") and metric_uuid is not None:
        metric_id_str = str(metric_uuid)

        def _pair_sort_key(
            pair: Tuple[CallImportEvaluationRow, CallImportRow],
        ) -> Tuple[Any, ...]:
            scores = pair[0].metric_scores or {}
            entry = scores.get(metric_id_str, {})
            raw_value = entry.get("value") if isinstance(entry, dict) else None
            null_rank = 1 if raw_value is None else 0
            return (
                null_rank,
                _directed_string(
                    str(raw_value) if raw_value is not None else None,
                    direction_desc,
                ),
                _pair_row_index(pair),
            )
    elif sort_recognized and sort_by_clean == "row_index":
        def _pair_sort_key(
            pair: Tuple[CallImportEvaluationRow, CallImportRow],
        ) -> Tuple[int, ...]:
            idx = _pair_row_index(pair)
            return (-idx,) if direction_desc else (idx,)
    else:
        def _pair_sort_key(
            pair: Tuple[CallImportEvaluationRow, CallImportRow],
        ) -> Tuple[int, ...]:
            return (_pair_row_index(pair),)

    if is_sharding_enabled():
        def _build_query(session: Session):
            return query.with_session(session)

        total, rows = fetch_evaluation_row_pairs_page(
            db,
            _build_query,
            page=page,
            page_size=page_size,
            sort_key=_pair_sort_key,
            bounded_shard_fetch=(
                not sort_recognized or sort_by_clean == "row_index"
            ),
            row_index_desc=bool(
                sort_recognized and sort_by_clean == "row_index" and direction_desc
            ),
            sort_reads_scores=sort_by_clean.startswith("metric:"),
        )
    else:
        from app.db_sharding.scatter_gather import defer_call_import_row_text

        total = query.count()
        rows = (
            query.options(*defer_call_import_row_text())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    items: List[CallImportEvaluationRowResponse] = [
        _to_evaluation_row_response(
            eval_row_obj,
            source_row,
            eval_row,
            include_text=False,
        )
        for eval_row_obj, source_row in rows
    ]

    return CallImportEvaluationRowListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{eval_id}/rows/{row_id}",
    response_model=CallImportEvaluationRowResponse,
    operation_id="getCallImportEvaluationRow",
)
async def get_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowResponse:
    """One evaluation row, including the transcript the list leaves off."""
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
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    from app.db_sharding.sessions import is_sharding_enabled

    if not is_sharding_enabled():
        pair = (
            db.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(
                CallImportEvaluationRow.id == row_id,
                CallImportEvaluationRow.evaluation_id == eval_id,
                CallImportRow.call_import_id == call_import_id,
            )
            .first()
        )
        if pair is None:
            raise HTTPException(
                status_code=404, detail="Call import evaluation row not found"
            )
        eval_row, source_row = pair
        return _to_evaluation_row_response(
            eval_row,
            source_row,
            evaluation,
            include_text=True,
        )

    from app.db_sharding.row_ops import (
        close_row_sessions,
        locate_call_import_evaluation_row,
    )

    try:
        row_db, catalog_db, eval_row, source_row, _shard_id = (
            locate_call_import_evaluation_row(row_id)
        )
    except LookupError:
        raise HTTPException(
            status_code=404, detail="Call import evaluation row not found"
        ) from None
    try:
        if (
            eval_row.evaluation_id != eval_id
            or source_row.call_import_id != call_import_id
        ):
            raise HTTPException(
                status_code=404, detail="Call import evaluation row not found"
            )
        return _to_evaluation_row_response(
            eval_row,
            source_row,
            evaluation,
            include_text=True,
        )
    finally:
        close_row_sessions(row_db, catalog_db)


@router.post(
    "/{eval_id}/rows/{eval_row_id}/cancel",
    response_model=CallImportEvaluationRowResponse,
    status_code=status.HTTP_200_OK,
    operation_id="cancelCallImportEvaluationRow",
)
async def cancel_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    eval_row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportEvaluationRowResponse:
    """Abort an in-flight (or queued) evaluation for a single row.

    Idempotent: calling on a row that's already terminal (``completed``
    / ``failed``) returns the row unchanged with a 200 so the UI can
    wire this to a "Stop" button without having to pre-check the
    state. Updates the parent run's rollup so its counters reflect
    the cancel immediately.
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

    from app.db_sharding.eval_rows import evaluation_row_session
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        try:
            with evaluation_row_session(eval_row_id) as (
                row_db,
                _catalog_db,
                eval_row,
                source_row,
                _shard_id,
            ):
                if eval_row.evaluation_id != eval_id:
                    raise HTTPException(
                        status_code=404,
                        detail="Evaluation row not found in this run",
                    )
                _apply_evaluation_cancel(
                    [eval_row],
                    source_rows={source_row.id: source_row},
                    cascade_diarisation=True,
                )
                row_db.commit()
                _rollup_evaluation_status(evaluation, db)
                stamp_evaluation_actor(evaluation, principal)
                db.commit()
                row_db.refresh(eval_row)
                return _to_evaluation_row_response(eval_row, source_row, evaluation)
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation row not found in this run"
            ) from exc

    eval_row = (
        db.query(CallImportEvaluationRow)
        .filter(
            CallImportEvaluationRow.id == eval_row_id,
            CallImportEvaluationRow.evaluation_id == eval_id,
        )
        .first()
    )
    if not eval_row:
        raise HTTPException(
            status_code=404, detail="Evaluation row not found in this run"
        )

    source_row = (
        db.query(CallImportRow)
        .filter(CallImportRow.id == eval_row.call_import_row_id)
        .first()
    )
    source_rows = (
        {source_row.id: source_row} if source_row is not None else None
    )
    _apply_evaluation_cancel(
        [eval_row],
        source_rows=source_rows,
        cascade_diarisation=True,
    )
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    stamp_evaluation_actor(evaluation, principal)
    db.commit()
    db.refresh(eval_row)

    return _to_evaluation_row_response(eval_row, source_row, evaluation)

@router.delete(
    "/{eval_id}/rows/{eval_row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportEvaluationRow",
)
async def delete_call_import_evaluation_row(
    call_import_id: UUID,
    eval_id: UUID,
    eval_row_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a single per-row scoring entry within an evaluation run.

    Useful when the user wants to drop a noisy row before re-exporting
    the CSV — e.g. a row whose audio was corrupt and skewed the
    aggregate. Counters on the parent are recomputed so the rolled-up
    status stays accurate.
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
        raise HTTPException(status_code=404, detail="Call import evaluation not found")

    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled():
        from app.db_sharding.eval_rows import delete_evaluation_row_on_shards

        if not delete_evaluation_row_on_shards(eval_row_id, eval_id):
            raise HTTPException(
                status_code=404, detail="Evaluation row not found in this run"
            )
        _rollup_evaluation_status(evaluation, db)
        stamp_evaluation_actor(evaluation, principal)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    eval_row = (
        db.query(CallImportEvaluationRow)
        .filter(
            CallImportEvaluationRow.id == eval_row_id,
            CallImportEvaluationRow.evaluation_id == eval_id,
        )
        .first()
    )
    if not eval_row:
        raise HTTPException(
            status_code=404, detail="Evaluation row not found in this run"
        )

    # If the row was still in flight, best-effort revoke the worker task
    # so it doesn't try to write into a deleted DB row mid-execution.
    if eval_row.celery_task_id and eval_row.status in {"pending", "running"}:
        try:
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(eval_row.celery_task_id, terminate=False)
        except Exception:
            pass

    db.delete(eval_row)
    db.flush()
    _rollup_evaluation_status(evaluation, db)
    stamp_evaluation_actor(evaluation, principal)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

