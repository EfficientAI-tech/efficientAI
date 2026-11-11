"""Credential resolution helpers shared by telephony, AI, and voice integrations.

Each helper returns a single row for ``(org, provider)`` using a consistent
priority: explicit ``credential_id`` -> ``is_default = TRUE`` -> most
recently updated active row. ``clear_other_defaults`` is used when promoting
a row so the partial unique index on ``is_default`` is never violated.
"""

from __future__ import annotations

from typing import Any, Optional, Type
from uuid import UUID

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import (
    AIProvider,
    Integration,
    IntegrationPlatform,
    ModelProvider,
    TelephonyIntegration,
)

_VOICE_INTEGRATION_PLATFORMS = {
    ModelProvider.DEEPGRAM: IntegrationPlatform.DEEPGRAM,
    ModelProvider.CARTESIA: IntegrationPlatform.CARTESIA,
    ModelProvider.ELEVENLABS: IntegrationPlatform.ELEVENLABS,
    ModelProvider.MURF: IntegrationPlatform.MURF,
    ModelProvider.SARVAM: IntegrationPlatform.SARVAM,
    ModelProvider.VOICEMAKER: IntegrationPlatform.VOICEMAKER,
    ModelProvider.SMALLEST: IntegrationPlatform.SMALLEST,
}


def _resolve_for_org_provider(
    model: Type[Any],
    *,
    db: Session,
    org_id: UUID,
    provider_field: str,
    provider_value: str,
    credential_id: Optional[UUID],
) -> Optional[Any]:
    base = db.query(model).filter(
        model.organization_id == org_id,
        model.is_active.is_(True),
    )

    if credential_id is not None:
        return base.filter(model.id == credential_id).first()

    column = getattr(model, provider_field)
    base = base.filter(func.lower(column) == provider_value.lower())

    default_row = base.filter(model.is_default.is_(True)).first()
    if default_row is not None:
        return default_row

    return base.order_by(
        desc(model.updated_at),
        desc(model.created_at),
    ).first()


