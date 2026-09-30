"""Helpers for resolving Vapi call recording URLs."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session


def is_presigned_storage_url(url: Optional[str]) -> bool:
    """Return True when the URL includes S3/R2 presigned query parameters."""
    if not url:
        return False
    return "X-Amz-Signature=" in url or "X-Amz-Algorithm=" in url


def extract_vapi_stereo_url(call_data: Any) -> Optional[str]:
    """Prefer presigned stereo URL for dual-channel waveform."""
    if not isinstance(call_data, dict):
        return None

    artifact = call_data.get("artifact") if isinstance(call_data.get("artifact"), dict) else {}
    recording_urls = call_data.get("recording_urls") if isinstance(call_data.get("recording_urls"), dict) else {}

    return (
        artifact.get("presignedStereoUrl")
        or call_data.get("presignedStereoUrl")
        or call_data.get("stereoRecordingUrl")
        or artifact.get("stereoRecordingUrl")
        or recording_urls.get("stereo_url")
    )


def extract_vapi_recording_url(call_data: Any, *, stereo: bool = False) -> Optional[str]:
    """
    Resolve the best Vapi recording URL from provider call_data.

    HIPAA deployments expose time-limited presigned URLs on the artifact;
    those must be preferred over raw R2 object URLs that reject browser playback.
    """
    if not isinstance(call_data, dict):
        return None

    if stereo:
        stereo_url = extract_vapi_stereo_url(call_data)
        if stereo_url:
            return stereo_url

    artifact = call_data.get("artifact") if isinstance(call_data.get("artifact"), dict) else {}
    recording = artifact.get("recording") if isinstance(artifact.get("recording"), dict) else {}
    mono = recording.get("mono") if isinstance(recording.get("mono"), dict) else {}
    recording_urls = call_data.get("recording_urls") if isinstance(call_data.get("recording_urls"), dict) else {}
    provider_payload = (
        call_data.get("provider_payload") if isinstance(call_data.get("provider_payload"), dict) else {}
    )

    return (
        artifact.get("presignedMonoUrl")
        or artifact.get("presignedStereoUrl")
        or call_data.get("presignedMonoUrl")
        or call_data.get("presignedStereoUrl")
        or call_data.get("recordingUrl")
        or call_data.get("stereoRecordingUrl")
        or artifact.get("recordingUrl")
        or artifact.get("stereoRecordingUrl")
        or mono.get("combinedUrl")
        or recording_urls.get("combined_url")
        or recording_urls.get("stereo_url")
        or provider_payload.get("recordingUrl")
        or provider_payload.get("stereoRecordingUrl")
    )


def vapi_playback_url_needs_refresh(url: Optional[str]) -> bool:
    if not url:
        return True
    if "r2.cloudflarestorage.com" in url.lower() and not is_presigned_storage_url(url):
        return True
    return False


def vapi_proxy_request_headers(
    url: str,
    integration_api_key: Optional[str],
) -> Optional[Dict[str, str]]:
    if not integration_api_key:
        return None
    if is_presigned_storage_url(url):
        return None
    if "r2.cloudflarestorage.com" in url.lower():
        return None
    return {"Authorization": f"Bearer {integration_api_key}"}


def refresh_vapi_call_data_from_provider(
    db: Session,
    *,
    organization_id: UUID,
    agent_id: Optional[UUID],
    provider_call_id: str,
    prev_call_data: Optional[dict],
) -> Optional[dict]:
    """Fetch latest Vapi call payload (incl. HIPAA presigned recording URLs)."""
    from app.core.encryption import decrypt_api_key
    from app.models.database import Agent, Integration
    from app.services.playground.post_call_processing import merge_playground_call_data
    from app.services.voice_providers import get_voice_provider

    if not provider_call_id or not agent_id:
        return None

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent or not agent.voice_ai_integration_id:
        return None

    integration = db.query(Integration).filter(
        Integration.id == agent.voice_ai_integration_id,
        Integration.organization_id == organization_id,
    ).first()
    if not integration:
        return None

    try:
        decrypted_key = decrypt_api_key(integration.api_key)
        provider_kwargs: Dict[str, Any] = {"api_key": decrypted_key}
        if integration.public_key:
            provider_kwargs["public_key"] = integration.public_key
        provider_class = get_voice_provider("vapi")
        provider = provider_class(**provider_kwargs)
        refreshed = provider.retrieve_call_metrics(provider_call_id)
    except Exception as exc:
        logger.warning(f"[Vapi audio] refresh failed for call {provider_call_id}: {exc}")
        return None

    if not isinstance(refreshed, dict) or not refreshed:
        return None

    prev = prev_call_data if isinstance(prev_call_data, dict) else {}
    return merge_playground_call_data(prev, refreshed)
