"""Knowledge base CRUD and document upload."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.dependencies import get_db, get_organization_id, get_workspace_id
from app.models.database import AgentKnowledgeBase, KnowledgeBase, KnowledgeDocument
from app.models.schemas import (
    EmbeddingConfigHelpResponse,
    EmbeddingModelOption,
    EmbeddingProviderOption,
    KnowledgeBaseCreate,
    KnowledgeBaseDetailResponse,
    KnowledgeBaseSummaryResponse,
    KnowledgeBaseUpdate,
    KnowledgeDocumentPagePreview,
    KnowledgeDocumentResponse,
    KnowledgeDocumentViewResponse,
)
from app.services.knowledge_bases.document_view import build_document_view_payload
from app.services.knowledge_bases.embedding_config import (
    embedding_profile_changed,
    parse_embedding_fields,
    profile_from_kb,
)
from app.services.knowledge_bases.embeddings_catalog import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    EMBEDDING_CAPABLE_PROVIDERS,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_CHOICES,
    PROVIDER_LABELS,
    SUGGESTED_EMBEDDING_MODELS,
)
from app.services.knowledge_bases.paths import (
    MAX_KB_UPLOAD_BYTES,
    knowledge_document_blob_key,
    validate_kb_upload_filename,
)
from app.services.storage.blob_storage_service import blob_storage_service
from app.utils.upload_limits import UploadTooLargeError, read_upload_with_limit

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def _kb_detail_fields(row: KnowledgeBase) -> dict:
    profile = profile_from_kb(row)
    return {
        "embedding_provider": profile.provider,
        "embedding_model": profile.model,
        "embedding_credential_id": profile.credential_id,
    }


def _apply_embedding_patch(
    db: Session,
    *,
    row: KnowledgeBase,
    organization_id: UUID,
    data: dict,
) -> bool:
    """Apply embedding fields from PATCH payload; return True if re-index needed."""
    embedding_keys = {
        "embedding_provider",
        "embedding_model",
        "embedding_credential_id",
    }
    if not embedding_keys.intersection(data.keys()):
        return False
    current = profile_from_kb(row)
    provider = (
        data["embedding_provider"]
        if "embedding_provider" in data and data["embedding_provider"] is not None
        else current.provider
    )
    model = (
        data["embedding_model"]
        if "embedding_model" in data and data["embedding_model"] is not None
        else current.model
    )
    if "embedding_credential_id" in data:
        credential_id = data["embedding_credential_id"]
    else:
        credential_id = current.credential_id
    try:
        profile = parse_embedding_fields(
            db,
            organization_id=organization_id,
            embedding_provider=provider,
            embedding_model=model,
            embedding_credential_id=credential_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    changed = embedding_profile_changed(row, profile)
    row.embedding_provider = profile.provider
    row.embedding_model = profile.model
    row.embedding_credential_id = profile.credential_id
    return changed


def _queue_reindex_documents(db: Session, kb_id: UUID) -> int:
    # Skip documents already ingesting: ingest_knowledge_document re-queues itself if
    # the KB embedding profile changes mid-run; overlapping tasks caused duplicate chunks
    # before per-document advisory locks (see ingest.py).
    docs = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.knowledge_base_id == kb_id,
            KnowledgeDocument.status.in_(("ready", "failed")),
        )
        .all()
    )
    if not docs:
        return 0
    from app.workers.tasks.ingest_knowledge_document import ingest_knowledge_document_task

    for doc in docs:
        doc.status = "pending"
        doc.error_text = None
    db.commit()
    for doc in docs:
        ingest_knowledge_document_task.delay(str(doc.id))
    return len(docs)


def _get_document_or_404(
    db: Session,
    *,
    knowledge_base_id: UUID,
    document_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> KnowledgeDocument:
    doc = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
            KnowledgeDocument.organization_id == organization_id,
            KnowledgeDocument.workspace_id == workspace_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _document_counts(db: Session, kb_id: UUID) -> tuple[int, int, int]:
    total = (
        db.query(func.count(KnowledgeDocument.id))
        .filter(KnowledgeDocument.knowledge_base_id == kb_id)
        .scalar()
        or 0
    )
    ready = (
        db.query(func.count(KnowledgeDocument.id))
        .filter(
            KnowledgeDocument.knowledge_base_id == kb_id,
            KnowledgeDocument.status == "ready",
        )
        .scalar()
        or 0
    )
    failed = (
        db.query(func.count(KnowledgeDocument.id))
        .filter(
            KnowledgeDocument.knowledge_base_id == kb_id,
            KnowledgeDocument.status == "failed",
        )
        .scalar()
        or 0
    )
    return int(total), int(ready), int(failed)


def _linked_agent_count(db: Session, kb_id: UUID) -> int:
    return (
        db.query(func.count(func.distinct(AgentKnowledgeBase.agent_id)))
        .filter(AgentKnowledgeBase.knowledge_base_id == kb_id)
        .scalar()
        or 0
    )


def _get_kb_or_404(
    db: Session,
    *,
    knowledge_base_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> KnowledgeBase:
    row = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.organization_id == organization_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return row


@router.post("", response_model=KnowledgeBaseDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_principal),
):
    try:
        profile = parse_embedding_fields(
            db,
            organization_id=organization_id,
            embedding_provider=payload.embedding_provider,
            embedding_model=payload.embedding_model,
            embedding_credential_id=payload.embedding_credential_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = KnowledgeBase(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        embedding_provider=profile.provider,
        embedding_model=profile.model,
        embedding_credential_id=profile.credential_id,
        status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return KnowledgeBaseDetailResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        documents=[],
        linked_agent_count=0,
        created_at=row.created_at,
        updated_at=row.updated_at,
        **_kb_detail_fields(row),
    )


@router.get("/embedding-models", response_model=List[EmbeddingModelOption])
async def list_embedding_models():
    return [EmbeddingModelOption(id=model_id, label=label) for model_id, label in EMBEDDING_MODEL_CHOICES]


@router.get("/embedding-config", response_model=EmbeddingConfigHelpResponse)
async def get_embedding_config():
    providers: List[EmbeddingProviderOption] = []
    for provider in EMBEDDING_CAPABLE_PROVIDERS:
        pid = provider.value
        suggested = SUGGESTED_EMBEDDING_MODELS.get(pid, [])
        if not suggested:
            continue
        providers.append(
            EmbeddingProviderOption(
                id=pid,
                label=PROVIDER_LABELS.get(pid, pid),
                suggested_models=[
                    EmbeddingModelOption(id=model_id, label=label)
                    for model_id, label in suggested
                ],
            )
        )
    return EmbeddingConfigHelpResponse(
        default_provider=DEFAULT_EMBEDDING_PROVIDER,
        default_model=DEFAULT_EMBEDDING_MODEL,
        required_dimensions=EMBEDDING_DIMENSIONS,
        providers=providers,
    )


@router.get("", response_model=List[KnowledgeBaseSummaryResponse])
async def list_knowledge_bases(
    skip: int = 0,
    limit: int = 100,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.organization_id == organization_id,
            KnowledgeBase.workspace_id == workspace_id,
        )
        .order_by(KnowledgeBase.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    summaries: List[KnowledgeBaseSummaryResponse] = []
    for row in rows:
        total, ready, failed = _document_counts(db, row.id)
        summaries.append(
            KnowledgeBaseSummaryResponse(
                id=row.id,
                name=row.name,
                description=row.description,
                status=row.status,
                **_kb_detail_fields(row),
                document_count=total,
                ready_document_count=ready,
                failed_document_count=failed,
                linked_agent_count=_linked_agent_count(db, row.id),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return summaries


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseDetailResponse)
async def get_knowledge_base(
    knowledge_base_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    row = _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    documents = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == row.id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )
    return KnowledgeBaseDetailResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        documents=[KnowledgeDocumentResponse.model_validate(doc) for doc in documents],
        linked_agent_count=_linked_agent_count(db, row.id),
        created_at=row.created_at,
        updated_at=row.updated_at,
        **_kb_detail_fields(row),
    )


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseDetailResponse)
async def update_knowledge_base(
    knowledge_base_id: UUID,
    payload: KnowledgeBaseUpdate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    row = _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        row.name = data["name"].strip()
    if "description" in data:
        row.description = (data["description"] or "").strip() or None
    if "status" in data and data["status"] is not None:
        row.status = data["status"]
    if _apply_embedding_patch(
        db, row=row, organization_id=organization_id, data=data
    ):
        _queue_reindex_documents(db, row.id)
    db.commit()
    db.refresh(row)
    return await get_knowledge_base(knowledge_base_id, organization_id, workspace_id, db)


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    knowledge_base_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    row = _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    docs = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == row.id)
        .all()
    )
    for doc in docs:
        try:
            blob_storage_service.delete_file_by_key(doc.blob_key)
        except Exception:
            pass
    db.delete(row)
    db.commit()
    return None


@router.post(
    "/{knowledge_base_id}/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_knowledge_document(
    knowledge_base_id: UUID,
    file: UploadFile = File(...),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_principal),
):
    kb = _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    filename = file.filename or "document.txt"
    try:
        extension, content_type = validate_kb_upload_filename(filename)
        file_bytes = await read_upload_with_limit(file, MAX_KB_UPLOAD_BYTES)
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {exc.max_bytes} bytes",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document_id = uuid4()
    blob_key = knowledge_document_blob_key(
        organization_id,
        workspace_id,
        kb.id,
        document_id,
        extension,
    )
    blob_storage_service.upload_file_by_key(file_bytes, blob_key, content_type=content_type)

    doc = KnowledgeDocument(
        id=document_id,
        knowledge_base_id=kb.id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_type="file",
        original_filename=filename,
        blob_key=blob_key,
        content_type=content_type,
        byte_size=len(file_bytes),
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    from app.workers.tasks.ingest_knowledge_document import ingest_knowledge_document_task

    ingest_knowledge_document_task.delay(str(doc.id))
    return KnowledgeDocumentResponse.model_validate(doc)


@router.post(
    "/{knowledge_base_id}/documents/{document_id}/retry",
    response_model=KnowledgeDocumentResponse,
)
async def retry_knowledge_document(
    knowledge_base_id: UUID,
    document_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    doc = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
            KnowledgeDocument.organization_id == organization_id,
            KnowledgeDocument.workspace_id == workspace_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status not in ("failed", "ready"):
        raise HTTPException(status_code=400, detail="Document is not eligible for retry")
    doc.status = "pending"
    doc.error_text = None
    db.commit()
    db.refresh(doc)
    from app.workers.tasks.ingest_knowledge_document import ingest_knowledge_document_task

    ingest_knowledge_document_task.delay(str(doc.id))
    return KnowledgeDocumentResponse.model_validate(doc)


@router.get(
    "/{knowledge_base_id}/documents/{document_id}/view",
    response_model=KnowledgeDocumentViewResponse,
)
async def view_knowledge_document(
    knowledge_base_id: UUID,
    document_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    doc = _get_document_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    try:
        payload = build_document_view_payload(
            original_filename=doc.original_filename,
            content_type=doc.content_type,
            blob_key=doc.blob_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load document: {exc}") from exc
    pages = payload.get("pages")
    page_models = None
    if pages:
        page_models = [
            KnowledgeDocumentPagePreview(page=p.get("page"), text=p.get("text") or "")
            for p in pages
        ]
    return KnowledgeDocumentViewResponse(
        knowledge_base_id=kb.id,
        knowledge_base_name=kb.name,
        document_id=doc.id,
        view_mode=str(payload.get("view_mode") or "binary"),
        original_filename=payload.get("original_filename"),
        content_type=payload.get("content_type"),
        text_content=payload.get("text_content"),
        pages=page_models,
        page_count=payload.get("page_count"),
    )


@router.get("/{knowledge_base_id}/documents/{document_id}/download")
async def download_knowledge_document(
    knowledge_base_id: UUID,
    document_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    doc = _get_document_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    try:
        file_bytes = blob_storage_service.download_file_by_key(doc.blob_key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="File not found in storage") from exc
    filename = doc.original_filename or f"document-{doc.id}"
    media_type = doc.content_type or "application/octet-stream"
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return Response(content=file_bytes, media_type=media_type, headers=headers)


@router.delete(
    "/{knowledge_base_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_document(
    knowledge_base_id: UUID,
    document_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _get_kb_or_404(
        db,
        knowledge_base_id=knowledge_base_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    doc = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
            KnowledgeDocument.organization_id == organization_id,
            KnowledgeDocument.workspace_id == workspace_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        blob_storage_service.delete_file_by_key(doc.blob_key)
    except Exception:
        pass
    db.delete(doc)
    db.commit()
    return None


from app.core.auth.capabilities import SIM_MANAGE, SIM_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=SIM_VIEW,
    manage_capability=SIM_MANAGE,
)
