"""Configured public URLs (never derived from untrusted Host headers)."""

from __future__ import annotations

from urllib.parse import urlparse

from app.config import settings


def configured_public_base_url() -> str:
    """Canonical https/http base for links and callbacks (PUBLIC_BASE_URL or FRONTEND_BASE_URL)."""
    for candidate in (settings.PUBLIC_BASE_URL, settings.FRONTEND_BASE_URL):
        raw = (candidate or "").strip().rstrip("/")
        if raw.startswith(("http://", "https://")):
            return raw
    return ""


def configured_public_origin() -> str:
    base = configured_public_base_url()
    if not base:
        return ""
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"
