"""Tests for app.services.ai.llm_resolver Integration credential support."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.database import Integration
from app.models.enums import IntegrationPlatform, ModelProvider
from app.services.ai import llm_resolver


def _seed_sarvam_integration(db_session, org_id, *, is_default: bool = True):
    row = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform=IntegrationPlatform.SARVAM.value,
        name="Sarvam prod",
        api_key="enc-key",
        is_active=True,
        is_default=is_default,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_get_llm_provider_and_model_resolves_sarvam_from_integration(
    db_session, org_id
):
    _seed_sarvam_integration(db_session, org_id)

    provider_enum, model_str = llm_resolver.get_llm_provider_and_model(
        org_id,
        db_session,
        provider="sarvam",
        model=None,
    )

    assert provider_enum == ModelProvider.SARVAM
    assert model_str == "sarvam-30b"


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


def test_get_llm_provider_and_model_auto_detects_sarvam_integration(
    db_session, org_id
):
    _seed_sarvam_integration(db_session, org_id)

    provider_enum, model_str = llm_resolver.get_llm_provider_and_model(
        org_id,
        db_session,
        provider=None,
        model=None,
    )

    assert provider_enum == ModelProvider.SARVAM
    assert model_str == "sarvam-30b"


def test_get_llm_provider_and_model_raises_when_sarvam_integration_missing(
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
    assert "sarvam" in exc.value.detail.lower()
