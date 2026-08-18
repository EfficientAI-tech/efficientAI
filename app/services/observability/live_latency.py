"""Live latency sample capture and rolling percentile helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import CallRecording, ObservabilityLiveLatencySample


def _extract_latency_samples(payload: Dict[str, Any]) -> List[Dict[str, float]]:
    samples: List[Dict[str, float]] = []

    direct_latency = payload.get("latency")
    if isinstance(direct_latency, dict):
        for key, value in direct_latency.items():
            if isinstance(value, (int, float)):
                metric = f"{str(key).strip().lower()}_ms"
                samples.append({"metric_name": metric, "latency_ms": float(value)})

    metric_name = payload.get("latency_metric")
    latency_ms = payload.get("latency_ms")
    if isinstance(metric_name, str) and isinstance(latency_ms, (int, float)):
        samples.append(
            {"metric_name": f"{metric_name.strip().lower()}_ms", "latency_ms": float(latency_ms)}
        )

    totals = payload.get("metrics")
    if isinstance(totals, dict):
        for key, value in totals.items():
            if isinstance(value, (int, float)) and "latency" in str(key).lower():
                samples.append({"metric_name": str(key).strip().lower(), "latency_ms": float(value)})

    return [item for item in samples if item["latency_ms"] >= 0]


def record_live_latency_samples(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    call_recording: CallRecording,
    provider_platform: str,
    provider_call_id: str,
    event_payload: Dict[str, Any],
    event_ts: datetime,
) -> int:
    """Persist latency samples parsed from a live event payload."""
    extracted = _extract_latency_samples(event_payload)
    if not extracted:
        return 0
    for sample in extracted:
        db.add(
            ObservabilityLiveLatencySample(
                organization_id=organization_id,
                workspace_id=workspace_id,
                call_recording_id=call_recording.id,
                call_short_id=call_recording.call_short_id,
                provider_platform=provider_platform,
                provider_call_id=provider_call_id,
                agent_id=call_recording.agent_id,
                metric_name=sample["metric_name"],
                latency_ms=sample["latency_ms"],
                event_ts=event_ts.astimezone(UTC),
            )
        )
    db.flush()
    return len(extracted)


def _percentile(sorted_values: List[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * q
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    weight = rank - lo
    return sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight


def _build_percentiles(values: Iterable[float]) -> Dict[str, Optional[float]]:
    sorted_values = sorted(float(v) for v in values)
    return {
        "p50_ms": _percentile(sorted_values, 0.50),
        "p90_ms": _percentile(sorted_values, 0.90),
        "p95_ms": _percentile(sorted_values, 0.95),
    }


def query_live_latency_metrics(
    *,
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    window_seconds: int,
    agent_id: Optional[UUID] = None,
    provider_platform: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute rolling latency percentiles for a time window."""
    cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
    query = db.query(ObservabilityLiveLatencySample).filter(
        ObservabilityLiveLatencySample.organization_id == organization_id,
        ObservabilityLiveLatencySample.workspace_id == workspace_id,
        ObservabilityLiveLatencySample.event_ts >= cutoff,
    )
    if agent_id:
        query = query.filter(ObservabilityLiveLatencySample.agent_id == agent_id)
    if provider_platform:
        query = query.filter(
            ObservabilityLiveLatencySample.provider_platform == provider_platform.strip().lower()
        )

    rows = query.all()
    all_values = [row.latency_ms for row in rows]

    by_metric: Dict[str, List[float]] = {}
    for row in rows:
        by_metric.setdefault(row.metric_name, []).append(row.latency_ms)

    metric_payload = {
        metric_name: {
            **_build_percentiles(values),
            "sample_count": len(values),
        }
        for metric_name, values in by_metric.items()
    }
    return {
        "window_seconds": window_seconds,
        "sample_count": len(all_values),
        **_build_percentiles(all_values),
        "metrics": metric_payload,
    }
