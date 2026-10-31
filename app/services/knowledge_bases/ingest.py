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

_INGEST_LOCK_NS = 0x4B42_444F  # "KBDO" — serialize ingest per document across workers


def _signed_int32(value: int) -> int:
    """pg_advisory_lock(int, int) requires signed 32-bit keys."""
    value &= 0xFFFFFFFF
    if value > 0x7FFFFFFF:
        return value - 0x100000000
    return value


def _ingest_advisory_keys(document_id: UUID) -> tuple[int, int]:
    b = document_id.bytes
    doc_key = int.from_bytes(b[0:4], "big") ^ int.from_bytes(b[4:8], "big")
    return (_signed_int32(_INGEST_LOCK_NS), _signed_int32(doc_key))


def ingest_knowledge_document(db: Session, *, document_id: UUID) -> None:
    lock_k1, lock_k2 = _ingest_advisory_keys(document_id)
    bind = db.get_bind()
    with bind.connect() as lock_conn:
        lock_conn.execute(
            text("SELECT pg_advisory_lock(:k1, :k2)"),
            {"k1": lock_k1, "k2": lock_k2},
        )
        work = Session(bind=lock_conn, expire_on_commit=False)
        try:
            _ingest_knowledge_document_locked(work, document_id=document_id)
        finally:
            work.close()
            lock_conn.execute(
                text("SELECT pg_advisory_unlock(:k1, :k2)"),
                {"k1": lock_k1, "k2": lock_k2},
            )


def _ingest_knowledge_document_locked(db: Session, *, document_id: UUID) -> None:
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id)
        .with_for_update()
        .first()
    )
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
        db.refresh(kb)
        current_profile = profile_from_kb(kb)
        if (
            current_profile.provider != embed_profile.provider
            or current_profile.model != embed_profile.model
            or current_profile.credential_id != embed_profile.credential_id
        ):
            doc.status = "pending"
            doc.error_text = None
            db.commit()
            from app.workers.tasks.ingest_knowledge_document import (
                ingest_knowledge_document_task,
            )

            ingest_knowledge_document_task.delay(str(doc.id))
            return
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
