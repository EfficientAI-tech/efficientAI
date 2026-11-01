"""Embedding helpers for knowledge base chunks (multi-provider via LiteLLM)."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

import litellm
from sqlalchemy.orm import Session

from app.models.enums import ModelProvider
from app.services.ai.llm_gateway import (
    apply_llm_gateway,
    resolve_effective_routing,
    resolve_litellm_api_key,
    resolve_litellm_model,
)
from app.services.ai.llm_service import canonical_litellm_model_id, llm_service
from app.services.knowledge_bases.embeddings_catalog import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    EMBEDDING_DIMENSIONS,
    normalize_embedding_model,
    normalize_embedding_provider,
)


def embed_texts(
    db: Session,
    *,
    organization_id: UUID,
    texts: List[str],
    provider: str = DEFAULT_EMBEDDING_PROVIDER,
    model: str = DEFAULT_EMBEDDING_MODEL,
    credential_id: Optional[UUID] = None,
    dimensions: int = EMBEDDING_DIMENSIONS,
) -> List[List[float]]:
    if not texts:
        return []
    provider_value = normalize_embedding_provider(provider)
    model = normalize_embedding_model(model)
    llm_provider = ModelProvider(provider_value)

    ai_provider, credential_ctx = llm_service._resolve_credential_context(  # noqa: SLF001
        llm_provider,
        db,
        organization_id,
        credential_id=credential_id,
    )
    if ai_provider:
        api_key = resolve_litellm_api_key(
            organization_id,
            db,
            ai_provider,
            credential=credential_ctx,
        )
    else:
        api_key = llm_service._resolve_api_key(  # noqa: SLF001
            llm_provider, db, organization_id, credential_id=credential_id
        )

    _, effective_routing = resolve_effective_routing(
        organization_id, db, credential_ctx
    )
    workload_model_str = llm_service._litellm_model_name(llm_provider, model)  # noqa: SLF001
    model_str = canonical_litellm_model_id(
        resolve_litellm_model(
            workload_model_str=workload_model_str,
            gateway_active=effective_routing != "direct",
            credential=credential_ctx,
        )
    )

    kwargs: dict = {"model": model_str, "input": texts}
    if api_key:
        kwargs["api_key"] = api_key
    if (
        llm_provider == ModelProvider.OPENAI
        and model.startswith("text-embedding-3-")
    ):
        kwargs["dimensions"] = dimensions

    kwargs = apply_llm_gateway(
        kwargs,
        organization_id=organization_id,
        db=db,
        model=model_str,
        credential=credential_ctx,
    )

    try:
        response = litellm.embedding(**kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"Embedding request failed for {provider_value}/{model}: {exc}"
        ) from exc

    data = getattr(response, "data", None) or []
    ordered = sorted(data, key=lambda row: getattr(row, "index", 0))
    vectors: List[List[float]] = []
    for row in ordered:
        emb = getattr(row, "embedding", None)
        if emb is None and isinstance(row, dict):
            emb = row.get("embedding")
        if not emb:
            raise RuntimeError("Embedding API returned empty vector")
        vec = list(emb)
        if len(vec) != dimensions:
            raise RuntimeError(
                f"Embedding model returned {len(vec)} dimensions; "
                f"knowledge bases require {dimensions}. "
                "Choose a model that outputs 1536 vectors (e.g. OpenAI text-embedding-3-* "
                "with dimensions=1536) or re-index after changing pgvector size."
            )
        vectors.append(vec)
    return vectors
