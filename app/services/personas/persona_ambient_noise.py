"""Validation and normalization for persona ambient noise settings."""

from __future__ import annotations

from typing import Any, Optional

from app.core.usage_entitlement import has_enterprise_entitlement
from app.models.enums import BackgroundNoiseEnum, BackgroundNoiseSourceEnum
from app.services.audio.ambient_catalog import (
    get_ambient_asset_provider,
    normalize_ambient_preset,
)
from app.services.audio.ambient_mixer import (
    MAX_AMBIENT_VOLUME,
    MIN_AMBIENT_VOLUME,
    clamp_ambient_volume,
)

ALLOWED_AMBIENT_EXTENSIONS = {"wav", "mp3", "ogg", "m4a", "flac"}
MAX_AMBIENT_UPLOAD_BYTES = 10 * 1024 * 1024


def normalize_ambient_source(value: Optional[str]) -> str:
    if not value:
        return BackgroundNoiseSourceEnum.NONE.value
    normalized = str(value).strip().lower()
    try:
        return BackgroundNoiseSourceEnum(normalized).value
    except ValueError as exc:
        raise ValueError(
            f"background_noise_source must be one of: "
            f"{', '.join(s.value for s in BackgroundNoiseSourceEnum)}"
        ) from exc


def validate_ambient_preset(preset: Optional[str]) -> Optional[str]:
    normalized = normalize_ambient_preset(preset)
    if not normalized:
        raise ValueError("background_noise_preset is required for platform ambient source")
    known = {item.value for item in BackgroundNoiseEnum if item != BackgroundNoiseEnum.NONE}
    known.add(BackgroundNoiseEnum.TRAFFIC.value)
    provider_presets = set(get_ambient_asset_provider().list_presets())
    allowed = known | provider_presets
    if normalized not in allowed:
        raise ValueError(f"Unknown ambient preset: {normalized}")
    return normalized


def validate_persona_ambient_fields(
    *,
    source: Optional[str],
    preset: Optional[str],
    volume: Optional[float],
    s3_key: Optional[str],
    asset_id: Optional[Any] = None,
    organization_id: Any = None,
    workspace_id: Any = None,
    require_custom_file: bool = False,
    db=None,
) -> dict[str, Any]:
    normalized_source = normalize_ambient_source(source)
    normalized_volume = clamp_ambient_volume(volume)
    if normalized_volume < MIN_AMBIENT_VOLUME or normalized_volume > MAX_AMBIENT_VOLUME:
        raise ValueError(
            f"background_noise_volume must be between {MIN_AMBIENT_VOLUME} and {MAX_AMBIENT_VOLUME}"
        )

    normalized_preset = None
    resolved_asset_id = None
    if normalized_source == BackgroundNoiseSourceEnum.PLATFORM.value:
        normalized_preset = validate_ambient_preset(preset)
    elif preset:
        normalized_preset = normalize_ambient_preset(preset)

    if normalized_source == BackgroundNoiseSourceEnum.CUSTOM.value:
        if organization_id is not None and not has_enterprise_entitlement(organization_id):
            raise ValueError(
                "Custom ambient audio requires a valid EfficientAI Enterprise license"
            )
        resolved_asset_id = None
        if asset_id:
            if db is None:
                resolved_asset_id = asset_id
            else:
                if db is None:
                    raise ValueError("Internal error resolving ambient asset")
                from app.models.database import AmbientNoiseAsset

                query = db.query(AmbientNoiseAsset).filter(
                    AmbientNoiseAsset.id == asset_id,
                    AmbientNoiseAsset.organization_id == organization_id,
                )
                if workspace_id is not None:
                    query = query.filter(AmbientNoiseAsset.workspace_id == workspace_id)
                row = query.first()
                if not row:
                    raise ValueError("Selected ambient library asset was not found")
                resolved_asset_id = row.id
                s3_key = None
        elif require_custom_file and not s3_key:
            raise ValueError("Select an uploaded ambient bed or upload one in the Background Noise tab")
        if s3_key and not str(s3_key).strip():
            raise ValueError("background_noise_s3_key must not be empty")

    if normalized_source == BackgroundNoiseSourceEnum.NONE.value:
        return {
            "background_noise_source": BackgroundNoiseSourceEnum.NONE.value,
            "background_noise_preset": None,
            "background_noise_volume": normalized_volume,
            "background_noise_s3_key": None,
            "background_noise_asset_id": None,
        }

    return {
        "background_noise_source": normalized_source,
        "background_noise_preset": normalized_preset,
        "background_noise_volume": normalized_volume,
        "background_noise_s3_key": s3_key if normalized_source == BackgroundNoiseSourceEnum.CUSTOM.value and not asset_id else None,
        "background_noise_asset_id": resolved_asset_id if normalized_source == BackgroundNoiseSourceEnum.CUSTOM.value else None,
    }


def persona_ambient_s3_key(organization_id: Any, persona_id: Any, extension: str) -> str:
    from app.services.storage.s3_service import s3_service

    ext = extension.lower().lstrip(".")
    return (
        f"{s3_service.prefix}organizations/{organization_id}/personas/{persona_id}/ambient.{ext}"
    )
