"""Credential resolver: decrypt failure fallthrough and Azure endpoint pinning."""

from uuid import uuid4

from app.core.encryption import encrypt_api_key
from app.models.database import AIProvider, Integration, ModelProvider
from app.services.credentials import resolver


def test_unpinned_aiprovider_decrypt_failure_falls_back_to_integration(
    db_session, org_id, seed_org, monkeypatch
):
    ai = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="elevenlabs",
        api_key="not-valid-ciphertext",
        name="Broken AIProvider",
        is_active=True,
        is_default=True,
    )
    integration = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform="elevenlabs",
        api_key=encrypt_api_key("integration-key"),
        name="ElevenLabs integration",
        is_active=True,
        is_default=True,
    )
    db_session.add_all([ai, integration])
    db_session.commit()

    def _decrypt(value):
        if value == ai.api_key:
            raise ValueError("bad ciphertext")
        return "integration-key"

    monkeypatch.setattr(resolver, "decrypt_api_key", _decrypt)

    key = resolver.resolve_decrypted_api_key_for_model_provider(
        ModelProvider.ELEVENLABS, db_session, org_id
    )
    assert key == "integration-key"


def test_pinned_aiprovider_decrypt_failure_does_not_fall_back(
    db_session, org_id, seed_org, monkeypatch
):
    ai = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="elevenlabs",
        api_key="not-valid-ciphertext",
        name="Pinned broken",
        is_active=True,
        is_default=False,
    )
    integration = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform="elevenlabs",
        api_key=encrypt_api_key("integration-key"),
        name="ElevenLabs integration",
        is_active=True,
        is_default=True,
    )
    db_session.add_all([ai, integration])
    db_session.commit()

    monkeypatch.setattr(
        resolver,
        "decrypt_api_key",
        lambda _value: (_ for _ in ()).throw(ValueError("bad ciphertext")),
    )

    key = resolver.resolve_decrypted_api_key_for_model_provider(
        ModelProvider.ELEVENLABS, db_session, org_id, credential_id=ai.id
    )
    assert key is None


def test_azure_endpoint_uses_pinned_credential_id(db_session, org_id, seed_org):
    default = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="azure",
        api_key=encrypt_api_key("default-key"),
        name="Azure default",
        endpoint_url="https://default.azure.com",
        is_active=True,
        is_default=True,
    )
    pinned = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="azure",
        api_key=encrypt_api_key("pinned-key"),
        name="Azure pinned",
        endpoint_url="https://pinned.azure.com",
        is_active=True,
        is_default=False,
    )
    db_session.add_all([default, pinned])
    db_session.commit()

    endpoint = resolver.resolve_azure_endpoint_for_model_provider(
        ModelProvider.AZURE, db_session, org_id, credential_id=pinned.id
    )
    assert endpoint == "https://pinned.azure.com"
