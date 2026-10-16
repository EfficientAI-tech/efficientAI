"""Ingest a knowledge document: extract, chunk, embed, persist."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.database import KnowledgeBase, KnowledgeDocument
from app.services.knowledge_bases.chunking import chunk_text_pages
from app.services.knowledge_bases.embeddings import embed_texts
from app.services.knowledge_bases.embedding_config import profile_from_kb
from app.services.knowledge_bases.extract import extract_text_from_bytes
from app.services.storage.blob_storage_service import blob_storage_service


def ingest_knowledge_document(db: Session, *, document_id: UUID) -> None:
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if not doc:
        return
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.knowledge_base_id).first()
    embed_profile = profile_from_kb(kb)
    doc.status = "processing"
    doc.error_text = None
    db.commit()

    try:
        file_bytes = blob_storage_service.download_file_by_key(doc.blob_key)
        extension = (doc.original_filename or "file.txt").rsplit(".", 1)[-1].lower()
        pages = extract_text_from_bytes(file_bytes, extension=extension)
        chunks = chunk_text_pages(pages)
        if not chunks:
            raise ValueError("No text could be extracted from this document")

        db.execute(
            text("DELETE FROM knowledge_chunks WHERE document_id = :document_id"),
            {"document_id": str(doc.id)},
        )
        db.commit()

        batch_size = 32
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = embed_texts(
                db,
                organization_id=doc.organization_id,
                texts=[c.text for c in batch],
                provider=embed_profile.provider,
                model=embed_profile.model,
                credential_id=embed_profile.credential_id,
            )
            for chunk, vector in zip(batch, vectors):
                db.execute(
                    text(
                        """
                        INSERT INTO knowledge_chunks
                            (id, document_id, chunk_index, text, page_number, embedding, embedding_model)
                        VALUES
                            (:id, :document_id, :chunk_index, :text, :page_number,
                             CAST(:embedding AS vector), :embedding_model)
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "document_id": str(doc.id),
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "page_number": chunk.page_number,
                        "embedding": _vector_literal(vector),
                        "embedding_model": embed_profile.model,
                    },
                )
        doc.status = "ready"
        doc.error_text = None
        db.commit()
    except Exception as exc:
        db.rollback()
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if doc:
            doc.status = "failed"
            doc.error_text = str(exc)[:2000]
            db.commit()
        return


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"
