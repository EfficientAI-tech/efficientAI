"""Intensity presets and config resolution for red team runs.

A run's budget is the per-family ``attack_quotas``: each family gets that many attack
conversations in total, split between level-0 roots and escalation children. Recon
probes are counted separately (``recon_count``).
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.red_team.catalog import (
    AUDIO_NATIVE,
    CONTENT_HARM,
    FAMILY_ORDER,
    PROMPT_INJECTION,
    SOCIAL_ENGINEERING,
    TEXT_NATIVE,
    family_applies,
)

INTENSITIES = ("quick", "standard", "thorough", "custom")

MAX_FAMILY_QUOTA = 20
MAX_LEVELS = 8
MAX_BRANCHES = 5
MAX_RECON = 5
MAX_TURNS = 20
MAX_CALL_MINUTES = 10
MAX_CONCURRENT = 8

_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "recon_count": 1,
        "max_levels": 2,
        "max_branches": 2,
        "max_turns": 8,
        "max_call_minutes": 5,
        "n_concurrent": 4,
        "attack_quotas": {
            SOCIAL_ENGINEERING: 2,
            PROMPT_INJECTION: 2,
            TEXT_NATIVE: 1,
            AUDIO_NATIVE: 1,
            CONTENT_HARM: 1,
        },
    },
    "standard": {
        "recon_count": 2,
        "max_levels": 3,
        "max_branches": 3,
        "max_turns": 10,
        "max_call_minutes": 8,
        "n_concurrent": 4,
        "attack_quotas": {
            SOCIAL_ENGINEERING: 4,
            PROMPT_INJECTION: 5,
            TEXT_NATIVE: 3,
            AUDIO_NATIVE: 3,
            CONTENT_HARM: 5,
        },
    },
    "thorough": {
        "recon_count": 3,
        "max_levels": 5,
        "max_branches": 3,
        "max_turns": 14,
        "max_call_minutes": 10,
        "n_concurrent": 6,
        "attack_quotas": {
            SOCIAL_ENGINEERING: 8,
            PROMPT_INJECTION: 10,
            TEXT_NATIVE: 6,
            AUDIO_NATIVE: 6,
            CONTENT_HARM: 8,
        },
    },
}


class PresetError(ValueError):
    """Invalid intensity or custom quotas (maps to HTTP 400)."""


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def resolve_config(
    intensity: str,
    *,
    modality: str,
    attack_quotas: Optional[dict[str, int]] = None,
    overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Concrete run config for ``intensity``.

    ``custom`` starts from ``standard`` limits and takes ``attack_quotas`` (0-20 per
    family, at least one above 0). Families that do not apply to ``modality`` are
    zeroed. Values above the maximums are clamped, not rejected.
    """
    intensity = (intensity or "").strip().lower()
    if intensity not in INTENSITIES:
        raise PresetError(f"Unknown intensity '{intensity}'. Use one of: {', '.join(INTENSITIES)}")

    base = dict(_PRESETS["standard" if intensity == "custom" else intensity])
    quotas = dict(base["attack_quotas"])
    if intensity == "custom":
        if not attack_quotas:
            raise PresetError("Custom intensity needs attack_quotas")
        unknown = set(attack_quotas) - set(FAMILY_ORDER)
        if unknown:
            raise PresetError(f"Unknown attack families: {', '.join(sorted(unknown))}")
        quotas = {family: _clamp(attack_quotas.get(family, 0), 0, MAX_FAMILY_QUOTA, 0) for family in FAMILY_ORDER}

    quotas = {
        family: (quotas.get(family, 0) if family_applies(family, modality) else 0)
        for family in FAMILY_ORDER
    }
    if sum(quotas.values()) <= 0:
        raise PresetError("At least one attack family that applies to this agent must be above 0")

    overrides = overrides or {}
    config = {
        "recon_count": _clamp(overrides.get("recon_count", base["recon_count"]), 0, MAX_RECON, base["recon_count"]),
        "max_levels": _clamp(overrides.get("max_levels", base["max_levels"]), 1, MAX_LEVELS, base["max_levels"]),
        "max_branches": _clamp(overrides.get("max_branches", base["max_branches"]), 1, MAX_BRANCHES, base["max_branches"]),
        "max_turns": _clamp(overrides.get("max_turns", base["max_turns"]), 2, MAX_TURNS, base["max_turns"]),
        "max_call_minutes": _clamp(
            overrides.get("max_call_minutes", base["max_call_minutes"]), 1, MAX_CALL_MINUTES, base["max_call_minutes"]
        ),
        "n_concurrent": _clamp(overrides.get("n_concurrent", base["n_concurrent"]), 1, MAX_CONCURRENT, base["n_concurrent"]),
        "attack_quotas": quotas,
    }
    config["max_attacks"] = sum(quotas.values())
    return config


def root_allocation(quota: int, max_levels: int) -> int:
    """Level-0 attacks for one family: about half the quota, the rest is kept for escalation."""
    if quota <= 0:
        return 0
    if max_levels <= 1:
        return quota
    return max(1, (quota + 1) // 2)


def preview(config: dict[str, Any], *, modality: str) -> dict[str, Any]:
    """What a run will do, for the confirm step."""
    total = config["max_attacks"] + config["recon_count"]
    per_call = config["max_call_minutes"] if modality == "voice" else None
    return {
        "recon_conversations": config["recon_count"],
        "max_attack_conversations": config["max_attacks"],
        "max_total_conversations": total,
        "max_levels": config["max_levels"],
        "attack_quotas": config["attack_quotas"],
        "max_minutes_per_call": per_call,
        "max_voice_minutes": (total * per_call) if per_call else None,
        "max_turns_per_conversation": config["max_turns"],
    }
