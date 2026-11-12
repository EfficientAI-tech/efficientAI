"""Scope C: per-LLM-call catalog reads (credentials + org gateway settings).

Phase 1: one read per thing per call (``llm_call_scope``).
Phase 2: per-process cache keyed by the org's Redis LLM-config version.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis
from sqlalchemy import event

from app.core.encryption import encrypt_api_key
from app.models.database import AIProvider, ModelProvider, Organization
from app.services.ai import llm_credential_version as ver
from app.services.ai.llm_call_scope import llm_call_scope
from app.services.ai.llm_gateway import org_gateway_settings_for_call
from app.services.call_imports import eval_progress_buffer as buf
from app.services.credentials import (
    CredentialSnapshot,
    clear_other_defaults,
    resolve_ai_provider_for_call,
)

_TABLES = ("from organizations", "from aiproviders", "from integrations")


@pytest.fixture
def redis_ok():
    try:
        buf._client().ping()
    except redis.RedisError:
        pytest.skip("redis not reachable for llm config version tests")


@contextmanager
def count_statements(db_session, *tables: str):
    seen: list[str] = []
    bind = db_session.get_bind()
    engine = getattr(bind, "engine", bind)

    def _before(_conn, _cursor, statement, _params, _context, _many):
        lowered = statement.lower()
        if any(t in lowered for t in tables):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _org(db_session, *, settings=None) -> Organization:
    org = Organization(id=uuid4(), name="Scope C Org")
    if settings is not None:
        org.llm_gateway_settings = settings
    db_session.add(org)
    db_session.commit()
    return org


def _provider(db_session, org_id, *, key="sk-one", default=True, provider="openai"):
    row = AIProvider(
        id=uuid4(),
        organization_id=org_id,
        provider=provider,
        api_key=encrypt_api_key(key),
        name=f"{provider} key",
        is_active=True,
        is_default=default,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _decrypted(snapshot) -> str:
    from app.core.encryption import decrypt_api_key

    return decrypt_api_key(snapshot.api_key)


# --- Phase 1: per-call memo --------------------------------------------------------


def test_scope_reads_org_settings_once_per_call(db_session, monkeypatch):
    org = _org(db_session, settings={"routing_mode": "direct"})
    org_id = org.id
    monkeypatch.setattr(ver, "read_llm_config_version", lambda _org: None)  # no cache
    with count_statements(db_session, "from organizations") as seen:
        with llm_call_scope():
            for _ in range(3):  # key resolution, routing, gateway kwargs
                org_gateway_settings_for_call(org_id, db_session)
    assert len(seen) == 1


def test_scope_does_not_leak_between_calls(db_session, monkeypatch):
    org = _org(db_session)
    org_id = org.id
    monkeypatch.setattr(ver, "read_llm_config_version", lambda _org: None)
    with count_statements(db_session, "from organizations") as seen:
        with llm_call_scope():
            org_gateway_settings_for_call(org_id, db_session)
        with llm_call_scope():
            org_gateway_settings_for_call(org_id, db_session)
    assert len(seen) == 2


# --- Phase 2: cache keyed by version ----------------------------------------------------


def test_cached_across_calls_until_change(db_session, redis_ok):
    org = _org(db_session)
    row = _provider(db_session, org.id, key="sk-one")
    org_id, row_id = org.id, row.id

    with count_statements(db_session, *_TABLES) as seen:
        first = resolve_ai_provider_for_call("openai", db_session, org_id)
        second = resolve_ai_provider_for_call(ModelProvider.OPENAI, db_session, org_id)
        org_gateway_settings_for_call(org_id, db_session)
        org_gateway_settings_for_call(org_id, db_session)
    assert first.id == row_id and second.id == row_id
    assert len(seen) == 2  # one aiproviders + one organizations, ever

    # Key rotation is picked up on the very next call.
    row.api_key = encrypt_api_key("sk-rotated")
    db_session.commit()
    assert _decrypted(resolve_ai_provider_for_call("openai", db_session, org_id)) == "sk-rotated"


def test_deactivated_credential_is_not_served_from_cache(db_session, redis_ok):
    org = _org(db_session)
    row = _provider(db_session, org.id)
    org_id = org.id
    assert resolve_ai_provider_for_call("openai", db_session, org_id) is not None

    row.is_active = False
    db_session.commit()
    assert resolve_ai_provider_for_call("openai", db_session, org_id) is None


def test_deleted_credential_is_not_served_from_cache(db_session, redis_ok):
    org = _org(db_session)
    row = _provider(db_session, org.id)
    org_id = org.id
    assert resolve_ai_provider_for_call("openai", db_session, org_id) is not None

    db_session.delete(row)
    db_session.commit()
    assert resolve_ai_provider_for_call("openai", db_session, org_id) is None


def test_default_switch_via_bulk_clear_is_picked_up(db_session, redis_ok):
    org = _org(db_session)
    old = _provider(db_session, org.id, key="sk-old", default=True)
    new = _provider(db_session, org.id, key="sk-new", default=False)
    org_id, new_id = org.id, new.id
    assert resolve_ai_provider_for_call("openai", db_session, org_id).id == old.id

    clear_other_defaults(
        AIProvider,
        db_session,
        org_id,
        keep_id=new_id,
        provider_field="provider",
        provider_value="openai",
    )
    new.is_default = True
    db_session.commit()
    assert resolve_ai_provider_for_call("openai", db_session, org_id).id == new_id


def test_bulk_update_alone_bumps_version(db_session, redis_ok):
    org = _org(db_session)
    _provider(db_session, org.id)
    org_id = org.id
    start = ver.read_llm_config_version(org_id)
    clear_other_defaults(
        AIProvider,
        db_session,
        org_id,
        keep_id=uuid4(),
        provider_field="provider",
        provider_value="openai",
    )
    db_session.commit()
    assert ver.read_llm_config_version(org_id) == start + 1


def test_gateway_settings_change_is_picked_up(db_session, redis_ok):
    org = _org(db_session, settings={"routing_mode": "direct"})
    org_id = org.id
    assert org_gateway_settings_for_call(org_id, db_session)["routing_mode"] == "direct"

    org.llm_gateway_settings = {"routing_mode": "gateway"}
    db_session.commit()
    assert org_gateway_settings_for_call(org_id, db_session)["routing_mode"] == "gateway"


def test_unrelated_org_change_does_not_bump(db_session, redis_ok):
    org = _org(db_session)
    start = ver.read_llm_config_version(org.id)
    org.name = "Renamed"
    db_session.commit()
    assert ver.read_llm_config_version(org.id) == start


def test_rollback_does_not_bump(db_session, redis_ok):
    org = _org(db_session)
    row = _provider(db_session, org.id)
    org_id = org.id
    start = ver.read_llm_config_version(org_id)
    row.api_key = encrypt_api_key("never-committed")
    db_session.flush()
    db_session.rollback()
    assert ver.read_llm_config_version(org_id) == start


def test_redis_down_reads_database_every_call(db_session, monkeypatch):
    org = _org(db_session)
    _provider(db_session, org.id)
    org_id = org.id
    monkeypatch.setattr(ver, "read_llm_config_version", lambda _org: None)
    with count_statements(db_session, "from aiproviders") as seen:
        resolve_ai_provider_for_call("openai", db_session, org_id)
        resolve_ai_provider_for_call("openai", db_session, org_id)
    assert len(seen) == 2


def test_snapshot_is_read_only_and_settings_are_copied(db_session, redis_ok):
    org = _org(db_session, settings={"routing_mode": "direct", "extra": {"a": 1}})
    _provider(db_session, org.id)
    org_id = org.id
    snap = resolve_ai_provider_for_call("openai", db_session, org_id)
    assert isinstance(snap, CredentialSnapshot)
    with pytest.raises(AttributeError):
        snap.api_key = "x"

    one = org_gateway_settings_for_call(org_id, db_session)
    one["extra"]["a"] = 99
    assert org_gateway_settings_for_call(org_id, db_session)["extra"] == {"a": 1}


def test_pinned_credential_from_another_org_is_rejected(db_session, redis_ok):
    owner = _org(db_session)
    other = _org(db_session)
    row = _provider(db_session, owner.id)
    assert (
        resolve_ai_provider_for_call("openai", db_session, other.id, credential_id=row.id)
        is None
    )


# --- end to end: generate_response --------------------------------------------------------


def test_second_llm_call_issues_no_credential_or_org_reads(db_session, monkeypatch, redis_ok):
    llm_module = sys.modules["app.services.ai.llm_service"]
    org = _org(db_session)
    _provider(db_session, org.id, key="sk-live")
    org_id = org.id
    sent_keys: list[str] = []

    def _completion(**kwargs):
        sent_keys.append(kwargs.get("api_key"))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(llm_module.litellm, "completion", _completion)
    service = llm_module.LLMService()

    def _call():
        return service.generate_response(
            messages=[{"role": "user", "content": "hi"}],
            llm_provider=ModelProvider.OPENAI,
            llm_model="gpt-4o-mini",
            organization_id=org_id,
            db=db_session,
        )

    with count_statements(db_session, *_TABLES) as first_seen:
        assert _call()["text"] == "ok"
    with count_statements(db_session, *_TABLES) as second_seen:
        assert _call()["text"] == "ok"

    assert 1 <= len(first_seen) <= 2, first_seen  # was ~4 (3x organizations + aiproviders)
    assert second_seen == [], second_seen
    assert sent_keys == ["sk-live", "sk-live"]


# --- per-row diarisation / STT lookups ---------------------------------------------------


def test_audio_diariser_lookups_hit_catalog_once(db_session, redis_ok):
    from app.workers.tasks.helpers import llm_diarisation

    org = _org(db_session)
    row = _provider(db_session, org.id, key="sk-custom", provider="custom")
    row.gateway_model = "prod-gpt4o-audio"
    _provider(db_session, org.id, key="sk-google", provider="google")
    db_session.commit()
    org_id = org.id

    def _row_lookups():
        # The per-row reads in diarize_audio_with_llm: custom-gateway check
        # and the Gemini Files API key.
        assert llm_diarisation._custom_gateway_audio_allowed(
            provider_value="custom", organization_id=org_id, db=db_session
        )
        assert (
            llm_diarisation._resolve_provider_api_key(
                ModelProvider.GOOGLE, organization_id=org_id, db=db_session
            )
            == "sk-google"
        )

    with count_statements(db_session, "from aiproviders") as first:
        _row_lookups()
    with count_statements(db_session, "from aiproviders") as second:
        _row_lookups()
    assert len(first) == 2
    assert second == []


def test_stt_key_lookup_hits_catalog_once(db_session, redis_ok):
    import sys

    stt_module = sys.modules.get("app.services.ai.transcription_service")
    if stt_module is None:
        import importlib

        stt_module = importlib.import_module("app.services.ai.transcription_service")
    org = _org(db_session)
    _provider(db_session, org.id, key="sk-whisper", provider="openai")
    org_id = org.id
    service = stt_module.TranscriptionService()

    with count_statements(db_session, *_TABLES) as first:
        assert service._get_api_key_for_provider(ModelProvider.OPENAI, db_session, org_id) == "sk-whisper"
    with count_statements(db_session, *_TABLES) as second:
        assert service._get_api_key_for_provider(ModelProvider.OPENAI, db_session, org_id) == "sk-whisper"
    assert 1 <= len(first) <= 2
    assert second == []


def test_audio_diariser_has_no_debug_file_logging():
    import inspect

    from app.workers.tasks.helpers import llm_diarisation

    assert not hasattr(llm_diarisation, "_DEBUG_LOG_PATH")
    source = inspect.getsource(llm_diarisation.diarize_audio_with_llm)
    assert "#region agent log" not in source
