"""Import and manage org-owned Vobiz phone numbers (delegates to shared import service)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.telephony.number_import_service import import_numbers, list_available_numbers
from app.services.telephony.telephony_service import telephony_service
from app.models.enums import TelephonyProvider


def list_available_vobiz_numbers(
    db: Session,
    org_id: UUID,
    *,
    credential_id: Optional[UUID] = None,
) -> List[Dict[str, Any]]:
    """Return Vobiz account numbers with import status for this org."""
    return list_available_numbers(
        db,
        org_id,
        TelephonyProvider.VOBIZ.value,
        credential_id=credential_id,
    )


def import_vobiz_numbers(
    db: Session,
    org_id: UUID,
    *,
    numbers: List[str],
    agent_id: Optional[UUID] = None,
    credential_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Import one or more Vobiz numbers for an organization."""
    return import_numbers(
        db,
        org_id,
        TelephonyProvider.VOBIZ.value,
        numbers=numbers,
        agent_id=agent_id,
        credential_id=credential_id,
    )


def deactivate_imported_number(db: Session, org_id: UUID, number_id: UUID) -> None:
    """Permanently remove an imported number from org inventory and unlink agents."""
    try:
        telephony_service.remove_org_phone_number(org_id, number_id, db)
    except ValueError as exc:
        if str(exc) == "Phone number not found":
            raise ValueError("Imported number not found") from exc
        raise
