"""Resolve and validate knowledge-base embedding settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import KnowledgeBase
from app.models.enums import ModelProvider
from app.services.credentials.resolver import resolve_ai_provider
from app.services.knowledge_bases.embeddings_catalog import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    MAX_EMBEDDING_MODEL_LENGTH,
    normalize_embedding_model,
    normalize_embedding_provider,
)


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    credential_id: Optional[UUID]

    def cache_key(self) -> tuple[str, str, Optional[str]]:
        cred = str(self.credential_id) if self.credential_id else None
        return (self.provider, self.model, cred)


def profile_from_kb(kb: KnowledgeBase | None) -> EmbeddingProfile:
    if kb is None:
        return EmbeddingProfile(
            provider=DEFAULT_EMBEDDING_PROVIDER,
            model=DEFAULT_EMBEDDING_MODEL,
            credential_id=None,
        )
    return EmbeddingProfile(
        provider=normalize_embedding_provider(getattr(kb, "embedding_provider", None)),
        model=normalize_embedding_model(getattr(kb, "embedding_model", None)),
        credential_id=getattr(kb, "embedding_credential_id", None),
    )


def validate_embedding_credential(
    db: Session,
    *,
    organization_id: UUID,
    provider: ModelProvider,
    credential_id: Optional[UUID],
) -> Optional[UUID]:
    if credential_id is None:
        return None
    row = resolve_ai_provider(
        provider, db, organization_id, credential_id=credential_id
    )
    if not row:
        raise ValueError(
            "embedding_credential_id does not match an active credential for this provider"
        )
    return credential_id


def parse_embedding_fields(
    db: Session,
    *,
    organization_id: UUID,
    embedding_provider: str | None,
    embedding_model: str | None,
    embedding_credential_id: UUID | None,
) -> EmbeddingProfile:
    provider = normalize_embedding_provider(embedding_provider)
    model = normalize_embedding_model(embedding_model)
    provider_enum = ModelProvider(provider)
    cred = validate_embedding_credential(
        db,
        organization_id=organization_id,
        provider=provider_enum,
        credential_id=embedding_credential_id,
    )
    return EmbeddingProfile(provider=provider, model=model, credential_id=cred)


def embedding_profile_changed(kb: KnowledgeBase, profile: EmbeddingProfile) -> bool:
    current = profile_from_kb(kb)
    return current.cache_key() != profile.cache_key()
