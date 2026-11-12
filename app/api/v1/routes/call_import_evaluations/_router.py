"""Shared APIRouter for call import evaluation endpoints."""

from fastapi import APIRouter, Depends

from app.dependencies import require_enterprise_feature

router = APIRouter(
    prefix="/call-imports/{call_import_id}/evaluations",
    tags=["Call Import Evaluations"],
    dependencies=[Depends(require_enterprise_feature("call_imports"))],
)
