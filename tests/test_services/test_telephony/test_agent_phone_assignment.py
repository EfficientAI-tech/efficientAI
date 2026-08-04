"""Tests for org-wide agent phone number assignment uniqueness."""

from uuid import uuid4

import pytest

from app.models.database import Agent, TelephonyPhoneNumber
from app.services.telephony.phone_routing import find_agent_phone_assignment_conflict


@pytest.fixture
def make_agent(db_session, org_id, default_workspace):
    counter = {"n": 0}

    def _make(**overrides):
        counter["n"] += 1
        agent = Agent(
            id=overrides.get("id", uuid4()),
            agent_id=overrides.get("agent_id", f"{counter['n']:06d}"),
            organization_id=org_id,
            workspace_id=overrides.get("workspace_id", default_workspace.id),
            name=overrides.get("name", "Agent A"),
            phone_number=overrides.get("phone_number", "+1234567890"),
            language=overrides.get("language", "en"),
            description=overrides.get("description", "Agent description"),
            call_type=overrides.get("call_type", "outbound"),
            call_medium=overrides.get("call_medium", "phone_call"),
            telephony_phone_number_id=overrides.get("telephony_phone_number_id"),
            voice_ai_agent_id=overrides.get("voice_ai_agent_id", "voice-agent-1"),
        )
        db_session.add(agent)
        db_session.commit()
        db_session.refresh(agent)
        return agent

    return _make


@pytest.fixture
def make_telephony_number(db_session, org_id):
    def _make(**overrides):
        number = TelephonyPhoneNumber(
            id=overrides.get("id", uuid4()),
            organization_id=org_id,
            phone_number=overrides.get("phone_number", "+919876543210"),
            is_active=True,
            inbound_enabled=True,
            outbound_enabled=True,
            source="imported",
            agent_id=overrides.get("agent_id"),
        )
        db_session.add(number)
        db_session.commit()
        db_session.refresh(number)
        return number

    return _make


def test_no_conflict_when_number_is_free(db_session, org_id, make_agent):
    make_agent(phone_number="+1111111111", name="Agent A")

    conflict = find_agent_phone_assignment_conflict(
        db_session,
        organization_id=org_id,
        phone_number="+2222222222",
    )

    assert conflict is None


def test_conflict_via_synced_number_agent_id(db_session, org_id, make_agent, make_telephony_number):
    agent = make_agent(phone_number="+919876543210", name="Inbound Agent")
    number = make_telephony_number(phone_number="+919876543210", agent_id=agent.id)

    conflict = find_agent_phone_assignment_conflict(
        db_session,
        organization_id=org_id,
        telephony_phone_number_id=number.id,
    )

    assert conflict is not None
    assert conflict["agent_id"] == agent.id
    assert conflict["agent_name"] == "Inbound Agent"


def test_conflict_via_custom_agent_phone_number(db_session, org_id, make_agent):
    agent = make_agent(phone_number="+13334445555", name="Custom Agent")

    conflict = find_agent_phone_assignment_conflict(
        db_session,
        organization_id=org_id,
        phone_number="+13334445555",
    )

    assert conflict is not None
    assert conflict["agent_id"] == agent.id
    assert conflict["agent_name"] == "Custom Agent"


def test_no_conflict_when_exclude_agent_matches_owner(db_session, org_id, make_agent):
    agent = make_agent(phone_number="+14445556666", name="Owner Agent")

    conflict = find_agent_phone_assignment_conflict(
        db_session,
        organization_id=org_id,
        phone_number="+14445556666",
        exclude_agent_id=agent.id,
    )

    assert conflict is None


def test_normalization_matches_variants(db_session, org_id, make_agent):
    make_agent(phone_number="+919876543210", name="India Agent")

    conflict = find_agent_phone_assignment_conflict(
        db_session,
        organization_id=org_id,
        phone_number="919876543210",
    )

    assert conflict is not None
    assert conflict["agent_name"] == "India Agent"


def test_telephony_not_found_returns_error_marker(db_session, org_id):
    conflict = find_agent_phone_assignment_conflict(
        db_session,
        organization_id=org_id,
        telephony_phone_number_id=uuid4(),
    )

    assert conflict == {"error": "telephony_not_found"}


def test_conflict_when_agent_linked_via_telephony_phone_number_id(
    db_session, org_id, make_agent, make_telephony_number
):
    number = make_telephony_number(phone_number="+15556667777")
    agent = make_agent(
        phone_number="+15556667777",
        name="Linked Agent",
        telephony_phone_number_id=number.id,
    )
    number.agent_id = agent.id
    db_session.commit()

    conflict = find_agent_phone_assignment_conflict(
        db_session,
        organization_id=org_id,
        phone_number="+15556667777",
    )

    assert conflict is not None
    assert conflict["agent_id"] == agent.id
