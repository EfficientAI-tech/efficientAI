"""Shared credential resolution helpers (telephony + AI providers).

Centralizes the "pick one row for (org, provider)" logic so that ordering
and tie-breaking stay consistent across the codebase.
"""

from app.services.credentials.resolver import (
    clear_other_defaults,
    resolve_ai_provider,
    resolve_integration,
    resolve_telephony_integration,
)

__all__ = [
    "clear_other_defaults",
    "resolve_ai_provider",
    "resolve_integration",
    "resolve_telephony_integration",
]
