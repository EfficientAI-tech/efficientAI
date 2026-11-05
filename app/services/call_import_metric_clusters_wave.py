"""Paged metric-cluster generation with durable batch checkpoints (call-import evals)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.db_sharding.scatter_gather import (
    EVALUATION_ANALYSIS_BATCH_SIZE,
    EvaluationRowPageCursor,
    count_completed_evaluation_row_pairs,
    evaluation_row_page_cursor_from_pair,
    load_completed_evaluation_row_pairs_for_eval_row_ids,
    load_completed_evaluation_row_pairs_page,
)
from app.models.database import CallImportEvaluation, CallImportEvaluationRow, CallImportRow, Metric
from app.models.schemas import (
    DiscoveredProblemCluster,
    EvaluationMetricClustersState,
    MetricClusterGroup,
    MetricFailurePolicy,
)
from app.services.call_import_metric_clusters import (
    METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
    ClusterOutputTruncated,
    _aggregate_signatures,
    _build_flagged_row_payload_from_source,
    _metric_is_quality,
    _run_discovery,
    _run_extraction,
    _selected_evaluation_row_ids_from_raw,
    _synthesize_metric_clusters,
    metric_clusters_raw_is_cancelled,
    policies_from_evaluation_raw,
    policy_has_failure_criteria,
)
from app.services.call_import_user_insights_wave import pick_transcript_for_source
from app.services.evaluation_analysis_checkpoints import (
    JOB_KIND_METRIC_CLUSTERS,
    batch_count_for_rows,
    cursor_from_header,
    cursor_to_dict,
    init_job_header,
    list_analysis_batches,
    merge_cluster_extractions_from_batches,
    merge_signature_counts_from_cluster_batches,
    normalize_transcript_source,
    progress_header,
    rows_completed_for_batches,
    upsert_analysis_batch,
)
from app.services.metric_cluster_rows import call_import_pair_to_cluster_row
from app.services.metric_clusters_rca_summary import compute_rca_summary, enrich_metric_cluster_groups

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[Dict[str, Any]], None]

EXTRACTION_SUB_BATCH_ROWS = 25
SYNTHESIS_BATCH_INDEX_OFFSET = 100_000
DISCOVERY_BATCH_INDEX_OFFSET = 200_000


def _cluster_row_for_pair(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    transcript_source: str,
):
    base = call_import_pair_to_cluster_row(evaluation, eval_row, source_row)
    transcript = pick_transcript_for_source(evaluation, source_row, transcript_source)
    return replace(base, transcript=transcript)


def _sub_batch_payloads(rows: Sequence[Dict[str, Any]], *, size: int = EXTRACTION_SUB_BATCH_ROWS):
    chunk = max(1, size)
    return [list(rows[i : i + chunk]) for i in range(0, len(rows), chunk)]


def _merge_sig_maps(
    target: Dict[str, Dict[str, int]],
    metric_id: str,
    delta: Dict[str, int],
) -> None:
    bucket = target.setdefault(metric_id, {})
    for label, count in delta.items():
        bucket[label] = bucket.get(label, 0) + int(count)


def _count_row_scope(
    db: Session,
    evaluation: CallImportEvaluation,
    metric_clusters_raw: Any,
) -> Tuple[int, Optional[List[UUID]]]:
    selected = _selected_evaluation_row_ids_from_raw(metric_clusters_raw)
    if selected:
        return len(selected), [UUID(rid) for rid in selected]
    total = count_completed_evaluation_row_pairs(db, evaluation.id)
    return total, None


def _metrics_eligible_for_synthesis(
    quality_metrics: Sequence[Metric],
    failure_policies: Dict[str, MetricFailurePolicy],
    sig_by_metric: Dict[str, Dict[str, int]],
) -> List[Metric]:
    eligible: List[Metric] = []
    for metric in quality_metrics:
        policy = failure_policies.get(str(metric.id))
        if policy is None or not policy_has_failure_criteria(policy, metric):
            continue
        if not sig_by_metric.get(str(metric.id)):
            continue
        eligible.append(metric)
    return eligible


def start_metric_clusters_job_header(
    evaluation: CallImportEvaluation,
    db: Session,
    *,
    job_run_id: UUID,
    transcript_source: str,
    provider: Optional[str],
    model: Optional[str],
    metric_clusters_raw: Any,
) -> Dict[str, Any]:
    total_rows, _ = _count_row_scope(db, evaluation, metric_clusters_raw)
    total_batches = batch_count_for_rows(total_rows)
    prior = metric_clusters_raw if isinstance(metric_clusters_raw, dict) else {}
    header = init_job_header(
        job_run_id=job_run_id,
        transcript_source=normalize_transcript_source(transcript_source),
        total_rows=total_rows,
        total_batches=total_batches,
        provider=provider,
        model=model,
        extra={
            "generated_at_completed_rows": evaluation.completed_rows,
            "llm_calls_used": 0,
            "selected_evaluation_row_ids": prior.get("selected_evaluation_row_ids") or [],
            "failure_policies": prior.get("failure_policies") or {},
            "failure_policies_source": prior.get("failure_policies_source"),
            "failure_policies_updated_at": prior.get("failure_policies_updated_at"),
            "synthesis_completed_metric_ids": [],
            "groups": [],
            "discovered_problems": [],
        },
    )
    header["progress"]["phase"] = "rows"
    return header


def resume_metric_clusters_job_header(
    db: Session,
    evaluation: CallImportEvaluation,
    prior: Dict[str, Any],
    *,
    transcript_source: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-open a checkpointed clustering job without losing finished pages."""
    header = dict(prior)
    header["status"] = "running"
    header["error_message"] = None
    header["celery_task_id"] = None
    header["transcript_source"] = normalize_transcript_source(transcript_source)
    if provider:
        header["provider"] = provider
    if model:
        header["model"] = model

    total_rows, _ = _count_row_scope(db, evaluation, header)
    total_batches = batch_count_for_rows(total_rows)
    progress = header.get("progress") if isinstance(header.get("progress"), dict) else {}
    stored_batches = int(progress.get("completed_batches") or 0)
    completed_batches = min(stored_batches, total_batches) if total_batches else stored_batches
    phase = progress.get("phase") if isinstance(progress.get("phase"), str) else None
    if phase not in {"rows", "synthesis", "discovery"}:
        phase = "synthesis" if completed_batches >= total_batches else "rows"
    header["progress"] = progress_header(
        completed_rows=rows_completed_for_batches(completed_batches, total_rows)
        if total_rows
        else int(progress.get("completed_rows") or 0),
        total_rows=total_rows,
        completed_batches=completed_batches,
        total_batches=total_batches,
        completed_llm_calls=int(header.get("llm_calls_used") or 0),
        total_llm_calls=int(progress.get("total_llm_calls") or 0),
        phase=phase,
    )
    return header


