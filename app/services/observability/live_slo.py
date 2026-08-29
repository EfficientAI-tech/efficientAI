"""Live SLO evaluation + automation hook helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import (
    CallRecording,
    ObservabilityLiveLatencySample,
    ObservabilityLiveSloBreach,
)
from app.services.observability.live_latency import query_live_latency_metrics


def evaluate_llm_p90_slo(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    call_recording: CallRecording,
    provider_platform: str,
    window_seconds: int = 300,
) -> Optional[ObservabilityLiveSloBreach]:
    """Evaluate rolling LLM p90 and persist a breach marker when violated."""
    if not settings.OBSERVABILITY_LIVE_SLO_ALERTS_ENABLED:
        return None

    metrics = query_live_latency_metrics(
        db=db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        window_seconds=window_seconds,
        agent_id=call_recording.agent_id,
        provider_platform=provider_platform,
    )
    llm_metrics = metrics.get("metrics", {}).get("llm_ms") or metrics.get("metrics", {}).get("llm_latency_ms")
    if not isinstance(llm_metrics, dict):
        return None
    sample_count = int(llm_metrics.get("sample_count") or 0)
    p90_ms = llm_metrics.get("p90_ms")
    if sample_count < settings.OBSERVABILITY_LIVE_SLO_MIN_SAMPLE_COUNT or not isinstance(p90_ms, (int, float)):
        return None
    threshold = float(settings.OBSERVABILITY_LIVE_SLO_P90_LLM_MS)
    if float(p90_ms) <= threshold:
        return None

    cooldown_cutoff = datetime.now(UTC) - timedelta(minutes=10)
    recent = (
        db.query(ObservabilityLiveSloBreach)
        .filter(
            ObservabilityLiveSloBreach.organization_id == organization_id,
            ObservabilityLiveSloBreach.workspace_id == workspace_id,
            ObservabilityLiveSloBreach.agent_id == call_recording.agent_id,
            ObservabilityLiveSloBreach.metric_name == "llm_ms",
            ObservabilityLiveSloBreach.created_at >= cooldown_cutoff,
        )
        .first()
    )
    if recent:
        return None

    breach = ObservabilityLiveSloBreach(
        organization_id=organization_id,
        workspace_id=workspace_id,
        call_recording_id=call_recording.id,
        call_short_id=call_recording.call_short_id,
        provider_platform=provider_platform,
        agent_id=call_recording.agent_id,
        metric_name="llm_ms",
        window_seconds=window_seconds,
        p90_ms=float(p90_ms),
        threshold_ms=threshold,
        sample_count=sample_count,
        evaluator_queued=False,
    )
    db.add(breach)
    db.flush()
    return breach