def resolve_telephony_integration(
    provider: str,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[TelephonyIntegration]:
    """Resolve one ``TelephonyIntegration`` row for ``(org, provider)``."""
    return _resolve_for_org_provider(
        TelephonyIntegration,
        db=db,
        org_id=org_id,
        provider_field="provider",
        provider_value=provider,
        credential_id=credential_id,
    )


def resolve_integration(
    platform: str,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[Integration]:
    """Resolve one ``Integration`` row for ``(org, platform)``."""
    return _resolve_for_org_provider(
        Integration,
        db=db,
        org_id=org_id,
        provider_field="platform",
        provider_value=platform,
        credential_id=credential_id,
    )


def resolve_ai_provider(
    provider: str,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[AIProvider]:
    """Resolve one ``AIProvider`` row for ``(org, provider)``."""
    return _resolve_for_org_provider(
        AIProvider,
        db=db,
        org_id=org_id,
        provider_field="provider",
        provider_value=provider,
        credential_id=credential_id,
    )


class CredentialSnapshot:
    """Read-only copy of a resolved ``AIProvider`` / ``Integration`` row.

    Used by the LLM call path cache: every column attribute is present (so
    ``ai_provider.api_key`` / ``routing_mode`` / ``gateway_*`` reads work as
    on the ORM row), nothing lazy-loads, and assignments raise so a shared
    cached copy can never be mutated or flushed. ``api_key`` stays encrypted.
    """

    __slots__ = ("_values", "_kind")

    def __init__(self, kind: str, values: dict) -> None:
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_values", dict(values))

    @classmethod
    def from_row(cls, row: Any) -> Optional["CredentialSnapshot"]:
        if row is None:
            return None
        from sqlalchemy import inspect

        mapper = inspect(row).mapper
        values = {attr.key: getattr(row, attr.key) for attr in mapper.column_attrs}
        return cls(type(row).__name__, values)

    def __getattr__(self, name: str) -> Any:
        values = object.__getattribute__(self, "_values")
        if name in values:
            return values[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"CredentialSnapshot is read-only (tried to set {name})")

    def __repr__(self) -> str:
        return f"CredentialSnapshot({self._kind}, id={self._values.get('id')!r})"


def _provider_key(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _resolve_for_call(
    model: Type[Any],
    namespace: str,
    *,
    db: Session,
    org_id: UUID,
    provider_field: str,
    provider_value: Any,
    credential_id: Optional[UUID],
) -> Optional[CredentialSnapshot]:
    """Resolve once per LLM call, and from a per-process cache across calls.

    Cache key includes the org's LLM-config version, which is bumped on any
    committed credential/gateway change. When Redis is down the version is
    unknown and the row is read from the database (per call, not cached).
    """
    from app.services.ai.llm_call_scope import scoped
    from app.services.ai.llm_credential_version import (
        cache_ttl_seconds,
        read_llm_config_version,
    )
    from app.workers.catalog_cache import cached_catalog_fetch

    provider_key = _provider_key(provider_value)
    cred_key = str(credential_id) if credential_id is not None else "-"

    def _load() -> Optional[CredentialSnapshot]:
        return CredentialSnapshot.from_row(
            _resolve_for_org_provider(
                model,
                db=db,
                org_id=org_id,
                provider_field=provider_field,
                provider_value=provider_key,
                credential_id=credential_id,
            )
        )

    def _cached() -> Optional[CredentialSnapshot]:
        version = read_llm_config_version(org_id)
        if version is None:
            return _load()
        return cached_catalog_fetch(
            f"llmcfg_{namespace}",
            f"{org_id}:{version}:{provider_key}:{cred_key}",
            _load,
            ttl_seconds=cache_ttl_seconds(),
        )

    return scoped((namespace, str(org_id), provider_key, cred_key), _cached)


def resolve_ai_provider_for_call(
    provider: Any,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[CredentialSnapshot]:
    """LLM call path: cached, read-only ``AIProvider`` resolution."""
    return _resolve_for_call(
        AIProvider,
        "aip",
        db=db,
        org_id=org_id,
        provider_field="provider",
        provider_value=provider,
        credential_id=credential_id,
    )


def resolve_integration_for_call(
    platform: Any,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[CredentialSnapshot]:
    """LLM call path: cached, read-only ``Integration`` resolution."""
    return _resolve_for_call(
        Integration,
        "int",
        db=db,
        org_id=org_id,
        provider_field="platform",
        provider_value=platform,
        credential_id=credential_id,
    )


def resolve_azure_endpoint_for_model_provider(
    provider: ModelProvider,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[str]:
    """Resolve Azure OpenAI endpoint from the same AIProvider row as the LLM key."""
    from app.services.ai.llm_service import _resolve_azure_endpoint_from_provider

    provider_value = provider.value if hasattr(provider, "value") else str(provider)
    if str(provider_value).lower() != "azure":
        return None
    ai_provider_rec = resolve_ai_provider(
        provider_value, db, org_id, credential_id=credential_id
    )
    if not ai_provider_rec:
        return None
    return _resolve_azure_endpoint_from_provider(ai_provider_rec, None)


def resolve_decrypted_api_key_for_model_provider(
    provider: ModelProvider,
    db: Session,
    org_id: UUID,
    credential_id: Optional[UUID] = None,
) -> Optional[str]:
    """Decrypt API key for a voice/STT/TTS provider using shared credential priority."""
    provider_value = provider.value if hasattr(provider, "value") else str(provider)

    ai_provider_rec = resolve_ai_provider(
        provider_value, db, org_id, credential_id=credential_id
    )
    if ai_provider_rec:
        try:
            return decrypt_api_key(ai_provider_rec.api_key)
        except Exception:
            if credential_id is not None and ai_provider_rec.id == credential_id:
                return None

    plat = _VOICE_INTEGRATION_PLATFORMS.get(provider)
    if plat is None:
        return None
    plat_value = plat.value if hasattr(plat, "value") else str(plat)
    integ = resolve_integration(plat_value, db, org_id, credential_id=credential_id)
    if integ:
        try:
            return decrypt_api_key(integ.api_key)
        except Exception:
            if credential_id is not None and integ.id == credential_id:
                return None
            return None
    return None


def clear_other_defaults(
    model: Type[Any],
    db: Session,
    org_id: UUID,
    *,
    keep_id: UUID,
    provider_field: str,
    provider_value: str,
) -> None:
    """Set ``is_default = FALSE`` on every other row for ``(org, provider)``.

    Caller is expected to flip the kept row's ``is_default`` to ``TRUE``
    afterwards (and commit). Using ``synchronize_session=False`` keeps the
    bulk update cheap; identity-mapped rows already loaded into the session
    will be refreshed on the next access.
    """
    column = getattr(model, provider_field)
    db.query(model).filter(
        model.organization_id == org_id,
        func.lower(column) == provider_value.lower(),
        model.id != keep_id,
        model.is_default.is_(True),
    ).update({"is_default": False}, synchronize_session=False)
    # Bulk update bypasses the ORM hook; bump the org's LLM-config version
    # when this session commits so cached credential resolutions refresh.
    from app.services.ai.llm_credential_version import mark_llm_config_changed

    mark_llm_config_changed(db, org_id)
