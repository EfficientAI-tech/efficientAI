"""OSS org member limit (solo user)."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core import oss_quotas as quotas_module
from app.models.database import OrganizationMember, RoleEnum, User


def test_enforce_org_member_quota_blocks_second_member(
    db_session, org_id, seed_org, monkeypatch
):
    monkeypatch.setattr(
        quotas_module,
        "has_enterprise_entitlement",
        lambda _org: False,
    )

    user = User(
        id=uuid4(),
        email="solo@example.com",
        name="Solo User",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=user.id,
            role=RoleEnum.ADMIN.value,
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        quotas_module.enforce_oss_quota(db_session, org_id, "org_members")

    assert exc.value.detail["resource"] == "org_members"
    assert exc.value.detail["limit"] == 1
    assert exc.value.detail["current"] == 1
