"""Helpers for resolving Vapi call recording URLs."""

from __future__ import annotations

from typing import Any, Dict, Optional


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
