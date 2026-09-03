"""Atomic post-call processing for playground Voice AI poll tasks."""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import CallRecording

PLAYGROUND_CALL_DATA_PRESERVE_KEYS = ("ui_surface", "external_usage_recorded")

_ENDED_STATUSES = frozenset(
    {"ended", "completed", "failed", "end-of-call-report", "done"}
)


def call_metrics_indicate_ended(metrics: dict[str, Any]) -> bool:
    status = str(metrics.get("call_status") or metrics.get("status") or "").lower()
    end_timestamp = metrics.get("end_timestamp") or metrics.get("endedAt")
    return bool(end_timestamp) or status in _ENDED_STATUSES


def provider_metrics_enriched(provider_platform: str, metrics: dict[str, Any]) -> bool:
    """True when the provider payload has analysis and/or pipeline latency details."""
    plat = str(provider_platform or "").lower()
    if plat == "vapi":
        analysis = metrics.get("analysis") if isinstance(metrics.get("analysis"), dict) else {}
        perf = (metrics.get("artifact") or {}).get("performanceMetrics") or {}
        return bool(analysis.get("summary")) or bool(perf.get("turnLatencies"))
    if plat == "retell":
        return bool(metrics.get("call_analysis")) or bool(metrics.get("latency"))
    if plat == "elevenlabs":
        status = str(metrics.get("status") or "").lower()
        return status in {"done", "completed"} or bool(metrics.get("conversation_turn_metrics"))
    if plat == "smallest":
        raw = metrics.get("raw_data") if isinstance(metrics.get("raw_data"), dict) else {}
        return bool(raw.get("latencyStats")) or bool(metrics.get("transcript"))
    return call_metrics_indicate_ended(metrics)


def merge_playground_call_data(
    prev: Optional[dict[str, Any]],
    new: dict[str, Any],
) -> dict[str, Any]:
    """Keep internal audit fields when provider metrics replace call_data."""
    merged = dict(new)
    if isinstance(prev, dict):
        for key in PLAYGROUND_CALL_DATA_PRESERVE_KEYS:
            if prev.get(key) is not None:
                merged[key] = prev[key]
    return merged


def _lock_call_recording(db: Session, call_recording_id: UUID) -> Optional[CallRecording]:
    return (
        db.query(CallRecording)
        .filter(CallRecording.id == call_recording_id)
        .with_for_update()
        .first()
    )


def record_playground_post_call_usage_once(
    db: Session,
    call_recording_id: UUID,
    *,
    provider_platform: str,
    call_metrics: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """
    Record external provider usage at most once per call recording.

    Returns (should_create_evaluator, updated_call_metrics).
    """
    from app.services.usage.external_agent_usage import (
        apply_playground_provider_usage_from_call_data,
    )

    locked = _lock_call_recording(db, call_recording_id)
    if not locked:
        db.rollback()
        return False, call_metrics

    if locked.evaluator_result_id:
        db.rollback()
        logger.info(
            "[Poll Call Metrics] Skipping post-call processing — "
            "evaluator result already exists"
        )
        return False, call_metrics

    stored_data = locked.call_data if isinstance(locked.call_data, dict) else {}
    metrics = dict(call_metrics) if isinstance(call_metrics, dict) else call_metrics
    platform_key = str(provider_platform or "").lower()

    if stored_data.get("external_usage_recorded") and isinstance(metrics, dict):
        metrics = merge_playground_call_data(stored_data, metrics)
        locked.call_data = metrics
        db.commit()
    elif isinstance(metrics, dict):
        try:
            apply_playground_provider_usage_from_call_data(
                organization_id=locked.organization_id,
                workspace_id=locked.workspace_id,
                agent_id=locked.agent_id,
                provider_platform=platform_key,
                call_short_id=locked.call_short_id,
                call_data=metrics,
            )
        except Exception:
            db.rollback()
            logger.exception(
                "[Poll Call Metrics] Usage counters failed for "
                f"call recording {call_recording_id}"
            )
            return False, call_metrics

        metrics["external_usage_recorded"] = True
        metrics = merge_playground_call_data(stored_data, metrics)
        locked.call_data = metrics
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "[Poll Call Metrics] Failed to persist external_usage_recorded "
                f"for call recording {call_recording_id}"
            )
            return False, call_metrics

    return True, metrics


def claim_playground_evaluator_result_slot(
    db: Session,
    call_recording_id: UUID,
    *,
    provider_call_id: str | None = None,
) -> Optional[CallRecording]:
    """
    Lock the call recording row and return it when evaluator creation may proceed.

    Caller must create/link EvaluatorResult and commit before the lock is released.
    """
    locked = _lock_call_recording(db, call_recording_id)
    if not locked:
        db.rollback()
        return None

    if locked.evaluator_result_id:
        db.rollback()
        call_ref = provider_call_id or locked.provider_call_id or str(call_recording_id)
        logger.info(
            f"[Poll Call Metrics] Skipping evaluator creation — "
            f"another poll already created result for call {call_ref}"
        )
        return None

    return locked


def persist_provider_call_metrics(
    db: Session,
    call_recording_id: UUID,
    call_metrics: dict[str, Any],
) -> bool:
    """Update stored provider call_data without creating an evaluator result."""
    from app.models.enums import CallRecordingStatus

    locked = _lock_call_recording(db, call_recording_id)
    if not locked:
        db.rollback()
        return False

    prev_data = locked.call_data if isinstance(locked.call_data, dict) else {}
    merged = merge_playground_call_data(prev_data, call_metrics)
    locked.call_data = merged
    locked.status = CallRecordingStatus.UPDATED
    db.commit()
    return True


def persist_provider_call_metrics(
    db: Session,
    call_recording_id: UUID,
    call_metrics: dict[str, Any],
) -> bool:
    """Update stored provider call_data without creating an evaluator result."""
    from app.models.enums import CallRecordingStatus

    locked = _lock_call_recording(db, call_recording_id)
    if not locked:
        db.rollback()
        return False

    prev_data = locked.call_data if isinstance(locked.call_data, dict) else {}
    merged = merge_playground_call_data(prev_data, call_metrics)
    locked.call_data = merged
    locked.status = CallRecordingStatus.UPDATED
    db.commit()
    return True
