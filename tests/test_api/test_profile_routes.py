"""API tests for profile routes.

Covers the basic profile read/update endpoints plus the invitation
accept/decline flow that powers the team management UX.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.database import (
    Invitation,
    InvitationStatus,
    Organization,
    OrganizationMember,
    RoleEnum,
)


def test_get_and_update_profile(authenticated_client, user_context):
    get_response = authenticated_client.get("/api/v1/profile")
    assert get_response.status_code == 200
    assert get_response.json()["email"] == user_context["user"].email

    update_response = authenticated_client.put(
        "/api/v1/profile",
        json={"name": "Updated Owner", "first_name": "Updated", "last_name": "User"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Owner"


def test_get_and_update_preferences(authenticated_client, user_context, make_agent):
    agent = make_agent()

    get_response = authenticated_client.get("/api/v1/profile/preferences")
    assert get_response.status_code == 200
    assert get_response.json()["default_agent_id"] is None

    update_response = authenticated_client.put(
        "/api/v1/profile/preferences",
        json={"default_agent_id": str(agent.id)},
    )
    assert update_response.status_code == 200
    assert update_response.json()["default_agent_id"] == str(agent.id)


# ---------------------------------------------------------------------------
# Invitation accept / decline flow
# ---------------------------------------------------------------------------

def _make_invitation(
    db_session,
    *,
    email,
    invited_by_id,
    organization_id,
    role=RoleEnum.WRITER.value,
    status=InvitationStatus.PENDING.value,
    expires_in_days=7,
):
    invitation = Invitation(
        id=uuid4(),
        organization_id=organization_id,
        invited_by_id=invited_by_id,
        email=email,
        role=role,
        status=status,
        token=f"tok-{uuid4()}",
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
    )
    db_session.add(invitation)
    db_session.commit()
    db_session.refresh(invitation)
    return invitation


def test_list_invitations_returns_pending_invites_for_my_email(
    authenticated_client, user_context, db_session
):
    other_org = Organization(id=uuid4(), name="Other Org")
    db_session.add(other_org)
    db_session.commit()

    invitation = _make_invitation(
        db_session,
        email=user_context["user"].email,
        invited_by_id=user_context["user"].id,
        organization_id=other_org.id,
    )
    # Unrelated invite that should not appear.
    _make_invitation(
        db_session,
        email="someone-else@example.com",
        invited_by_id=user_context["user"].id,
        organization_id=other_org.id,
    )

    response = authenticated_client.get("/api/v1/profile/invitations")

    assert response.status_code == 200
    body = response.json()
    ids = [row["id"] for row in body]
    assert str(invitation.id) in ids
    assert all(row["email"] == user_context["user"].email for row in body)


def test_accept_pending_invitation_creates_membership(
    authenticated_client, user_context, db_session
):
    target_org = Organization(id=uuid4(), name="Invited Org")
    db_session.add(target_org)
    db_session.commit()

    invitation = _make_invitation(
        db_session,
        email=user_context["user"].email,
        invited_by_id=user_context["user"].id,
        organization_id=target_org.id,
        role=RoleEnum.WRITER.value,
    )

    response = authenticated_client.post(
        f"/api/v1/profile/invitations/{invitation.id}/accept"
    )

    assert response.status_code == 200
    db_session.refresh(invitation)
    assert invitation.status == InvitationStatus.ACCEPTED.value or invitation.status == InvitationStatus.ACCEPTED
    assert invitation.accepted_at is not None
    assert invitation.invited_user_id == user_context["user"].id

    membership = (
        db_session.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == target_org.id,
            OrganizationMember.user_id == user_context["user"].id,
        )
        .first()
    )
    assert membership is not None
    assert (
        membership.role == RoleEnum.WRITER.value
        or membership.role == RoleEnum.WRITER
    )


def test_accept_expired_invitation_returns_400(
    authenticated_client, user_context, db_session
):
    target_org = Organization(id=uuid4(), name="Stale Org")
    db_session.add(target_org)
    db_session.commit()

    invitation = _make_invitation(
        db_session,
        email=user_context["user"].email,
        invited_by_id=user_context["user"].id,
        organization_id=target_org.id,
        expires_in_days=-1,
    )

    response = authenticated_client.post(
        f"/api/v1/profile/invitations/{invitation.id}/accept"
    )

    assert response.status_code == 400
    assert "expired" in response.json()["detail"].lower()


def test_accept_already_accepted_invitation_returns_400(
    authenticated_client, user_context, db_session
):
    target_org = Organization(id=uuid4(), name="Already-Accepted Org")
    db_session.add(target_org)
    db_session.commit()

    invitation = _make_invitation(
        db_session,
        email=user_context["user"].email,
        invited_by_id=user_context["user"].id,
        organization_id=target_org.id,
        status=InvitationStatus.ACCEPTED.value,
    )

    response = authenticated_client.post(
        f"/api/v1/profile/invitations/{invitation.id}/accept"
    )

    assert response.status_code == 400


def test_decline_pending_invitation_sets_status_declined(
    authenticated_client, user_context, db_session
):
    target_org = Organization(id=uuid4(), name="Reject Org")
    db_session.add(target_org)
    db_session.commit()

    invitation = _make_invitation(
        db_session,
        email=user_context["user"].email,
        invited_by_id=user_context["user"].id,
        organization_id=target_org.id,
    )

    response = authenticated_client.post(
        f"/api/v1/profile/invitations/{invitation.id}/decline"
    )

    assert response.status_code == 200

    db_session.refresh(invitation)
    assert (
        invitation.status == InvitationStatus.DECLINED.value
        or invitation.status == InvitationStatus.DECLINED
    )
    # Decline must NOT create a membership.
    membership = (
        db_session.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == target_org.id,
            OrganizationMember.user_id == user_context["user"].id,
        )
        .first()
    )
    assert membership is None
