"""Provider-agnostic telephony number import (Vobiz, Plivo, Exotel)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import Agent, TelephonyIntegration, TelephonyPhoneNumber
from app.models.enums import TelephonyProvider
from app.services.telephony.phone_routing import sync_agent_telephony_number_link
from app.services.telephony.plivo_client import PlivoClient, expand_phone_candidates, normalize_e164
from app.services.telephony.plivo_webhook_urls import (
    legacy_answer_webhook_url,
    plivo_answer_webhook_url,
    plivo_hangup_webhook_url,
)
from app.services.telephony.telephony_service import telephony_service
from app.services.telephony.vobiz_agent_context import vobiz_webhook_base_url
from app.services.telephony.vobiz_client import VobizClient, build_vobiz_client_for_org

IMPORT_SUPPORTED_PROVIDERS = frozenset(
    {
        TelephonyProvider.VOBIZ.value,
        TelephonyProvider.PLIVO.value,
        TelephonyProvider.EXOTEL.value,
    }
)


def _assert_import_provider(provider: str) -> str:
    provider_key = (provider or "").lower()
    if provider_key not in IMPORT_SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported telephony provider for import: {provider}. "
            f"Supported: {', '.join(sorted(IMPORT_SUPPORTED_PROVIDERS))}"
        )
    return provider_key


def _vobiz_answer_webhook_url() -> str:
    base = vobiz_webhook_base_url()
    return f"{base}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/answer"


def _plivo_answer_webhook_url() -> str:
    return plivo_answer_webhook_url()


def _plivo_hangup_webhook_url() -> str:
    return plivo_hangup_webhook_url()


def _exotel_voice_webhook_url() -> str:
    return legacy_answer_webhook_url()


def _normalize_remote_number(provider: str, item: Dict[str, Any]) -> Optional[str]:
    provider_key = provider.lower()
    if provider_key == "exotel":
        raw = item.get("PhoneNumber") or item.get("phone_number") or item.get("e164")
    else:
        raw = item.get("e164") or item.get("number") or item.get("phone_number")
    if not raw:
        return None
    try:
        return normalize_e164(str(raw))
    except ValueError:
        candidates = expand_phone_candidates(str(raw))
        return candidates[0] if candidates else None


def _imported_by_phone(db: Session, org_id: UUID) -> Dict[str, TelephonyPhoneNumber]:
    imported_rows = (
        db.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.organization_id == org_id,
            TelephonyPhoneNumber.is_active.is_(True),
        )
        .all()
    )
    return {row.phone_number: row for row in imported_rows}


def _resolve_integration_for_import(
    db: Session,
    org_id: UUID,
    provider: str,
    integration: Optional[TelephonyIntegration],
    *,
    credential_id: Optional[UUID] = None,
) -> Optional[UUID]:
    if integration:
        return integration.id
    if credential_id:
        row = (
            db.query(TelephonyIntegration)
            .filter(
                TelephonyIntegration.id == credential_id,
                TelephonyIntegration.organization_id == org_id,
                TelephonyIntegration.provider == provider,
                TelephonyIntegration.is_active.is_(True),
            )
            .first()
        )
        return row.id if row else None
    row = (
        db.query(TelephonyIntegration)
        .filter(
            TelephonyIntegration.organization_id == org_id,
            TelephonyIntegration.provider == provider,
            TelephonyIntegration.is_active.is_(True),
        )
        .order_by(TelephonyIntegration.is_default.desc())
        .first()
    )
    return row.id if row else None


def _build_provider_client(
    db: Session,
    org_id: UUID,
    provider: str,
    *,
    credential_id: Optional[UUID] = None,
) -> Tuple[Any, Optional[TelephonyIntegration]]:
    provider_key = _assert_import_provider(provider)
    if provider_key == TelephonyProvider.VOBIZ.value:
        return build_vobiz_client_for_org(db, org_id, credential_id=credential_id)

    integration = telephony_service.get_org_integration(
        org_id,
        db,
        provider=provider_key,
        credential_id=credential_id,
    )
    client = telephony_service.get_provider_client(
        org_id,
        db,
        provider=provider_key,
        credential_id=credential_id,
    )
    return client, integration


def _list_remote_numbers(
    provider: str,
    client: Any,
) -> List[Dict[str, Any]]:
    provider_key = provider.lower()
    if provider_key == TelephonyProvider.VOBIZ.value:
        return client.list_account_numbers()
    if provider_key == TelephonyProvider.PLIVO.value:
        return client.list_numbers()
    if provider_key == TelephonyProvider.EXOTEL.value:
        return client.list_incoming_phone_numbers()
    raise ValueError(f"Unsupported provider: {provider}")


def _normalize_country_iso2(
    raw: Optional[str],
    *,
    e164: Optional[str] = None,
) -> Optional[str]:
    """Normalize provider country values to ISO-3166 alpha-2 for storage."""
    value = (raw or "").strip()
    if not value:
        return _country_iso2_from_e164(e164)

    if len(value) == 2 and value.isalpha():
        return value.upper()

    mapped = _COUNTRY_NAME_TO_ISO2.get(value.lower())
    if mapped:
        return mapped

    return _country_iso2_from_e164(e164)


def _country_iso2_from_e164(e164: Optional[str]) -> Optional[str]:
    if not e164:
        return None
    digits = str(e164).strip().lstrip("+")
    if not digits.isdigit():
        return None
    for length in (3, 2, 1):
        prefix = digits[:length]
        iso2 = _CALLING_CODE_TO_ISO2.get(prefix)
        if iso2:
            return iso2
    return None


def _extract_application_id(value: Optional[str]) -> Optional[str]:
    """Extract a Plivo-style application id from a URI or raw id."""
    if not value:
        return None
    text = str(value).strip().rstrip("/")
    if "/Application/" in text:
        tail = text.rsplit("/Application/", 1)[-1]
        app_id = tail.split("/", 1)[0].strip()
        return app_id or None
    return text or None


_COUNTRY_NAME_TO_ISO2 = {
    "india": "IN",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "singapore": "SG",
}

_CALLING_CODE_TO_ISO2 = {
    "91": "IN",
    "1": "US",
    "44": "GB",
    "61": "AU",
    "49": "DE",
    "33": "FR",
    "65": "SG",
    "971": "AE",
}


def _remote_metadata(
    provider: str,
    item: Dict[str, Any],
    *,
    e164: Optional[str] = None,
) -> Dict[str, Any]:
    provider_key = provider.lower()
    if provider_key == TelephonyProvider.EXOTEL.value:
        raw_country = item.get("Country") or item.get("country")
        return {
            "provider_number_id": item.get("Sid") or item.get("sid"),
            "country": raw_country,
            "country_iso2": _normalize_country_iso2(raw_country, e164=e164),
            "region": item.get("Region") or item.get("region") or item.get("FriendlyName"),
            "capabilities": None,
            "status": item.get("Status") or item.get("status"),
            "application_id": item.get("VoiceUrl") or item.get("voice_url"),
        }
    raw_country = item.get("country") or item.get("Country")
    application_id = _extract_application_id(
        item.get("application_id")
        or item.get("app_id")
        or item.get("Application")
        or item.get("application")
    )
    return {
        "provider_number_id": item.get("id") or item.get("Sid") or item.get("sid"),
        "country": raw_country,
        "country_iso2": _normalize_country_iso2(raw_country, e164=e164),
        "region": item.get("region") or item.get("Region"),
        "capabilities": item.get("capabilities"),
        "status": item.get("status") or item.get("Status"),
        "application_id": application_id,
    }


def _answer_url_for_provider(provider: str) -> str:
    provider_key = provider.lower()
    if provider_key == TelephonyProvider.VOBIZ.value:
        return _vobiz_answer_webhook_url()
    if provider_key == TelephonyProvider.PLIVO.value:
        return _plivo_answer_webhook_url()
    if provider_key == TelephonyProvider.EXOTEL.value:
        return _exotel_voice_webhook_url()
    raise ValueError(f"Unsupported provider: {provider}")


def _configure_inbound_webhook(
    provider: str,
    client: Any,
    *,
    e164: str,
    answer_url: str,
    remote: Dict[str, Any],
    org_id: UUID,
) -> Tuple[bool, str, Optional[str]]:
    provider_key = provider.lower()
    if provider_key == TelephonyProvider.VOBIZ.value:
        return client.set_number_answer_url(
            e164,
            answer_url,
            existing_application_id=remote.get("application_id"),
            app_name=f"efficientai_{org_id.hex[:8]}",
        )
    if provider_key == TelephonyProvider.PLIVO.value:
        return client.set_number_answer_url(
            e164,
            answer_url,
            hangup_url=_plivo_hangup_webhook_url(),
            existing_application_id=remote.get("application_id")
            or remote.get("app_id")
            or remote.get("Application"),
            app_name=f"efficientai_{org_id.hex[:8]}",
        )
    if provider_key == TelephonyProvider.EXOTEL.value:
        sid = remote.get("Sid") or remote.get("sid") or remote.get("provider_number_id")
        if not sid:
            return False, "Missing Exotel incoming-number SID", None
        return client.set_number_voice_url(sid, answer_url)
    raise ValueError(f"Unsupported provider: {provider}")


def list_available_numbers(
    db: Session,
    org_id: UUID,
    provider: str,
    *,
    credential_id: Optional[UUID] = None,
) -> List[Dict[str, Any]]:
    """Return remote account numbers with import status for this org."""
    provider_key = _assert_import_provider(provider)
    client, _ = _build_provider_client(db, org_id, provider_key, credential_id=credential_id)
    remote_numbers = _list_remote_numbers(provider_key, client)
    imported_by_phone = _imported_by_phone(db, org_id)

    results: List[Dict[str, Any]] = []
    for item in remote_numbers:
        e164 = _normalize_remote_number(provider_key, item)
        if not e164:
            continue
        imported = imported_by_phone.get(e164)
        meta = _remote_metadata(provider_key, item, e164=e164)
        results.append(
            {
                "e164": e164,
                **meta,
                "already_imported": imported is not None,
                "imported_number_id": str(imported.id) if imported else None,
            }
        )
    return results


def import_numbers(
    db: Session,
    org_id: UUID,
    provider: str,
    *,
    numbers: List[str],
    agent_id: Optional[UUID] = None,
    credential_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Import one or more phone numbers for an organization."""
    provider_key = _assert_import_provider(provider)
    if not numbers:
        raise ValueError("At least one number is required")

    client, integration = _build_provider_client(
        db,
        org_id,
        provider_key,
        credential_id=credential_id,
    )
    integration_id = _resolve_integration_for_import(
        db,
        org_id,
        provider_key,
        integration,
        credential_id=credential_id,
    )

    remote_by_e164: Dict[str, Dict[str, Any]] = {}
    for item in _list_remote_numbers(provider_key, client):
        e164 = _normalize_remote_number(provider_key, item)
        if e164:
            enriched = dict(item)
            enriched.update(_remote_metadata(provider_key, item, e164=e164))
            remote_by_e164[e164] = enriched

    agent: Optional[Agent] = None
    if agent_id:
        agent = (
            db.query(Agent)
            .filter(Agent.id == agent_id, Agent.organization_id == org_id)
            .first()
        )
        if not agent:
            raise ValueError("Agent not found for organization")

    answer_url = _answer_url_for_provider(provider_key)
    results: List[Dict[str, Any]] = []
    linked_agent = False
    provider_label = provider_key.capitalize()

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
                    "message": f"Number not found on the connected {provider_label} account",
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
            row.country_iso2 = remote.get("country_iso2") or row.country_iso2
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
                country_iso2=remote.get("country_iso2"),
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

        webhook_ok, webhook_message, app_id = _configure_inbound_webhook(
            provider_key,
            client,
            e164=e164,
            answer_url=answer_url,
            remote=remote,
            org_id=org_id,
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
                "message": (
                    webhook_message
                    if webhook_ok
                    else f"Imported; configure inbound webhook manually: {webhook_message}"
                ),
                "answer_url": answer_url,
                "webhook_configured": webhook_ok,
                "imported_number_id": str(row.id),
                "application_id": app_id,
            }
        )
        logger.info(
            "Imported {} number {} for org {} (webhook_configured={})",
            provider_key,
            e164,
            org_id,
            webhook_ok,
        )

    return {"results": results, "answer_url": answer_url, "provider": provider_key}
