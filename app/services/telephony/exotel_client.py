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

# Recognized Exotel REST API bases. ``sip_domain`` on integrations is also
# used by Plivo for SIP routing; for Exotel we only treat values matching
# these patterns as Calls API hosts — legacy SIP routing hosts are ignored.
_KNOWN_EXOTEL_API_HOSTS = frozenset(
    {
        "api.exotel.com",
        "api.in.exotel.com",
    }
)


def _parse_retry_after_header(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        seconds = int(str(value).strip())
    except ValueError:
        return None
    return max(1, seconds)


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


class CredentialedRecordingThrottledError(ExotelTransientError):
    """Credentialed recording fetch was throttled or overload-rejected."""

    def __init__(self, message: str, *, retry_after_seconds: Optional[int] = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


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
        credential_fingerprint: Optional[str] = None,
    ):
        if not auth_id or not auth_token:
            raise ValueError("Exotel auth_id and auth_token are required")
        self._auth = (auth_id, auth_token)
        self._account_sid = account_sid or auth_id
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_seconds
        self._max_bytes = max_recording_bytes
        self._credential_fingerprint = credential_fingerprint

    def _penalize_if_fingerprinted(self, *, retry_after_seconds: Optional[int] = None) -> None:
        if not self._credential_fingerprint:
            return
        from app.workers.concurrency.telephony_credential_rate_limit import (
            penalize_telephony_credential,
        )

        penalize_telephony_credential(
            self._credential_fingerprint,
            retry_after_seconds=retry_after_seconds,
        )

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
            self._penalize_if_fingerprinted()
            raise CredentialedRecordingThrottledError(
                f"Exotel rejected credentials when fetching call detail (HTTP {resp.status_code})"
            )
        if resp.status_code == 404:
            raise ExotelNotFoundError(
                f"Exotel call {call_sid} not found"
            )
        if resp.status_code == 429:
            retry_after = _parse_retry_after_header(resp.headers.get("Retry-After"))
            self._penalize_if_fingerprinted(retry_after_seconds=retry_after)
            raise CredentialedRecordingThrottledError(
                f"Exotel rate limited call detail fetch (HTTP 429)",
                retry_after_seconds=retry_after,
            )
        if 500 <= resp.status_code < 600:
            raise ExotelTransientError(
                f"Exotel server error fetching call detail (HTTP {resp.status_code})"
            )
        if resp.status_code == 400:
            self._penalize_if_fingerprinted()
            raise CredentialedRecordingThrottledError(
                f"Unexpected HTTP 400 fetching call detail: {resp.text[:200]}"
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
        from app.services.telephony.recording_download import download_recording_url

        return download_recording_url(
            recording_url,
            auth=self._auth,
            timeout_seconds=self._timeout,
            max_bytes=self._max_bytes,
            credential_fingerprint=self._credential_fingerprint,
        )


def _hostname_from_api_host_value(value: str) -> str:
    """Extract a lowercase hostname from a bare host, host:port, or URL."""
    from urllib.parse import urlparse

    raw = value.strip().rstrip("/")
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
    else:
        host = raw.split("/", 1)[0].split("@", 1)[-1]
        if ":" in host and not host.startswith("["):
            host = host.rsplit(":", 1)[0]
    return host.lower()


def is_exotel_rest_api_host(api_host: Optional[str]) -> bool:
    """Return True when ``api_host`` is a known Exotel REST API base.

    SIP routing domains (``sip.*``, customer SIP hosts, etc.) must not be
    used as Exotel REST API bases — those integrations fall back to the
    configured default instead.
    """
    if not api_host or not api_host.strip():
        return False
    host = _hostname_from_api_host_value(api_host)
    if host in _KNOWN_EXOTEL_API_HOSTS:
        return True
    # Future Exotel REST shards that follow api.<region>.exotel.com.
    return host.startswith("api.") and host.endswith(".exotel.com")


def validate_exotel_api_host_for_save(api_host: Optional[str]) -> None:
    """Reject non-empty Exotel API host values that are not REST API bases."""
    if not api_host or not str(api_host).strip():
        return
    if not is_exotel_rest_api_host(str(api_host)):
        raise ValueError(
            "Exotel API Host must be a REST API base such as api.exotel.com or "
            "api.in.exotel.com. SIP routing domains belong on Plivo integrations, "
            "not here."
        )


def resolve_exotel_api_base(api_host: Optional[str] = None) -> str:
    """Pick the Exotel REST base URL for call-import / telephony clients.

    Priority: per-integration API Host (``sip_domain``) when it matches a
    recognized Exotel REST host → ``EXOTEL_API_BASE`` in config → Singapore
    default. Unrecognized ``sip_domain`` values (e.g. legacy SIP routing
    hosts) are ignored with a warning so REST calls do not hit the
    wrong service.
    """
    if api_host and api_host.strip():
        if is_exotel_rest_api_host(api_host):
            host = api_host.strip().rstrip("/")
            if not host.startswith(("http://", "https://")):
                host = f"https://{host}"
            return host
        logger.warning(
            "Ignoring Exotel integration API host {!r}: not a recognized REST "
            "API base (expected api.exotel.com or api.in.exotel.com). "
            "Falling back to configured default.",
            api_host.strip(),
        )

    configured = getattr(settings, "EXOTEL_API_BASE", None)
    if configured and str(configured).strip():
        return str(configured).strip().rstrip("/")

    return DEFAULT_API_BASE


def build_exotel_client_from_integration(
    auth_id: str,
    auth_token: str,
    account_sid: Optional[str] = None,
    api_host: Optional[str] = None,
    credential_fingerprint: Optional[str] = None,
) -> ExotelClient:
    """Helper that reads optional API-host and timeout overrides from settings."""

    api_base = resolve_exotel_api_base(api_host)
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
        credential_fingerprint=credential_fingerprint,
    )
