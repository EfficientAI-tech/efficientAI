"""Unit tests for ``app.services.credentials.resolver``.

The resolver is the single source of truth used by every runtime caller
(LLM service, transcription service, telephony service, WebRTC bridge).
We exercise the three precedence rules:

    1. Explicit ``credential_id`` (when valid) wins.
    2. Otherwise the row marked ``is_default`` is preferred.
    3. Otherwise the most recently updated active row is used.

We also cover the helper that clears stale ``is_default`` flags when a
new default is being promoted.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.database import (
    AIProvider,
    Integration,
    Organization,
    TelephonyIntegration,
)
from app.services.credentials.resolver import (
    clear_other_defaults,
    resolve_ai_provider,
    resolve_integration,
    resolve_telephony_integration,
)


@pytest.fixture
def org(db_session):
    organization = Organization(id=uuid4(), name="Resolver Org")
    db_session.add(organization)
    db_session.commit()
    return organization


def _make_ai_provider(db_session, org, *, name, is_default=False, is_active=True, age_minutes=0):
    row = AIProvider(
        id=uuid4(),
        organization_id=org.id,
        provider="openai",
        api_key="enc",
        name=name,
        is_active=is_active,
        is_default=is_default,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    if age_minutes:
        row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
        db_session.commit()
        db_session.refresh(row)
    return row


def test_resolve_ai_provider_prefers_default(db_session, org):
    older = _make_ai_provider(db_session, org, name="Older", age_minutes=30)
    default_row = _make_ai_provider(db_session, org, name="Default", is_default=True, age_minutes=60)

    resolved = resolve_ai_provider("openai", db_session, org.id)

    assert resolved is not None
    assert resolved.id == default_row.id
    assert resolved.id != older.id


def test_resolve_ai_provider_falls_back_to_most_recent_active_when_no_default(db_session, org):
    older = _make_ai_provider(db_session, org, name="Older", age_minutes=30)
    newer = _make_ai_provider(db_session, org, name="Newer", age_minutes=0)

    resolved = resolve_ai_provider("openai", db_session, org.id)

    assert resolved is not None
    assert resolved.id == newer.id
    assert resolved.id != older.id


def test_resolve_ai_provider_explicit_credential_id_wins(db_session, org):
    _default_row = _make_ai_provider(db_session, org, name="Default", is_default=True)
    other = _make_ai_provider(db_session, org, name="Other")

    resolved = resolve_ai_provider(
        "openai", db_session, org.id, credential_id=other.id
    )
    assert resolved is not None
    assert resolved.id == other.id

    # When an explicit credential_id is passed but doesn't match any row, the
    # resolver returns None - the caller is asking for that specific credential,
    # so silently substituting a different one would be surprising.
    bogus_id = uuid4()
    assert (
        resolve_ai_provider("openai", db_session, org.id, credential_id=bogus_id)
        is None
    )


def test_resolve_ai_provider_returns_none_when_no_credentials(db_session, org):
    assert resolve_ai_provider("openai", db_session, org.id) is None


def test_resolve_integration_prefers_default(db_session, org):
    older = Integration(
        id=uuid4(),
        organization_id=org.id,
        platform="retell",
        api_key="enc",
        name="Older",
        is_active=True,
        is_default=False,
    )
    default_row = Integration(
        id=uuid4(),
        organization_id=org.id,
        platform="retell",
        api_key="enc",
        name="Default",
        is_active=True,
        is_default=True,
    )
    db_session.add_all([older, default_row])
    db_session.commit()

    resolved = resolve_integration("retell", db_session, org.id)
    assert resolved is not None
    assert resolved.id == default_row.id


def test_resolve_telephony_integration_explicit_id(db_session, org):
    default_row = TelephonyIntegration(
        id=uuid4(),
        organization_id=org.id,
        provider="exotel",
        auth_id="enc",
        auth_token="enc",
        is_active=True,
        is_default=True,
    )
    secondary = TelephonyIntegration(
        id=uuid4(),
        organization_id=org.id,
        provider="exotel",
        auth_id="enc",
        auth_token="enc",
        is_active=True,
        is_default=False,
    )
    db_session.add_all([default_row, secondary])
    db_session.commit()

    resolved = resolve_telephony_integration(
        "exotel", db_session, org.id, credential_id=secondary.id
    )
    assert resolved is not None
    assert resolved.id == secondary.id


def test_clear_other_defaults_only_touches_matching_provider(db_session, org):
    keep = _make_ai_provider(db_session, org, name="Keep", is_default=True)
    other = _make_ai_provider(db_session, org, name="Other", is_default=True)

    clear_other_defaults(
        AIProvider,
        db_session,
        org.id,
        keep_id=keep.id,
        provider_field="provider",
        provider_value="openai",
    )
    db_session.commit()

    db_session.refresh(keep)
    db_session.refresh(other)
    assert keep.is_default is True
    assert other.is_default is False
