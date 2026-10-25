"""Celery task to ingest a knowledge base document."""

from __future__ import annotations

from uuid import UUID

from app.database import SessionLocal
from app.services.knowledge_bases.ingest import ingest_knowledge_document
from app.workers.config import celery_app


@celery_app.task(name="ingest_knowledge_document", bind=True, max_retries=2)
def ingest_knowledge_document_task(self, document_id: str):
    db = SessionLocal()
    try:
        ingest_knowledge_document(db, document_id=UUID(document_id))
    except Exception as exc:
        db.rollback()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30) from exc
        raise
    finally:
        db.close()
