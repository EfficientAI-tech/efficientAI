"""Shared HTTP helpers for downloading call recording binaries from URLs."""

from __future__ import annotations

from typing import Optional, Tuple, Union

import httpx

from app.services.telephony.exotel_client import (
    DEFAULT_MAX_RECORDING_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ExotelAuthError,
    ExotelInvalidContentError,
    ExotelNotFoundError,
    ExotelRecordingTooLargeError,
    ExotelTransientError,
)


def download_recording_url(
    recording_url: str,
    *,
    auth: Optional[Union[Tuple[str, str], httpx.Auth]] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_RECORDING_BYTES,
) -> Tuple[bytes, str]:
    """Download a recording from a URL.

    Returns (audio_bytes, content_type). Raises typed Exotel* errors so the
    call-import worker can decide between retrying and failing the row.
    """
    if not recording_url:
        raise ExotelInvalidContentError("recording_url is empty")

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = client.get(recording_url, auth=auth)
    except httpx.TimeoutException as exc:
        raise ExotelTransientError(f"Timeout fetching recording: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ExotelTransientError(f"HTTP error fetching recording: {exc}") from exc

    if resp.status_code in (401, 403):
        raise ExotelAuthError(
            f"Recording URL rejected credentials (HTTP {resp.status_code})"
        )
    if resp.status_code == 404:
        raise ExotelNotFoundError(f"Recording not found at {recording_url}")
    if 500 <= resp.status_code < 600:
        raise ExotelTransientError(
            f"Server error fetching recording (HTTP {resp.status_code})"
        )
    if resp.status_code >= 400:
        raise ExotelInvalidContentError(
            f"Unexpected HTTP {resp.status_code} fetching recording: {resp.text[:200]}"
        )

    content_type = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("audio/"):
        raise ExotelInvalidContentError(
            f"Recording URL returned non-audio content type: {content_type or 'unknown'}"
        )

    body = resp.content
    if len(body) == 0:
        raise ExotelInvalidContentError("Recording response was empty")
    if len(body) > max_bytes:
        raise ExotelRecordingTooLargeError(
            f"Recording size {len(body)} bytes exceeds cap of {max_bytes} bytes"
        )

    return body, content_type


def download_public_recording(
    recording_url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_RECORDING_BYTES,
) -> Tuple[bytes, str]:
    """Download a recording from a public URL without authentication."""
    return download_recording_url(
        recording_url,
        auth=None,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
