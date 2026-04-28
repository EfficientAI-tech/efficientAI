"""Thin Exotel REST client.

Used by the CSV call-import worker to authenticate with Exotel and pull a call
recording binary off a recording URL. We deliberately use plain HTTP (no SDK)
so the dependency surface stays small and the client is easy to mock in tests.
"""

from __future__ import annotations

from typing import Optional, Tuple

import httpx
from loguru import logger

from app.config import settings


DEFAULT_API_BASE = "https://api.exotel.com"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RECORDING_BYTES = 50 * 1024 * 1024  # 50 MB


class ExotelAuthError(Exception):
    """Exotel rejected the credentials (HTTP 401/403). Not retryable."""


class ExotelNotFoundError(Exception):
    """Exotel returned 404 for the recording URL. Not retryable."""


class ExotelRecordingTooLargeError(Exception):
    """The recording exceeded the configured max size cap. Not retryable."""


class ExotelInvalidContentError(Exception):
    """The remote responded with a non-audio Content-Type. Not retryable."""


class ExotelTransientError(Exception):
    """Transient network / 5xx error, the worker may retry."""


class ExotelClient:
    """HTTP wrapper around Exotel's REST endpoints used by call import."""

    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        account_sid: Optional[str] = None,
        api_base: str = DEFAULT_API_BASE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_recording_bytes: int = DEFAULT_MAX_RECORDING_BYTES,
    ):
        if not auth_id or not auth_token:
            raise ValueError("Exotel auth_id and auth_token are required")
        self._auth = (auth_id, auth_token)
        self._account_sid = account_sid or auth_id
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_seconds
        self._max_bytes = max_recording_bytes

    def test_connection(self) -> bool:
        """Make a trivial authenticated call to confirm credentials work."""
        url = f"{self._api_base}/v1/Accounts/{self._account_sid}/Calls?PageSize=1"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, auth=self._auth)
            if resp.status_code in (401, 403):
                raise ExotelAuthError(
                    f"Exotel auth failed (HTTP {resp.status_code}): {resp.text[:200]}"
                )
            resp.raise_for_status()
            return True
        except (ExotelAuthError, httpx.HTTPError) as e:
            logger.exception("Exotel test_connection failed")
            raise ValueError(f"Failed to connect to Exotel: {str(e)}")

    def get_call_recording_url(self, call_sid: str) -> str:
        """Resolve the recording URL for a call via Exotel's Calls API.

        Hits ``GET {api_base}/v1/Accounts/{account_sid}/Calls/{call_sid}.json``
        with HTTP Basic auth and returns ``Call.RecordingUrl``. Raises a typed
        ``ExotelXxxError`` so the worker can decide between retrying and
        failing the row.
        """
        if not call_sid:
            raise ExotelInvalidContentError("call_sid is empty")

        url = f"{self._api_base}/v1/Accounts/{self._account_sid}/Calls/{call_sid}.json"
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(url, auth=self._auth)
        except httpx.TimeoutException as e:
            raise ExotelTransientError(
                f"Timeout fetching Exotel call detail for {call_sid}: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise ExotelTransientError(
                f"HTTP error fetching Exotel call detail for {call_sid}: {e}"
            ) from e

        if resp.status_code in (401, 403):
            raise ExotelAuthError(
                f"Exotel rejected credentials when fetching call detail (HTTP {resp.status_code})"
            )
        if resp.status_code == 404:
            raise ExotelNotFoundError(
                f"Exotel call {call_sid} not found"
            )
        if 500 <= resp.status_code < 600:
            raise ExotelTransientError(
                f"Exotel server error fetching call detail (HTTP {resp.status_code})"
            )
        if resp.status_code >= 400:
            raise ExotelInvalidContentError(
                f"Unexpected HTTP {resp.status_code} fetching call detail: {resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except ValueError as e:
            raise ExotelInvalidContentError(
                f"Exotel call detail response was not valid JSON: {e}"
            ) from e

        # Exotel wraps the call object under "Call". Be lenient about the
        # exact shape so we work whether the upstream returns the wrapped or
        # unwrapped form.
        call_obj = payload.get("Call") if isinstance(payload, dict) else None
        if not isinstance(call_obj, dict):
            call_obj = payload if isinstance(payload, dict) else {}

        recording_url = (
            call_obj.get("RecordingUrl")
            or call_obj.get("recording_url")
            or ""
        )
        if not isinstance(recording_url, str) or not recording_url.strip():
            raise ExotelNotFoundError(
                f"Exotel call {call_sid} has no recording URL"
            )

        return recording_url.strip()

    def download_recording(self, recording_url: str) -> Tuple[bytes, str]:
        """Download a recording from Exotel.

        Returns (audio_bytes, content_type). Raises a typed ExotelXxxError so
        the worker can decide between retrying and failing the row.
        """
        if not recording_url:
            raise ExotelInvalidContentError("recording_url is empty")

        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(recording_url, auth=self._auth)
        except httpx.TimeoutException as e:
            raise ExotelTransientError(f"Timeout fetching Exotel recording: {e}") from e
        except httpx.HTTPError as e:
            raise ExotelTransientError(f"HTTP error fetching Exotel recording: {e}") from e

        if resp.status_code in (401, 403):
            raise ExotelAuthError(
                f"Exotel rejected credentials when fetching recording (HTTP {resp.status_code})"
            )
        if resp.status_code == 404:
            raise ExotelNotFoundError(f"Exotel recording not found at {recording_url}")
        if 500 <= resp.status_code < 600:
            raise ExotelTransientError(
                f"Exotel server error fetching recording (HTTP {resp.status_code})"
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
        if len(body) > self._max_bytes:
            raise ExotelRecordingTooLargeError(
                f"Recording size {len(body)} bytes exceeds cap of {self._max_bytes} bytes"
            )

        return body, content_type


def build_exotel_client_from_integration(
    auth_id: str,
    auth_token: str,
    account_sid: Optional[str] = None,
) -> ExotelClient:
    """Helper that reads any optional overrides from settings."""

    api_base = getattr(settings, "EXOTEL_API_BASE", None) or DEFAULT_API_BASE
    timeout = float(getattr(settings, "EXOTEL_HTTP_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    max_bytes = int(
        getattr(settings, "EXOTEL_MAX_RECORDING_BYTES", DEFAULT_MAX_RECORDING_BYTES)
    )
    return ExotelClient(
        auth_id=auth_id,
        auth_token=auth_token,
        account_sid=account_sid,
        api_base=api_base,
        timeout_seconds=timeout,
        max_recording_bytes=max_bytes,
    )
