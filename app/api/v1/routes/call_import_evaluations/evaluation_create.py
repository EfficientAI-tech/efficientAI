"""POST handler to create a call-import evaluation run."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.schemas import CallImportEvaluationCreate, CallImportEvaluationResponse
from app.services.call_imports.evaluation_create import create_call_import_evaluations

from app.api.v1.routes.call_import_evaluations._router import router


@router.post(
    "",
    response_model=CallImportEvaluationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createCallImportEvaluation",
)
async def create_call_import_evaluation(
    call_import_id: UUID,
    payload: CallImportEvaluationCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CallImportEvaluationResponse:
    del api_key
    return create_call_import_evaluations(
        db,
        organization_id=organization_id,
        principal=principal,
        call_import_id=call_import_id,
        payload=payload,
    )
