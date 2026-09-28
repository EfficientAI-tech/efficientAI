"""Together AI model id normalization (serverless vs deprecated dedicated endpoints)."""

from __future__ import annotations

# Serverless default when org catalog still lists retired Meta-Llama-3.1-8B-Instruct-Turbo.
TOGETHER_SERVERLESS_DEFAULT_MODEL = "meta-llama/Llama-3.2-3B-Instruct-Turbo"

_LEGACY_TOGETHER_MODEL_IDS = frozenset(
    {
        "meta-llama/meta-llama-3.1-8b-instruct-turbo",
        "meta-llama/meta-llama-3.1-8b-instruct",
    }
)


def normalize_together_model_name(model: str) -> str:
    """Map retired or dedicated-only Together ids to a current serverless model."""
    text = (model or "").strip()
    if not text:
        return text
    lower = text.lower()
    if lower in _LEGACY_TOGETHER_MODEL_IDS:
        return TOGETHER_SERVERLESS_DEFAULT_MODEL
    if "meta-llama-3.1-8b-instruct-turbo" in lower.replace("_", "-"):
        return TOGETHER_SERVERLESS_DEFAULT_MODEL
    return text