def _load_row_page(
    db: Session,
    evaluation_id: UUID,
    *,
    after_cursor: Optional[EvaluationRowPageCursor],
    selected_ids: Optional[List[UUID]],
    batch_index: int,
) -> List[tuple[CallImportEvaluationRow, CallImportRow]]:
    if selected_ids:
        pairs = load_completed_evaluation_row_pairs_for_eval_row_ids(
            db, evaluation_id, selected_ids
        )
        start = batch_index * EVALUATION_ANALYSIS_BATCH_SIZE
        end = start + EVALUATION_ANALYSIS_BATCH_SIZE
        return pairs[start:end]
    return load_completed_evaluation_row_pairs_page(
        db,
        evaluation_id,
        limit=EVALUATION_ANALYSIS_BATCH_SIZE,
        after_cursor=after_cursor,
    )


def process_metric_clusters_wave_step(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    provider,
    model: str,
    *,
    metrics: Sequence[Metric],
    policies: Dict[str, MetricFailurePolicy],
    job_run_id: UUID,
    on_progress: Optional[ProgressCallback] = None,
    is_cancelled: Optional[CancelCheck] = None,
) -> Tuple[str, Optional[EvaluationMetricClustersState]]:
    raw = evaluation.metric_clusters if isinstance(evaluation.metric_clusters, dict) else {}
    if metric_clusters_raw_is_cancelled(raw):
        return "idle", EvaluationMetricClustersState(
            status="cancelled",
            error_message=METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
            generated_at=datetime.now(timezone.utc),
        )

    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    phase = str(progress.get("phase") or "rows")
    total_rows = int(progress.get("total_rows") or 0)
    total_batches = int(progress.get("total_batches") or 0)
    completed_batches = int(progress.get("completed_batches") or 0)
    llm_calls_used = int(raw.get("llm_calls_used") or 0)
    total_llm_calls = int(progress.get("total_llm_calls") or 0)
    transcript_source = normalize_transcript_source(raw.get("transcript_source"))
    selected_ids_raw = raw.get("selected_evaluation_row_ids") or []
    selected_ids = (
        [UUID(str(rid)) for rid in selected_ids_raw] if selected_ids_raw else None
    )

    stored_policies, policy_source = policies_from_evaluation_raw(raw)
    failure_policies = policies or stored_policies
    quality_metrics = [m for m in metrics if _metric_is_quality(m)]

    if phase == "rows" and completed_batches < total_batches:
        cursor = cursor_from_header(raw)
        pairs = _load_row_page(
            db,
            evaluation.id,
            after_cursor=cursor,
            selected_ids=selected_ids,
            batch_index=completed_batches,
        )
        if not pairs:
            raw["progress"] = {
                **progress,
                "phase": "synthesis",
                "completed_batches": completed_batches,
            }
            evaluation.metric_clusters = raw
            return "continue", None

        rows_before_this_batch = rows_completed_for_batches(completed_batches, total_rows)
        metrics_sig: Dict[str, Dict[str, int]] = {}
        metric_extractions: Dict[str, List[Dict[str, Any]]] = {}
        flagged_samples: List[Dict[str, Any]] = []

        for metric in quality_metrics:
            policy = failure_policies.get(str(metric.id))
            if policy is None or not policy_has_failure_criteria(policy, metric):
                continue
            flagged_payloads: List[Dict[str, Any]] = []
            for eval_row, source_row in pairs:
                if eval_row.status != "completed":
                    continue
                cluster_row = _cluster_row_for_pair(
                    evaluation, eval_row, source_row, transcript_source
                )
                payload = _build_flagged_row_payload_from_source(
                    cluster_row, metric, policy
                )
                if payload:
                    flagged_payloads.append(payload)
                    flagged_samples.append(payload)

            extractions: List[Dict[str, Any]] = []
            sub_batches = _sub_batch_payloads(flagged_payloads)
            for sub_batch in sub_batches:
                if is_cancelled and is_cancelled():
                    return "idle", EvaluationMetricClustersState(
                        status="cancelled",
                        error_message=METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
                        generated_at=datetime.now(timezone.utc),
                    )
                try:
                    extracted = _run_extraction(
                        db,
                        organization_id,
                        provider,
                        model,
                        metric.name,
                        sub_batch,
                    )
                    extractions.extend(extracted)
                except ClusterOutputTruncated:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Metric cluster extraction failed for {} / {}: {}",
                        evaluation.id,
                        metric.id,
                        exc,
                    )
                llm_calls_used += 1

            mid = str(metric.id)
            sig_counts = _aggregate_signatures(extractions)
            _merge_sig_maps(metrics_sig, mid, sig_counts)
            if extractions:
                reservoir = metric_extractions.setdefault(mid, [])
                reservoir.extend(extractions)
                metric_extractions[mid] = reservoir[:40]

        page_cursor = evaluation_row_page_cursor_from_pair(pairs[-1])
        upsert_analysis_batch(
            db,
            evaluation_id=evaluation.id,
            job_kind=JOB_KIND_METRIC_CLUSTERS,
            job_run_id=job_run_id,
            batch_index=completed_batches,
            payload={
                "metrics": metrics_sig,
                "metric_extractions": metric_extractions,
                "flagged_samples": flagged_samples[:80],
                "rows_processed": len(pairs),
            },
            cursor=page_cursor if not selected_ids else None,
            transcript_source=transcript_source,
        )

        completed_batches += 1
        new_progress = progress_header(
            completed_rows=rows_completed_for_batches(completed_batches, total_rows)
            if total_rows
            else rows_before_this_batch + len(pairs),
            total_rows=total_rows,
            completed_batches=completed_batches,
            total_batches=total_batches,
            completed_llm_calls=llm_calls_used,
            total_llm_calls=total_llm_calls,
            phase="rows" if completed_batches < total_batches else "synthesis",
        )
        raw["progress"] = new_progress
        raw["llm_calls_used"] = llm_calls_used
        if not selected_ids:
            raw["cursor"] = cursor_to_dict(page_cursor)

        db.expire(evaluation, ["metric_clusters"])
        db.refresh(evaluation)
        live = evaluation.metric_clusters if isinstance(evaluation.metric_clusters, dict) else {}
        if metric_clusters_raw_is_cancelled(live):
            return "idle", EvaluationMetricClustersState(
                status="cancelled",
                error_message=METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
                generated_at=datetime.now(timezone.utc),
            )
        evaluation.metric_clusters = {**live, **raw, "progress": new_progress}
        if on_progress:
            on_progress(new_progress)
        return "continue", None

    # Synthesis phase — one metric per wave step so each finish is checkpointed.
    row_batches = list_analysis_batches(
        db,
        evaluation_id=evaluation.id,
        job_kind=JOB_KIND_METRIC_CLUSTERS,
        job_run_id=job_run_id,
    )
    row_batches = [b for b in row_batches if b.batch_index < SYNTHESIS_BATCH_INDEX_OFFSET]
    sig_by_metric = merge_signature_counts_from_cluster_batches(row_batches)
    synthesis_done = {
        str(x) for x in (raw.get("synthesis_completed_metric_ids") or []) if x
    }

    groups: List[MetricClusterGroup] = []
    groups_raw = raw.get("groups")
    if isinstance(groups_raw, list):
        for item in groups_raw:
            if isinstance(item, dict):
                try:
                    groups.append(MetricClusterGroup.model_validate(item))
                except Exception:  # noqa: BLE001
                    continue

    metrics_by_id = {str(m.id): m for m in metrics}
    metrics_to_synth = _metrics_eligible_for_synthesis(
        quality_metrics, failure_policies, sig_by_metric
    )

    for metric_pos, metric in enumerate(metrics_to_synth):
        mid = str(metric.id)
        if mid in synthesis_done:
            continue
        if is_cancelled and is_cancelled():
            return "idle", EvaluationMetricClustersState(
                status="cancelled",
                error_message=METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
                generated_at=datetime.now(timezone.utc),
            )

        signature_counts = sig_by_metric.get(mid) or {}
        sample_rows = merge_cluster_extractions_from_batches(row_batches, mid)
        flagged_count = sum(signature_counts.values())
        try:
            clusters = _synthesize_metric_clusters(
                db,
                organization_id,
                provider,
                model,
                metric_name=metric.name,
                signature_counts=signature_counts,
                sample_rows=sample_rows,
                flagged_count=flagged_count,
            )
        except ClusterOutputTruncated:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Metric cluster synthesis failed for {} / {}: {}",
                evaluation.id,
                metric.id,
                exc,
            )
            clusters = []
        llm_calls_used += 1

        if clusters:
            group = MetricClusterGroup(
                metric_id=mid,
                metric_name=metric.name,
                flagged_count=flagged_count,
                clusters=clusters,
            )
            groups = [g for g in groups if g.metric_id != mid] + [group]

        synthesis_done.add(mid)
        batch_index = SYNTHESIS_BATCH_INDEX_OFFSET + metric_pos
        upsert_analysis_batch(
            db,
            evaluation_id=evaluation.id,
            job_kind=JOB_KIND_METRIC_CLUSTERS,
            job_run_id=job_run_id,
            batch_index=batch_index,
            payload={
                "metric_id": mid,
                "groups": [groups[-1].model_dump(mode="json")] if clusters else [],
            },
        )

        synth_index = len([m for m in metrics_to_synth if str(m.id) in synthesis_done])
        raw["synthesis_completed_metric_ids"] = sorted(synthesis_done)
        raw["groups"] = [g.model_dump(mode="json") for g in groups]
        raw["llm_calls_used"] = llm_calls_used
        raw["progress"] = {
            **progress,
            "phase": "synthesis",
            "completed_rows": progress.get("completed_rows"),
            "total_rows": progress.get("total_rows"),
            "completed_batches": completed_batches,
            "total_batches": total_batches,
            "completed_llm_calls": llm_calls_used,
            "total_llm_calls": total_llm_calls,
            "current_metric_name": metric.name,
            "current_metric_index": synth_index,
            "total_metrics": len(metrics_to_synth),
        }
        evaluation.metric_clusters = raw
        if on_progress:
            on_progress(raw["progress"])
        db.commit()
        return "continue", None

    # Discovery + final assembly
    all_samples: List[Dict[str, Any]] = []
    total_flagged = 0
    for batch in row_batches:
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        samples = payload.get("flagged_samples")
        if isinstance(samples, list):
            all_samples.extend(samples)
        for sig_map in (payload.get("metrics") or {}).values():
            if isinstance(sig_map, dict):
                total_flagged += sum(int(v) for v in sig_map.values())

    discovered_raw = raw.get("discovered_problems")
    discovered: List[DiscoveredProblemCluster] = []
    if isinstance(discovered_raw, list) and raw.get("discovery_completed"):
        for item in discovered_raw:
            if isinstance(item, dict):
                try:
                    discovered.append(DiscoveredProblemCluster.model_validate(item))
                except Exception:  # noqa: BLE001
                    continue
    else:
        try:
            discovered = _run_discovery(
                db,
                organization_id,
                provider,
                model,
                all_samples,
                total_flagged=max(total_flagged, 1),
            )
        except ClusterOutputTruncated:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Proactive discovery failed for evaluation {}: {}", evaluation.id, exc
            )
        llm_calls_used += 1
        upsert_analysis_batch(
            db,
            evaluation_id=evaluation.id,
            job_kind=JOB_KIND_METRIC_CLUSTERS,
            job_run_id=job_run_id,
            batch_index=DISCOVERY_BATCH_INDEX_OFFSET,
            payload={
                "discovered_problems": [d.model_dump(mode="json") for d in discovered]
            },
        )
        raw["discovered_problems"] = [d.model_dump(mode="json") for d in discovered]
        raw["discovery_completed"] = True
        raw["llm_calls_used"] = llm_calls_used
        evaluation.metric_clusters = raw
        if on_progress:
            on_progress(
                {
                    **progress,
                    "phase": "discovery",
                    "completed_llm_calls": llm_calls_used,
                    "total_llm_calls": total_llm_calls,
                }
            )
        db.commit()
        return "continue", None

    payloads_by_metric: Dict[str, List[Dict[str, Any]]] = {}
    extractions_by_metric: Dict[str, List[Dict[str, Any]]] = {}
    for batch in row_batches:
        payload = batch.payload if isinstance(batch.payload, dict) else {}
        for mid, samples in (payload.get("metric_extractions") or {}).items():
            extractions_by_metric.setdefault(str(mid), []).extend(samples or [])

    groups, discovered = enrich_metric_cluster_groups(
        groups,
        discovered,
        policies=failure_policies,
        metrics_by_id=metrics_by_id,
        payloads_by_metric=payloads_by_metric,
        extractions_by_metric=extractions_by_metric,
    )
    rca_summary = compute_rca_summary(
        groups,
        discovered,
        metrics_by_id=metrics_by_id,
        analysed_calls=max(int(progress.get("total_rows") or 1), 1),
    )

    final_progress = {
        **progress,
        "phase": "completed",
        "completed_rows": int(progress.get("total_rows") or 0),
        "completed_batches": total_batches,
        "completed_llm_calls": llm_calls_used,
        "total_llm_calls": total_llm_calls,
    }

    if not groups and not discovered:
        return "done", EvaluationMetricClustersState(
            status="failed",
            error_message="No flagged quality metrics or clusters produced.",
            generated_at=datetime.now(timezone.utc),
            llm_calls_used=llm_calls_used,
            progress=final_progress,
            selected_evaluation_row_ids=selected_ids_raw,
        )

    overview_parts = [
        f"{g.metric_name}: {len(g.clusters)} cluster(s) across {g.flagged_count} flagged calls"
        for g in groups
    ]
    if discovered:
        overview_parts.append(f"{len(discovered)} proactively discovered theme(s)")

    policies_updated_raw = None
    if raw.get("failure_policies_updated_at"):
        try:
            policies_updated_raw = datetime.fromisoformat(
                str(raw["failure_policies_updated_at"])
            )
        except ValueError:
            policies_updated_raw = None

    return "done", EvaluationMetricClustersState(
        status="completed",
        groups=groups,
        discovered_problems=discovered,
        rca_summary=rca_summary,
        overview="; ".join(overview_parts) if overview_parts else None,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=evaluation.completed_rows,
        progress=final_progress,
        provider=provider.value if hasattr(provider, "value") else str(provider),
        model=model,
        llm_calls_used=llm_calls_used,
        is_stale=False,
        selected_evaluation_row_ids=selected_ids_raw,
        failure_policies=failure_policies,
        failure_policies_source=policy_source,  # type: ignore[arg-type]
        failure_policies_updated_at=policies_updated_raw,
    )
