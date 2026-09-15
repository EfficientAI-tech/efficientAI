"""Trusted hosts and optional CSP extras (base CSP policy lives in config.Settings)."""

from __future__ import annotations

import re
from typing import List
from urllib.parse import urlparse

from app.config import settings


def _hostname_from_url(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    host = (urlparse(raw).hostname or "").strip().lower()
    return host or None


def _wildcard_parent_domain(host: str) -> str | None:
    if host in ("localhost", "127.0.0.1"):
        return None
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        return None
    parts = host.split(".")
    if len(parts) >= 2:
        return f"*.{parts[-2]}.{parts[-1]}"
    return None


def _dedupe_hosts(hosts: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for h in hosts:
        key = (h or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def resolve_trusted_hosts() -> List[str]:
    hosts: List[str] = []
    if settings.TRUSTED_HOSTS_AUTO_FROM_FRONTEND:
        for url in (settings.FRONTEND_BASE_URL, settings.PUBLIC_BASE_URL):
            hostname = _hostname_from_url(url)
            if not hostname:
                continue
            if hostname == "localhost":
                hosts.extend(["localhost", "127.0.0.1"])
            else:
                hosts.append(hostname)
                wildcard = _wildcard_parent_domain(hostname)
                if wildcard:
                    hosts.append(wildcard)
    for entry in settings.TRUSTED_HOSTS_EXPLICIT or []:
        if entry and str(entry).strip():
            hosts.append(str(entry).strip())
    return _dedupe_hosts(hosts)


def build_csp_policy_with_extras() -> str:
    """Platform SDK allowlist from Settings plus optional YAML suffix sources."""
    connect_extra = " ".join(settings.CSP_CONNECT_SRC_EXTRA or [])
    frame_extra = " ".join(settings.CSP_FRAME_SRC_EXTRA or [])
    script_extra = " ".join(settings.CSP_SCRIPT_SRC_EXTRA or [])
    connect_src = (
        f"'self' wss: ws: {settings._CSP_VOICE_CONNECT_SRC} {connect_extra}".strip()
    )
    frame_src = f"'self' blob: {settings._CSP_FRAME_SRC} {frame_extra}".strip()
    script_src = f"'self' {settings._CSP_DAILY_SCRIPT_SRC} {script_extra}".strip()
    return (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        f"connect-src {connect_src}; "
        "media-src 'self' blob: https:; "
        f"frame-src {frame_src}; "
        "worker-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self'"
    )


def finalize_security_settings() -> None:
    if not (settings.PUBLIC_BASE_URL or "").strip() and (settings.FRONTEND_BASE_URL or "").strip():
        settings.PUBLIC_BASE_URL = settings.FRONTEND_BASE_URL.strip().rstrip("/")
    settings.TRUSTED_HOSTS = resolve_trusted_hosts()
    if settings.CSP_POLICY_CUSTOM:
        return
    has_csp_extras = bool(
        settings.CSP_CONNECT_SRC_EXTRA
        or settings.CSP_FRAME_SRC_EXTRA
        or settings.CSP_SCRIPT_SRC_EXTRA
    )
    if has_csp_extras:
        settings.CSP_POLICY = build_csp_policy_with_extras()
