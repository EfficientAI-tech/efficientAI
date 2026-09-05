"""Tests for ``app.services.ai.llm_resolver``."""

from uuid import uuid4

import pytest

from app.core.encryption import encrypt_api_key
from app.models.database import AIProvider, Organization
from app.models.enums import ModelProvider
from app.services.ai.llm_gateway import GATEWAY_MANAGED_KEY_SENTINEL
from app.services.ai.llm_resolver import get_llm_provider_and_model


@pytest.fixture
def org(db_session):
    organization = Organization(id=uuid4(), name="LLM Resolver Org")
    db_session.add(organization)
    db_session.commit()
    return organization


def _make_provider(
    db_session,
    org,
    *,
    provider="custom",
    routing_mode="gateway",
    gateway_model="openai/gpt-4.1",
    gateway_interface="native_openai",
    gateway_base_url="http://localhost:8080",
    is_default=True,
):
    row = AIProvider(
        id=uuid4(),
        organization_id=org.id,
        provider=provider,
        api_key=encrypt_api_key(GATEWAY_MANAGED_KEY_SENTINEL),
        name="Gateway credential",
        is_active=True,
        is_default=is_default,
        routing_mode=routing_mode,
        gateway_model=gateway_model,
        gateway_interface=gateway_interface,
        gateway_base_url=gateway_base_url,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_provider_without_model_uses_gateway_model(db_session, org):
    _make_provider(db_session, org)

    provider_enum, model_str = get_llm_provider_and_model(
        org.id, db_session, provider="custom", model=None
    )

    assert provider_enum == ModelProvider.CUSTOM
    assert model_str == "openai/gpt-4.1"


def test_auto_detect_prefers_default_custom_gateway_credential(db_session, org):
    _make_provider(db_session, org, is_default=True)

    provider_enum, model_str = get_llm_provider_and_model(
        org.id, db_session, provider=None, model=None
    )

    assert provider_enum == ModelProvider.CUSTOM
    assert model_str == "openai/gpt-4.1"


def test_credential_id_pins_specific_gateway_model(db_session, org):
    default_row = _make_provider(
        db_session,
        org,
        gateway_model="openai/gpt-4.1",
        is_default=True,
    )
    pinned = _make_provider(
        db_session,
        org,
        gateway_model="openai/gpt-5.5",
        is_default=False,
    )
    assert default_row.id != pinned.id

    provider_enum, model_str = get_llm_provider_and_model(
        org.id,
        db_session,
        provider="custom",
        model=None,
        credential_id=pinned.id,
    )

    assert provider_enum == ModelProvider.CUSTOM
    assert model_str == "openai/gpt-5.5"


def test_provider_without_model_does_not_fall_back_to_openai(db_session, org):
    _make_provider(db_session, org, is_default=True)
    openai_row = AIProvider(
        id=uuid4(),
        organization_id=org.id,
        provider="openai",
        api_key=encrypt_api_key("sk-test"),
        name="OpenAI direct",
        is_active=True,
        is_default=True,
        routing_mode="direct",
    )
    db_session.add(openai_row)
    db_session.commit()

    provider_enum, model_str = get_llm_provider_and_model(
        org.id, db_session, provider="custom", model=""
    )

    assert provider_enum == ModelProvider.CUSTOM
    assert model_str == "openai/gpt-4.1"


def test_auto_detect_fireworks_uses_provider_default_not_openai(db_session, org):
    fireworks_row = AIProvider(
        id=uuid4(),
        organization_id=org.id,
        provider="fireworks",
        api_key=encrypt_api_key("fw-test"),
        name="Fireworks direct",
        is_active=True,
        is_default=True,
        routing_mode="direct",
    )
    db_session.add(fireworks_row)
    db_session.commit()

    provider_enum, model_str = get_llm_provider_and_model(
        org.id, db_session, provider=None, model=None
    )

    assert provider_enum == ModelProvider.FIREWORKS
    assert model_str == "gpt-oss-20b"
