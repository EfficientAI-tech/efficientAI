"""Helpers to normalize and enrich hosted-provider observability call payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.database import Agent, CallRecording, Integration


def looks_like_retell_call_data(call_data: Dict[str, Any]) -> bool:
    if not isinstance(call_data, dict):
        return False
    if call_data.get("provider_platform") == "retell":
        return True
    if call_data.get("call_id") and (
        isinstance(call_data.get("transcript_object"), list)
        or isinstance(call_data.get("call_analysis"), dict)
        or isinstance(call_data.get("latency"), dict)
        or isinstance(call_data.get("call_cost"), dict)
        or call_data.get("disconnection_reason") is not None
    ):
        return True
    return False


def looks_like_vapi_call_data(call_data: Dict[str, Any]) -> bool:
    if not isinstance(call_data, dict):
        return False
    if call_data.get("provider_platform") == "vapi":
        return True
    return bool(
        call_data.get("assistantId")
        or call_data.get("assistant_id")
        or isinstance(call_data.get("artifact"), dict)
        or call_data.get("endedReason") is not None
    )


def resolve_observability_provider_platform(
    call_recording: CallRecording,
    call_data: Optional[Dict[str, Any]] = None,
    *,
    db: Optional[Session] = None,
) -> str:
    payload = call_data if isinstance(call_data, dict) else (
        call_recording.call_data if isinstance(call_recording.call_data, dict) else {}
    )
    stored = (call_recording.provider_platform or payload.get("provider_platform") or "").strip().lower()
    if stored and stored not in {"external", "unknown"}:
        return stored

    if looks_like_retell_call_data(payload):
        return "retell"
    if looks_like_vapi_call_data(payload):
        return "vapi"
    if (payload.get("provider_platform") or "").strip().lower() == "elevenlabs":
        return "elevenlabs"

    if db is not None and call_recording.agent_id:
        agent = (
            db.query(Agent)
            .filter(
                Agent.id == call_recording.agent_id,
                Agent.organization_id == call_recording.organization_id,
                Agent.workspace_id == call_recording.workspace_id,
            )
            .first()
        )
        if agent and agent.voice_ai_integration_id:
            integration = (
                db.query(Integration)
                .filter(
                    Integration.id == agent.voice_ai_integration_id,
                    Integration.organization_id == call_recording.organization_id,
                    Integration.is_active == True,
                )
                .first()
            )
            if integration and integration.platform is not None:
                platform_value = (
                    integration.platform.value
                    if hasattr(integration.platform, "value")
                    else str(integration.platform)
                )
                return platform_value.strip().lower()

    return stored or "external"


def is_sparse_provider_call_data(call_data: Dict[str, Any], provider_platform: str) -> bool:
    platform = provider_platform.strip().lower()
    has_transcript = bool(
        (isinstance(call_data.get("transcript_object"), list) and len(call_data.get("transcript_object")) > 0)
        or (isinstance(call_data.get("messages"), list) and len(call_data.get("messages")) > 0)
        or (isinstance(call_data.get("transcript"), str) and call_data.get("transcript", "").strip())
        or (isinstance(call_data.get("transcript"), list) and len(call_data.get("transcript")) > 0)
    )

    if platform == "retell":
        has_analysis = isinstance(call_data.get("call_analysis"), dict) and len(call_data.get("call_analysis")) > 0
        has_cost = isinstance(call_data.get("call_cost"), dict) and len(call_data.get("call_cost")) > 0
        has_latency = isinstance(call_data.get("latency"), dict) and len(call_data.get("latency")) > 0
        if not has_transcript:
            return True
        return not (has_analysis and has_cost and has_latency)

    if platform == "vapi":
        has_messages = bool(
            (isinstance(call_data.get("messages"), list) and len(call_data.get("messages")) > 0)
            or (
                isinstance(call_data.get("artifact"), dict)
                and isinstance(call_data.get("artifact", {}).get("messages"), list)
                and len(call_data.get("artifact", {}).get("messages")) > 0
            )
        )
        has_analysis = isinstance(call_data.get("analysis"), dict) and len(call_data.get("analysis")) > 0
        has_cost = call_data.get("cost") is not None or isinstance(call_data.get("costBreakdown"), dict)
        if not has_messages:
            return True
        return not (has_analysis and has_cost)

    return False
