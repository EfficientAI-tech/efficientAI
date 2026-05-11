"""API tests for the per-leg ``*_credential_id`` fields on voice bundles.

VoiceBundle now carries optional ``stt_credential_id``, ``llm_credential_id``,
``tts_credential_id`` and ``s2s_credential_id`` so that an organization
that has multiple credentials configured for the same provider can pin a
specific one to a given bundle. The route validates that the supplied
credential belongs to the org and matches the chosen provider.
"""

from uuid import uuid4

from app.models.database import AIProvider, Integration


def _bundle_payload(**overrides):
    payload = {
        "name": "Test Bundle",
        "bundle_type": "stt_llm_tts",
        "stt_provider": "openai",
        "stt_model": "whisper-1",
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "tts_provider": "openai",
        "tts_model": "tts-1",
    }
    payload.update(overrides)
    return payload


def test_create_voice_bundle_with_explicit_aiprovider_credential(
    authenticated_client, db_session, org_id
):
    primary = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="openai",
        api_key="enc",
        name="Primary",
        is_active=True,
        is_default=True,
    )
    secondary = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="openai",
        api_key="enc",
        name="Backup",
        is_active=True,
        is_default=False,
    )
    db_session.add_all([primary, secondary])
    db_session.commit()

    payload = _bundle_payload(llm_credential_id=str(secondary.id))
    response = authenticated_client.post("/api/v1/voicebundles", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["llm_credential_id"] == str(secondary.id)
    # Other credential ids stay null when omitted.
    assert body["stt_credential_id"] is None
    assert body["tts_credential_id"] is None


def test_create_voice_bundle_rejects_credential_for_other_provider(
    authenticated_client, db_session, org_id
):
    """An OpenAI credential id cannot be pinned to a non-OpenAI leg."""
    openai_row = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="openai",
        api_key="enc",
        name="OpenAI",
        is_active=True,
        is_default=True,
    )
    db_session.add(openai_row)
    db_session.commit()

    payload = _bundle_payload(
        llm_provider="anthropic",
        llm_model="claude-3-haiku",
        llm_credential_id=str(openai_row.id),
    )
    response = authenticated_client.post("/api/v1/voicebundles", json=payload)
    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


def test_create_voice_bundle_rejects_unknown_credential_id(authenticated_client):
    payload = _bundle_payload(llm_credential_id=str(uuid4()))
    response = authenticated_client.post("/api/v1/voicebundles", json=payload)
    assert response.status_code == 400
    assert "does not match any credential" in response.json()["detail"]


def test_create_voice_bundle_with_voice_integration_credential(
    authenticated_client, db_session, org_id
):
    """Voice integrations (e.g. ElevenLabs/Deepgram) live in ``integrations``;
    the validator checks both tables."""
    integration_row = Integration(
        id=uuid4(),
        organization_id=org_id,
        platform="elevenlabs",
        api_key="enc",
        name="ElevenLabs Primary",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration_row)
    db_session.commit()

    payload = _bundle_payload(
        tts_provider="elevenlabs",
        tts_model="eleven_turbo_v2",
        tts_credential_id=str(integration_row.id),
    )
    response = authenticated_client.post("/api/v1/voicebundles", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["tts_credential_id"] == str(integration_row.id)


def test_credential_id_without_provider_is_rejected(authenticated_client, db_session, org_id):
    row = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider="openai",
        api_key="enc",
        name="OpenAI",
        is_active=True,
        is_default=True,
    )
    db_session.add(row)
    db_session.commit()

    payload = _bundle_payload(llm_provider=None, llm_credential_id=str(row.id))
    response = authenticated_client.post("/api/v1/voicebundles", json=payload)
    assert response.status_code in (400, 422)
