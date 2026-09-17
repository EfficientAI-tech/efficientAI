"""Guardrails for HTTP rate-limit scope (scale routes must stay exempt)."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.core.api_rate_limit import (
    RESOURCE_CREATE_RATE_LIMIT_ROUTES,
    SCALE_EXEMPT_ROUTE_MODULE_PREFIXES,
)

_ROUTES_DIR = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "routes"

_ALLOWED_RESOURCE_CREATE_MODULES = frozenset(
    {"agents.py", "personas.py", "scenarios.py", "chat.py"}
)


def _module_is_scale_exempt(stem: str) -> bool:
    for prefix in SCALE_EXEMPT_ROUTE_MODULE_PREFIXES:
        if stem.startswith(prefix) or stem == prefix.rstrip("_"):
            return True
    return False


def test_default_api_rate_limit_enforce_off_for_self_host():
    assert settings.API_RATE_LIMIT_ENFORCE is False


def test_scale_route_modules_do_not_import_resource_create_limiter():
    for path in _ROUTES_DIR.glob("*.py"):
        if path.name.startswith("__"):
            continue
        stem = path.stem
        if not _module_is_scale_exempt(stem):
            continue
        text = path.read_text(encoding="utf-8")
        assert "enforce_resource_create_rate_limit" not in text, (
            f"{path.name} must not use HTTP resource-create rate limits"
        )


def test_only_allowlisted_modules_may_import_resource_create_limiter():
    for path in _ROUTES_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "enforce_resource_create_rate_limit" not in text:
            continue
        assert path.name in _ALLOWED_RESOURCE_CREATE_MODULES, (
            f"Unexpected resource-create limiter in {path.name}"
        )


def test_resource_create_route_registry_matches_allowlist():
    assert len(RESOURCE_CREATE_RATE_LIMIT_ROUTES) == len(_ALLOWED_RESOURCE_CREATE_MODULES)
