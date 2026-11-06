"""Embedding defaults and provider hints for knowledge bases (pgvector is 1536-dim)."""

from __future__ import annotations

from typing import Dict, List, Tuple

from app.models.enums import ModelProvider

DEFAULT_EMBEDDING_PROVIDER = "openai"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_EMBEDDING_MODEL_LENGTH = 512

# Voice / TTS platforms — not offered in the KB embedding picker.
_EMBEDDING_EXCLUDED = {
    ModelProvider.DEEPGRAM,
    ModelProvider.CARTESIA,
    ModelProvider.ELEVENLABS,
    ModelProvider.MURF,
    ModelProvider.VOICEMAKER,
    ModelProvider.SMALLEST,
    ModelProvider.CUSTOM,
}

EMBEDDING_CAPABLE_PROVIDERS: List[ModelProvider] = [
    p for p in ModelProvider if p not in _EMBEDDING_EXCLUDED
]

PROVIDER_LABELS: Dict[str, str] = {
    ModelProvider.OPENAI.value: "OpenAI",
    ModelProvider.OPENROUTER.value: "OpenRouter",
    ModelProvider.ANTHROPIC.value: "Anthropic",
    ModelProvider.GOOGLE.value: "Google",
    ModelProvider.XAI.value: "xAI",
    ModelProvider.FIREWORKS.value: "Fireworks AI",
    ModelProvider.COHERE.value: "Cohere",
    ModelProvider.MISTRAL.value: "Mistral",
    ModelProvider.META.value: "Meta",
    ModelProvider.TOGETHER.value: "Together",
    ModelProvider.TYPESAFE.value: "TypeSafe",
    ModelProvider.PERPLEXITY.value: "Perplexity",
    ModelProvider.AZURE.value: "Azure",
    ModelProvider.AWS.value: "AWS",
    ModelProvider.SARVAM.value: "Sarvam",
}

# Curated models known to output EMBEDDING_DIMENSIONS (1536) vectors for pgvector.
SUGGESTED_EMBEDDING_MODELS: Dict[str, List[Tuple[str, str]]] = {
    "openai": [
        ("text-embedding-3-small", "text-embedding-3-small"),
        ("text-embedding-3-large", "text-embedding-3-large (1536 dims)"),
        ("text-embedding-ada-002", "text-embedding-ada-002"),
    ],
    "openrouter": [
        ("openai/text-embedding-3-small", "openai/text-embedding-3-small"),
        ("openai/text-embedding-3-large", "openai/text-embedding-3-large"),
    ],
    "azure": [
        ("text-embedding-3-small", "Deployment name (text-embedding-3-small)"),
    ],
}

# Backward-compatible flat list for legacy clients.
EMBEDDING_MODEL_CHOICES: List[Tuple[str, str]] = SUGGESTED_EMBEDDING_MODELS["openai"]


def normalize_embedding_provider(provider: str | None) -> str:
    raw = (provider or DEFAULT_EMBEDDING_PROVIDER).strip().lower()
    try:
        ModelProvider(raw)
    except ValueError as exc:
        allowed = ", ".join(sorted(p.value for p in EMBEDDING_CAPABLE_PROVIDERS))
        raise ValueError(
            f"Unsupported embedding provider '{raw}'. Choose one of: {allowed}"
        ) from exc
    if ModelProvider(raw) not in EMBEDDING_CAPABLE_PROVIDERS:
        raise ValueError(f"Provider '{raw}' is not available for knowledge base embeddings")
    return raw


def normalize_embedding_model(model: str | None) -> str:
    raw = (model or DEFAULT_EMBEDDING_MODEL).strip()
    if not raw:
        return DEFAULT_EMBEDDING_MODEL
    if len(raw) > MAX_EMBEDDING_MODEL_LENGTH:
        raise ValueError(
            f"embedding_model must be at most {MAX_EMBEDDING_MODEL_LENGTH} characters"
        )
    return raw
