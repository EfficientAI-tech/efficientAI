"""Shared HTTP helpers for downloading call recording binaries from URLs."""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable, List, Optional, Tuple, Union
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.services.telephony.exotel_client import (
    DEFAULT_MAX_RECORDING_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ExotelAuthError,
    ExotelInvalidContentError,
    ExotelNotFoundError,
    ExotelRecordingTooLargeError,
    ExotelTransientError,
)

_DEFAULT_ALLOWED_HOST_SUFFIXES = (
    "exotel.com",
    "plivo.com",
    "amazonaws.com",
    "cloudfront.net",
)

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _allowed_host_suffixes() -> List[str]:
    configured = getattr(settings, "RECORDING_URL_ALLOWED_HOST_SUFFIXES", None)
    if configured:
        return list(configured)
    return list(_DEFAULT_ALLOWED_HOST_SUFFIXES)


def _hostname_allowed(hostname: str, allowed_suffixes: List[str]) -> bool:
    host = hostname.lower().rstrip(".")
    for suffix in allowed_suffixes:
        normalized = suffix.lower().lstrip(".")
        if host == normalized or host.endswith(f".{normalized}"):
            return True
    return False


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    for network in _BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


def _resolve_host_ips(hostname: str) -> List[ipaddress._BaseAddress]:
    try:
        addr_infos = socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ExotelInvalidContentError(
            f"Recording URL hostname could not be resolved: {hostname}"
        ) from exc

    ips: List[ipaddress._BaseAddress] = []
    seen = set()
    for info in addr_infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        try:
            ips.append(ipaddress.ip_address(ip_str))
        except ValueError as exc:
            raise ExotelInvalidContentError(
                f"Recording URL resolved to invalid IP address: {ip_str}"
            ) from exc
    if not ips:
        raise ExotelInvalidContentError(
            f"Recording URL hostname could not be resolved: {hostname}"
        )
    return ips


def assert_recording_url_safe(
    recording_url: str,
    *,
    user_supplied: bool,
    allowed_suffixes: Optional[List[str]] = None,
) -> None:
    """Validate a recording URL before any outbound HTTP request."""
    parsed = urlparse(recording_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ExotelInvalidContentError(
            f"Recording URL must use http or https, got {parsed.scheme or 'none'}"
        )
    if not parsed.hostname:
        raise ExotelInvalidContentError("Recording URL is missing a hostname")
    if parsed.username or parsed.password:
        raise ExotelInvalidContentError(
            "Recording URL must not embed credentials in the URL"
        )

    hostname = parsed.hostname
    suffixes = allowed_suffixes or _allowed_host_suffixes()

    try:
        literal_ip = ipaddress.ip_address(hostname)
        if _ip_is_blocked(literal_ip):
            raise ExotelInvalidContentError(
                "Recording URL targets a blocked network address"
            )
        if user_supplied:
            raise ExotelInvalidContentError(
                "User-supplied recording URLs must use allowlisted hostnames"
            )
    except ValueError:
        if not _hostname_allowed(hostname, suffixes):
            raise ExotelInvalidContentError(
                f"Recording URL hostname is not allowlisted: {hostname}"
            )
        for resolved_ip in _resolve_host_ips(hostname):
            if _ip_is_blocked(resolved_ip):
                raise ExotelInvalidContentError(
                    "Recording URL resolves to a blocked network address"
                )


def download_recording_url(
    recording_url: str,
    *,
    auth: Optional[Union[Tuple[str, str], httpx.Auth]] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_RECORDING_BYTES,
    user_supplied: bool = False,
) -> Tuple[bytes, str]:
    """Download a recording from a URL.

    Returns (audio_bytes, content_type). Raises typed Exotel* errors so the
    call-import worker can decide between retrying and failing the row.
    """
    if not recording_url:
        raise ExotelInvalidContentError("recording_url is empty")
    if user_supplied and auth is not None:
        raise ExotelInvalidContentError(
            "User-supplied recording URLs must not be fetched with credentials"
        )

    assert_recording_url_safe(recording_url, user_supplied=user_supplied)

    request_hooks: Optional[dict[str, List[Callable[..., None]]]] = None
    if not user_supplied:

        def _validate_redirect(request: httpx.Request) -> None:
            assert_recording_url_safe(str(request.url), user_supplied=False)

        request_hooks = {"request": [_validate_redirect]}

    follow_redirects = not user_supplied

    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=follow_redirects,
            event_hooks=request_hooks,
        ) as client:
            resp = client.get(recording_url, auth=auth)
    except ExotelInvalidContentError:
        raise
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
    """Download a user-supplied recording URL without authentication."""
    return download_recording_url(
        recording_url,
        auth=None,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        user_supplied=True,
    )
