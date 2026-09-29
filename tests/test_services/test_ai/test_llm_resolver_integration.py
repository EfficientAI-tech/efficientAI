"""Integration-style tests for llm_resolver with DB."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.encryption import encrypt_api_key
from app.models.database import AIProvider, Integration, Organization
from app.models.enums import IntegrationPlatform, ModelProvider
from app.services.ai import llm_resolver


@pytest.fixture
def org_id(db_session):
    org = Organization(id=uuid4(), name="Resolver Org")
    db_session.add(org)
    db_session.commit()
    return org.id


def _ensure_org(db_session, org_id):
    if db_session.get(Organization, org_id):
        return
    db_session.add(Organization(id=org_id, name="Resolver Org"))
    db_session.commit()


def _seed_sarvam_integration(db_session, org_id):
    _ensure_org(db_session, org_id)
    integration = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform=IntegrationPlatform.SARVAM.value,
        name="Sarvam",
        api_key=encrypt_api_key("sarvam-key"),
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    db_session.commit()
    return integration


def test_get_llm_provider_and_model_resolves_sarvam_from_integration(
    db_session, org_id
):
    _seed_sarvam_integration(db_session, org_id)

    provider_enum, model_str = llm_resolver.get_llm_provider_and_model(
        org_id,
        db_session,
        provider="sarvam",
        model="sarvam-105b",
    )

    assert provider_enum == ModelProvider.SARVAM
    assert model_str == "sarvam-105b"


def test_get_llm_provider_and_model_resolves_sarvam_by_integration_credential_id(
    db_session, org_id
):
    integration = _seed_sarvam_integration(db_session, org_id)

    provider_enum, model_str = llm_resolver.get_llm_provider_and_model(
        org_id,
        db_session,
        provider="sarvam",
        model="sarvam-105b",
        credential_id=integration.id,
    )

    assert provider_enum == ModelProvider.SARVAM
    assert model_str == "sarvam-105b"


def test_get_llm_provider_and_model_auto_detect_raises(db_session, org_id):
    _seed_sarvam_integration(db_session, org_id)

    with pytest.raises(HTTPException) as exc:
        llm_resolver.get_llm_provider_and_model(
            org_id,
            db_session,
            provider=None,
            model=None,
        )
    assert exc.value.status_code == 400


def test_get_llm_provider_and_model_raises_when_sarvam_integration_missing_model(
    db_session, org_id
):
    with pytest.raises(HTTPException) as exc:
        llm_resolver.get_llm_provider_and_model(
            org_id,
            db_session,
            provider="sarvam",
            model=None,
        )

    assert exc.value.status_code == 400
