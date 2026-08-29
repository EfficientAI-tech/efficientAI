"""Emit incremental live observability events from Pipecat/voice pipelines."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from loguru import logger

from app.config import settings
from app.models.database import CallRecordingSource
from app.models.enums import CallRecordingStatus
from app.services.observability.call_ingest import upsert_live_event_call_recording
from app.services.observability.live_trace import build_live_synthetic_trace
from app.services.observability.trace_archive import persist_provider_trace


class LiveObservabilityEmitter:
    """Push transcript turns and terminal metadata into live observability ingest."""

    def __init__(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        provider_call_id: str,
        provider_platform: str = "pipecat",
        agent_ref: Optional[str] = None,
        explicit_agent_id: Optional[UUID] = None,
        trace_id: Optional[str] = None,
        db_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.provider_call_id = provider_call_id
        self.provider_platform = (provider_platform or "pipecat").strip().lower()
        self.agent_ref = agent_ref
        self.explicit_agent_id = explicit_agent_id
        self.trace_id = trace_id
        self._db_factory = db_factory
        self._seq = 0
        self.call_short_id: Optional[str] = None

    @classmethod
    def enabled(cls) -> bool:
        return bool(settings.OBSERVABILITY_LIVE_INGEST_ENABLED)

    def start_call(self, *, direction: str = "inbound") -> Optional[str]:
        if not self.enabled():
            return None
        started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ack = self._emit(
            "call.started",
            {"startedAt": started_at, "direction": direction, "status": "in_progress"},
        )
        self.call_short_id = ack.get("call_short_id")
        if ack.get("trace_id") and not self.trace_id:
            self.trace_id = str(ack["trace_id"])
        return self.call_short_id

    def emit_turn(
        self,
        role: str,
        content: str,
        *,
        latency: Optional[Dict[str, Any]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> None:
        if not self.enabled() or not content.strip():
            return
        normalized_role = (role or "").strip().lower()
        if normalized_role in {"assistant", "agent", "bot"}:
            event_type = "turn.assistant"
            payload_role = "assistant"
        else:
            event_type = "turn.user"
            payload_role = "user"
        payload: Dict[str, Any] = {"content": content.strip(), "role": payload_role}
        if isinstance(latency, dict) and latency:
            payload["latency"] = latency
        if start_time is not None:
            payload["start_time"] = start_time
        if end_time is not None:
            payload["end_time"] = end_time
        self._emit(event_type, payload)

    def end_call(
        self,
        *,
        recording_url: Optional[str] = None,
        recording_s3_key: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        trace_id: Optional[str] = None,
        ended_reason: Optional[str] = None,
    ) -> None:
        if not self.enabled():
            return
        if trace_id:
            self.trace_id = trace_id
        ended_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload: Dict[str, Any] = {"endedAt": ended_at, "status": "ended"}
        if ended_reason:
            payload["endedReason"] = ended_reason
        if recording_url:
            payload["recording_url"] = recording_url
        if recording_s3_key:
            payload["recording_s3_key"] = recording_s3_key
        if duration_seconds is not None:
            payload["duration_seconds"] = float(duration_seconds)
        if self.trace_id:
            payload["trace_id"] = self.trace_id
        self._emit("call.ended", payload)

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._seq += 1
        live_event = {
            "event_id": f"live-{self.provider_call_id}-{self._seq}-{uuid.uuid4().hex[:8]}",
            "call_id": self.provider_call_id,
            "event_type": event_type,
            "seq": self._seq,
            "event_ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "platform": self.provider_platform,
            "payload": payload,
        }
        if self.trace_id:
            live_event["trace_id"] = self.trace_id
        if self.agent_ref:
            live_event["agent_ref"] = self.agent_ref

        db = self._open_db()
        close_db = self._db_factory is None
        try:
            call_recording, _action = upsert_live_event_call_recording(
                db=db,
                organization_id=self.organization_id,
                workspace_id=self.workspace_id,
                provider_platform=self.provider_platform,
                provider_call_id=self.provider_call_id,
                live_event=live_event,
                max_out_of_order_seq=settings.OBSERVABILITY_LIVE_EVENT_MAX_OUT_OF_ORDER_SEQ,
                agent_ref_raw=self.agent_ref,
                explicit_agent_id=self.explicit_agent_id,
                source=CallRecordingSource.WEBHOOK,
                persist=False,
            )
            self.call_short_id = call_recording.call_short_id
            if call_recording.trace_id:
                self.trace_id = call_recording.trace_id

            if event_type in {"call.ended", "call.failed"}:
                call_data = call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
                synthetic_trace = build_live_synthetic_trace(
                    call_data,
                    provider_call_id=str(call_recording.provider_call_id or self.provider_call_id),
                    provider_platform=self.provider_platform,
                    trace_id=str(call_recording.trace_id or self.trace_id or "") or None,
                )
                if synthetic_trace:
                    call_recording.call_data = persist_provider_trace(
                        call_data=call_data,
                        provider_platform=self.provider_platform,
                        organization_id=self.organization_id,
                        call_short_id=call_recording.call_short_id,
                        trace_payload=synthetic_trace,
                        source=str(synthetic_trace.get("trace_source") or "live_synthetic"),
                    )
                    if synthetic_trace.get("trace_id"):
                        call_recording.trace_id = str(synthetic_trace["trace_id"])
                    call_recording.status = CallRecordingStatus.UPDATED

            db.commit()
            db.refresh(call_recording)
            return {
                "call_short_id": call_recording.call_short_id,
                "trace_id": call_recording.trace_id,
            }
        except Exception as exc:
            db.rollback()
            logger.warning(
                "Live observability emit failed platform={} call_id={} event={}: {}",
                self.provider_platform,
                self.provider_call_id,
                event_type,
                exc,
            )
            return {}
        finally:
            if close_db:
                db.close()

    def _open_db(self):
        if self._db_factory is not None:
            return self._db_factory()
        from app.database import SessionLocal

        return SessionLocal()
