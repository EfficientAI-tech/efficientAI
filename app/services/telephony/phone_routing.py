"""Resolve inbound telephony numbers to agents and keep number↔agent links in sync."""

from __future__ import annotations

from typing import Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Agent, TelephonyPhoneNumber
from app.services.telephony.plivo_client import expand_phone_candidates, normalize_e164


def safe_normalize_phone(phone_number: Optional[str]) -> Optional[str]:
    """Best-effort E.164 normalization for provider webhook payloads."""
    candidates = expand_phone_candidates(phone_number)
    return candidates[0] if candidates else None


def _find_inbound_number_row(
    db: Session,
    candidates: list[str],
) -> Optional[TelephonyPhoneNumber]:
    return (
        db.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.phone_number.in_(candidates),
            TelephonyPhoneNumber.is_active.is_(True),
            TelephonyPhoneNumber.inbound_enabled.is_(True),
            TelephonyPhoneNumber.source != "platform_pool",
        )
        .first()
    )


def _resolve_agent_for_org(
    db: Session,
    organization_id: UUID,
    candidates: list[str],
    number_row: Optional[TelephonyPhoneNumber],
) -> Tuple[Optional[UUID], Optional[UUID]]:
    if number_row and number_row.agent_id:
        agent = (
            db.query(Agent)
            .filter(
                Agent.id == number_row.agent_id,
                Agent.organization_id == organization_id,
            )
            .first()
        )
        if agent:
            return agent.id, organization_id

    agent = (
        db.query(Agent)
        .filter(
            Agent.organization_id == organization_id,
            Agent.phone_number.in_(candidates),
            Agent.call_medium == "phone_call",
        )
        .first()
    )
    if agent:
        if number_row and number_row.agent_id != agent.id:
            number_row.agent_id = agent.id
            db.commit()
        return agent.id, organization_id

    linked_agent = (
        db.query(Agent)
        .join(
            TelephonyPhoneNumber,
            TelephonyPhoneNumber.id == Agent.telephony_phone_number_id,
        )
        .filter(
            Agent.organization_id == organization_id,
            TelephonyPhoneNumber.phone_number.in_(candidates),
            TelephonyPhoneNumber.is_active.is_(True),
            TelephonyPhoneNumber.inbound_enabled.is_(True),
        )
        .first()
    )
    if linked_agent:
        if number_row and number_row.agent_id != linked_agent.id:
            number_row.agent_id = linked_agent.id
            db.commit()
        return linked_agent.id, organization_id

    return None, None


def resolve_inbound_agent_for_number(
    db: Session,
    to_number_raw: Optional[str],
) -> Tuple[Optional[UUID], Optional[UUID]]:
    """Resolve (agent_id, organization_id) for an inbound called number."""
    candidates = expand_phone_candidates(to_number_raw)
    if not candidates:
        return None, None

    number_row = _find_inbound_number_row(db, candidates)
    if not number_row:
        logger.warning(
            "Inbound routing miss for To={} (candidates={})",
            to_number_raw,
            candidates,
        )
        return None, None

    agent_id, organization_id = _resolve_agent_for_org(
        db,
        number_row.organization_id,
        candidates,
        number_row,
    )
    if agent_id and organization_id:
        return agent_id, organization_id

    logger.warning(
        "Inbound number {} owned by org {} but no agent linked (candidates={})",
        number_row.phone_number,
        number_row.organization_id,
        candidates,
    )
    return None, None


def sync_agent_telephony_number_link(db: Session, agent: Agent) -> None:
    """Keep TelephonyPhoneNumber.agent_id aligned with Agent.telephony_phone_number_id."""
    if not agent or not agent.id:
        return

    if agent.phone_number:
        try:
            agent.phone_number = normalize_e164(agent.phone_number)
        except ValueError:
            pass

    previously_linked = (
        db.query(TelephonyPhoneNumber)
        .filter(
            TelephonyPhoneNumber.agent_id == agent.id,
            TelephonyPhoneNumber.id != agent.telephony_phone_number_id,
        )
        .all()
    )
    for row in previously_linked:
        row.agent_id = None

    if agent.telephony_phone_number_id:
        number = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.id == agent.telephony_phone_number_id,
                TelephonyPhoneNumber.organization_id == agent.organization_id,
            )
            .first()
        )
        if number:
            number.agent_id = agent.id
            if not agent.phone_number:
                agent.phone_number = number.phone_number

    db.commit()
