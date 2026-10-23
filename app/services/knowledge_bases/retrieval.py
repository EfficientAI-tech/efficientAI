"""Vector retrieval for agent-attached knowledge bases."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.database import AgentKnowledgeBase
from app.services.knowledge_bases.agent_links import KB_ROLE_PRODUCTION
from app.services.knowledge_bases.embedding_config import EmbeddingProfile
from app.services.knowledge_bases.embeddings import embed_texts
from app.services.knowledge_bases.embeddings_catalog import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
)

TOP_K = 5
# Cosine-style scores from pgvector; below this, chunks are usually unrelated noise.
DEFAULT_MIN_SCORE = 0.32


def agent_has_ready_knowledge(
    db: Session, *, agent_id: UUID, role: str = KB_ROLE_PRODUCTION
) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM agent_knowledge_bases akb
            JOIN knowledge_documents kd ON kd.knowledge_base_id = akb.knowledge_base_id
            WHERE akb.agent_id = :agent_id AND akb.role = :role AND kd.status = 'ready'
            LIMIT 1
            """
        ),
        {"agent_id": str(agent_id), "role": role},
    ).first()
    return row is not None


def list_agent_knowledge_base_ids(
    db: Session, *, agent_id: UUID, role: str = KB_ROLE_PRODUCTION
) -> List[UUID]:
    rows = (
        db.query(AgentKnowledgeBase.knowledge_base_id)
        .filter(AgentKnowledgeBase.agent_id == agent_id, AgentKnowledgeBase.role == role)
        .all()
    )
    return [row[0] for row in rows]


def _agent_embedding_profiles(
    db: Session, *, agent_id: UUID, role: str = KB_ROLE_PRODUCTION
) -> List[EmbeddingProfile]:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT
                COALESCE(kb.embedding_provider, :default_provider),
                COALESCE(kb.embedding_model, :default_model),
                kb.embedding_credential_id
            FROM agent_knowledge_bases akb
            JOIN knowledge_bases kb ON kb.id = akb.knowledge_base_id
            WHERE akb.agent_id = :agent_id AND akb.role = :role
            """
        ),
        {
            "agent_id": str(agent_id),
            "role": role,
            "default_provider": DEFAULT_EMBEDDING_PROVIDER,
            "default_model": DEFAULT_EMBEDDING_MODEL,
        },
    ).fetchall()
    if not rows:
        return [
            EmbeddingProfile(
                provider=DEFAULT_EMBEDDING_PROVIDER,
                model=DEFAULT_EMBEDDING_MODEL,
                credential_id=None,
            )
        ]
    profiles: List[EmbeddingProfile] = []
    seen: set[tuple[str, str, str | None]] = set()
    for provider, model, credential_id in rows:
        cred_str = str(credential_id) if credential_id else None
        key = (str(provider), str(model), cred_str)
        if key in seen:
            continue
        seen.add(key)
        profiles.append(
            EmbeddingProfile(
                provider=str(provider),
                model=str(model),
                credential_id=credential_id,
            )
        )
    return profiles


def search_knowledge_base(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    query: str,
    top_k: int = TOP_K,
    min_score: Optional[float] = None,
    role: str = KB_ROLE_PRODUCTION,
) -> List[Dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    threshold = DEFAULT_MIN_SCORE if min_score is None else min_score
    merged: List[Dict[str, Any]] = []
    for profile in _agent_embedding_profiles(db, agent_id=agent_id, role=role):
        vectors = embed_texts(
            db,
            organization_id=organization_id,
            texts=[query],
            provider=profile.provider,
            model=profile.model,
            credential_id=profile.credential_id,
        )
        if not vectors:
            continue
        embedding_literal = _vector_literal(vectors[0])
        rows = db.execute(
            text(
                """
                SELECT
                    kc.text,
                    kd.original_filename,
                    kc.page_number,
                    kb.name AS knowledge_base_name,
                    1 - (kc.embedding <=> CAST(:embedding AS vector)) AS score
                FROM agent_knowledge_bases akb
                JOIN knowledge_bases kb ON kb.id = akb.knowledge_base_id
                JOIN knowledge_documents kd ON kd.knowledge_base_id = kb.id
                JOIN knowledge_chunks kc ON kc.document_id = kd.id
                WHERE akb.agent_id = :agent_id
                  AND akb.role = :role
                  AND akb.organization_id = :organization_id
                  AND akb.workspace_id = :workspace_id
                  AND kd.status = 'ready'
                  AND kc.embedding IS NOT NULL
                  AND COALESCE(kb.embedding_provider, :default_provider) = :embedding_provider
                  AND COALESCE(kb.embedding_model, :default_model) = :embedding_model
                  AND kb.embedding_credential_id IS NOT DISTINCT FROM CAST(:credential_id AS uuid)
                ORDER BY kc.embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
                """
            ),
            {
                "agent_id": str(agent_id),
                "role": role,
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
                "embedding": embedding_literal,
                "embedding_provider": profile.provider,
                "embedding_model": profile.model,
                "credential_id": str(profile.credential_id)
                if profile.credential_id
                else None,
                "default_provider": DEFAULT_EMBEDDING_PROVIDER,
                "default_model": DEFAULT_EMBEDDING_MODEL,
                "limit": top_k,
            },
        ).mappings().all()
        for row in rows:
            score = float(row["score"]) if row["score"] is not None else None
            if score is not None and score < threshold:
                continue
            merged.append(
                {
                    "text": row["text"],
                    "document_name": row["original_filename"] or "document",
                    "page": row["page_number"],
                    "knowledge_base_name": row["knowledge_base_name"],
                    "score": score,
                }
            )
    merged.sort(key=lambda hit: hit.get("score") or 0.0, reverse=True)
    return merged[:top_k]


def format_search_results_for_tool(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "No matching passages found in the attached knowledge bases."
    parts: List[str] = []
    for i, hit in enumerate(results, start=1):
        doc = hit.get("document_name") or "document"
        page = hit.get("page")
        page_suffix = f", page {page}" if page is not None else ""
        parts.append(f"[{i}] {doc}{page_suffix}:\n{hit.get('text', '').strip()}")
    return "\n\n".join(parts)


def _vector_literal(values: List[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"
