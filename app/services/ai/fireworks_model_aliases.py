"""Fireworks serverless catalog keys superseded by newer model slugs.

Fireworks decommissioned several legacy serverless models (Sept 2026).
Catalog keys and stored configs may still reference the old slugs; resolve
them to the replacement slug before building LiteLLM model paths.
"""

from __future__ import annotations

from typing import Dict

# catalog key -> Fireworks ``accounts/fireworks/models/{slug}`` segment
FIREWORKS_DEPRECATED_MODEL_ALIASES: Dict[str, str] = {
    "deepseek-v4-flash-0731": "deepseek-v4p1-flash",
    "deepseek-v4-pro-0813": "deepseek-v4p1-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-v4p1-flash",
    "glm-5p2": "glm-5p3",
    "glm-5p2-fast": "glm-5p3-flash",
    "glm-5p2-fast-us": "glm-5p3-flash",
    "muse-glimmer-30b": "nemotron-lightning-3p5-30b-a3b",
    "kimi-k2p6": "kimi-k3",
    "kimi-k2p6-fast": "kimi-k3-fast",
    "kimi-k2p7-code": "kimi-k3",
    "kimi-k2p7-code-fast": "kimi-k3-fast",
}


def resolve_fireworks_catalog_model(catalog_model: str) -> str:
    """Return the serverless slug LiteLLM should call for a catalog model key."""
    key = (catalog_model or "").strip()
    if not key:
        return catalog_model
    if key.startswith("accounts/fireworks/models/"):
        slug = key[len("accounts/fireworks/models/") :]
        return f"accounts/fireworks/models/{FIREWORKS_DEPRECATED_MODEL_ALIASES.get(slug, slug)}"
    return FIREWORKS_DEPRECATED_MODEL_ALIASES.get(key, key)
