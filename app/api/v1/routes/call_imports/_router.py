"""Shared APIRouter for call import endpoints."""

from fastapi import APIRouter, Depends

from app.dependencies import require_enterprise_feature

router = APIRouter(
    prefix="/call-imports",
    tags=["Call Imports"],
    dependencies=[Depends(require_enterprise_feature("call_imports"))],
)
