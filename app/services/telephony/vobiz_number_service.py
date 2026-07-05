"""Import and manage org-owned Vobiz phone numbers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import Agent, TelephonyIntegration, TelephonyPhoneNumber
from app.models.enums import TelephonyProvider
from app.services.telephony.phone_routing import sync_agent_telephony_number_link
from app.services.telephony.plivo_client import expand_phone_candidates, normalize_e164
from app.services.telephony.vobiz_agent_context import vobiz_webhook_base_url
from app.services.telephony.vobiz_client import VobizClient, build_vobiz_client_for_org


def _answer_webhook_url() -> str:
    base = vobiz_webhook_base_url()
    return f"{base}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/answer"


def _normalize_provider_number(item: Dict[str, Any]) -> Optional[str]:
    raw = item.get("e164") or item.get("number") or item.get("phone_number")
    if not raw:
        return None
    try:
        return normalize_e164(str(raw))
    except ValueError:
        candidates = expand_phone_candidates(str(raw))
        return candidates[0] if candidates else None


def list_available_vobiz_numbers(
    db: Session,
    org_id: UUID,
) -> List[Dict[str, Any]]:
    """Return Vobiz account numbers with import status for this org."""
    client, _ = build_vobiz_client_for_org(db, org_id)
    remote_numbers = client.list_account_numbers()

    imported_rows = (
        db.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.organization_id == org_id,
            TelephonyPhoneNumber.is_active.is_(True),
        )
        .all()
    )
    imported_by_phone = {row.phone_number: row for row in imported_rows}

    results: List[Dict[str, Any]] = []
    for item in remote_numbers:
        e164 = _normalize_provider_number(item)
        if not e164:
            continue
        imported = imported_by_phone.get(e164)
        results.append(
            {
                "e164": e164,
                "provider_number_id": item.get("id"),
                "country": item.get("country"),
                "region": item.get("region"),
                "capabilities": item.get("capabilities"),
                "status": item.get("status"),
                "application_id": item.get("application_id"),
                "already_imported": imported is not None,
                "imported_number_id": str(imported.id) if imported else None,
            }
        )
    return results


def _resolve_integration_for_import(
    db: Session,
    org_id: UUID,
    integration: Optional[TelephonyIntegration],
) -> Optional[UUID]:
    if integration:
        return integration.id
    platform_integration = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.organization_id == org_id,
            TelephonyIntegration.provider == TelephonyProvider.VOBIZ.value,
            TelephonyIntegration.is_active.is_(True),
        )
        .order_by(TelephonyIntegration.is_default.desc())
        .first()
    )
    return platform_integration.id if platform_integration else None


def import_vobiz_numbers(
    db: Session,
    org_id: UUID,
    *,
    numbers: List[str],
    agent_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Import one or more Vobiz numbers for an organization."""
    if not numbers:
        raise ValueError("At least one number is required")

    client, integration = build_vobiz_client_for_org(db, org_id)
    integration_id = _resolve_integration_for_import(db, org_id, integration)

    remote_by_e164: Dict[str, Dict[str, Any]] = {}
    for item in client.list_account_numbers():
        e164 = _normalize_provider_number(item)
        if e164:
            remote_by_e164[e164] = item

    agent: Optional[Agent] = None
    if agent_id:
        agent = (
            db.query(Agent)
            .filter(Agent.id == agent_id, Agent.organization_id == org_id)
            .first()
        )
        if not agent:
            raise ValueError("Agent not found for organization")

    answer_url = _answer_webhook_url()
    results: List[Dict[str, Any]] = []
    linked_agent = False

    for raw_number in numbers:
        try:
            e164 = normalize_e164(raw_number)
        except ValueError:
            results.append(
                {
                    "number": raw_number,
                    "success": False,
                    "message": "Invalid phone number format",
                    "answer_url": answer_url,
                }
            )
            continue

        remote = remote_by_e164.get(e164)
        if not remote:
            results.append(
                {
                    "number": e164,
                    "success": False,
                    "message": "Number not found on the connected Vobiz account",
                    "answer_url": answer_url,
                }
            )
            continue

        conflict = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.phone_number == e164,
                TelephonyPhoneNumber.inbound_enabled.is_(True),
                TelephonyPhoneNumber.source != "platform_pool",
                TelephonyPhoneNumber.organization_id != org_id,
                TelephonyPhoneNumber.is_active.is_(True),
            )
            .first()
        )
        if conflict:
            results.append(
                {
                    "number": e164,
                    "success": False,
                    "message": "Number is already imported by another organization",
                    "answer_url": answer_url,
                }
            )
            continue

        row = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.organization_id == org_id,
                TelephonyPhoneNumber.phone_number == e164,
            )
            .first()
        )
        if row:
            row.is_active = True
            row.inbound_enabled = True
            row.outbound_enabled = True
            row.source = "imported"
            row.country_iso2 = remote.get("country") or row.country_iso2
            row.region = remote.get("region") or row.region
            row.capabilities = remote.get("capabilities") or row.capabilities
            row.provider_app_id = remote.get("application_id") or row.provider_app_id
            if integration_id:
                row.telephony_integration_id = integration_id
        else:
            row = TelephonyPhoneNumber(
                organization_id=org_id,
                telephony_integration_id=integration_id,
                phone_number=e164,
                country_iso2=remote.get("country"),
                region=remote.get("region"),
                capabilities=remote.get("capabilities"),
                provider_app_id=remote.get("application_id"),
                inbound_enabled=True,
                outbound_enabled=True,
                source="imported",
                is_active=True,
            )
            db.add(row)
            db.flush()

        webhook_ok, webhook_message, app_id = client.set_number_answer_url(
            e164,
            answer_url,
            existing_application_id=remote.get("application_id"),
            app_name=f"efficientai_{org_id.hex[:8]}",
        )
        if app_id:
            row.provider_app_id = app_id

        if agent and not linked_agent:
            agent.telephony_phone_number_id = row.id
            agent.phone_number = e164
            sync_agent_telephony_number_link(db, agent)
            linked_agent = True
        else:
            db.commit()

        results.append(
            {
                "number": e164,
                "success": True,
                "message": webhook_message if webhook_ok else f"Imported; configure Answer URL manually: {webhook_message}",
                "answer_url": answer_url,
                "webhook_configured": webhook_ok,
                "imported_number_id": str(row.id),
                "application_id": app_id,
            }
        )
        logger.info(
            "Imported Vobiz number {} for org {} (webhook_configured={})",
            e164,
            org_id,
            webhook_ok,
        )

    return {"results": results, "answer_url": answer_url}


def deactivate_imported_number(db: Session, org_id: UUID, number_id: UUID) -> None:
    """Permanently remove an imported number from org inventory and unlink agents."""
    row = (
        db.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.id == number_id,
            TelephonyPhoneNumber.organization_id == org_id,
        )
        .first()
    )
    if not row:
        raise ValueError("Imported number not found")

    if row.agent_id:
        agent = db.query(Agent).filter(Agent.id == row.agent_id).first()
        if agent and agent.telephony_phone_number_id == row.id:
            agent.telephony_phone_number_id = None
            agent.phone_number = None
    row.agent_id = None
    db.delete(row)
    db.commit()
