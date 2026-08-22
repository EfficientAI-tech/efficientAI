"""Pluggable ambient asset catalog and persona resolution."""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from loguru import logger

from app.models.enums import BackgroundNoiseEnum, BackgroundNoiseSourceEnum
from app.services.audio.ambient_mixer import AmbientMixer, clamp_ambient_volume

PRESET_DISPLAY_NAMES = {
    BackgroundNoiseEnum.CAFE.value: "Cafe",
    BackgroundNoiseEnum.TRAFFIC.value: "Traffic",
    BackgroundNoiseEnum.STREET.value: "Street traffic",
    BackgroundNoiseEnum.CONCERT.value: "Concert crowd",
    BackgroundNoiseEnum.OFFICE.value: "Office",
    BackgroundNoiseEnum.HOME.value: "Home",
    BackgroundNoiseEnum.CALL_CENTER.value: "Call center",
}


def normalize_ambient_preset(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    value = str(name).strip().lower()
    if value == BackgroundNoiseEnum.NONE.value:
        return None
    if value == BackgroundNoiseEnum.STREET.value:
        return BackgroundNoiseEnum.TRAFFIC.value
    return value


@runtime_checkable
class AmbientAssetProvider(Protocol):
    def list_presets(self) -> list[str]:
        ...

    def load_wav(self, name: str) -> bytes:
        ...


class EmptyAmbientAssetProvider:
    def list_presets(self) -> list[str]:
        return []

    def load_wav(self, name: str) -> bytes:
        raise FileNotFoundError(name)


class DirectoryAmbientAssetProvider:
    """Load preset WAV/MP3/OGG files from EFFICIENTAI_AMBIENT_DIR."""

    def __init__(self, directory: Optional[str] = None):
        self._directory = Path(directory or os.getenv("EFFICIENTAI_AMBIENT_DIR", "")).expanduser()

    def list_presets(self) -> list[str]:
        if not self._directory.is_dir():
            return []
        names: list[str] = []
        for path in sorted(self._directory.iterdir()):
            if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".ogg", ".m4a", ".flac"}:
                names.append(path.stem.lower())
        return names

    def load_wav(self, name: str) -> bytes:
        normalized = normalize_ambient_preset(name) or name
        if not self._directory.is_dir():
            raise FileNotFoundError(normalized)
        for ext in (".wav", ".mp3", ".ogg", ".m4a", ".flac"):
            candidate = self._directory / f"{normalized}{ext}"
            if candidate.is_file():
                return candidate.read_bytes()
        raise FileNotFoundError(normalized)


class EntryPointAmbientAssetProvider:
    """Load presets from efficientai.ambient_assets entry points."""

    GROUP = "efficientai.ambient_assets"

    def __init__(self):
        self._provider: Optional[AmbientAssetProvider] = None
        self._loaded = False

    def _ensure_provider(self) -> Optional[AmbientAssetProvider]:
        if self._loaded:
            return self._provider
        self._loaded = True
        try:
            eps = metadata.entry_points(group=self.GROUP)
        except TypeError:
            eps = metadata.entry_points().get(self.GROUP, [])
        for ep in eps:
            try:
                provider = ep.load()
                if hasattr(provider, "list_presets") and hasattr(provider, "load_wav"):
                    self._provider = provider
                    logger.info("Loaded ambient asset provider from entry point {}", ep.name)
                    break
            except Exception as exc:
                logger.warning("Failed to load ambient asset entry point {}: {}", ep.name, exc)
        return self._provider

    def list_presets(self) -> list[str]:
        provider = self._ensure_provider()
        return provider.list_presets() if provider else []

    def load_wav(self, name: str) -> bytes:
        provider = self._ensure_provider()
        if not provider:
            raise FileNotFoundError(name)
        return provider.load_wav(name)


class ChainedAmbientAssetProvider:
    def __init__(self, providers: list[AmbientAssetProvider]):
        self._providers = providers

    def list_presets(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for provider in self._providers:
            for preset in provider.list_presets():
                normalized = normalize_ambient_preset(preset) or preset
                if normalized not in seen:
                    seen.add(normalized)
                    ordered.append(normalized)
        return ordered

    def load_wav(self, name: str) -> bytes:
        normalized = normalize_ambient_preset(name) or name
        last_error: Optional[Exception] = None
        for provider in self._providers:
            try:
                return provider.load_wav(normalized)
            except FileNotFoundError as exc:
                last_error = exc
        raise FileNotFoundError(normalized) from last_error


_default_provider: Optional[ChainedAmbientAssetProvider] = None


def get_ambient_asset_provider() -> ChainedAmbientAssetProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = ChainedAmbientAssetProvider(
            [
                EntryPointAmbientAssetProvider(),
                DirectoryAmbientAssetProvider(),
                EmptyAmbientAssetProvider(),
            ]
        )
    return _default_provider


def list_ambient_presets() -> list[dict[str, str]]:
    provider = get_ambient_asset_provider()
    return [
        {
            "id": preset,
            "label": PRESET_DISPLAY_NAMES.get(preset, preset.replace("_", " ").title()),
        }
        for preset in provider.list_presets()
    ]


def persona_ambient_source(persona: Any) -> str:
    source = getattr(persona, "background_noise_source", None) or BackgroundNoiseSourceEnum.NONE.value
    return str(source).strip().lower() or BackgroundNoiseSourceEnum.NONE.value


def persona_ambient_volume(persona: Any) -> float:
    return clamp_ambient_volume(getattr(persona, "background_noise_volume", None))


def persona_has_active_ambient(persona: Any) -> bool:
    return persona_ambient_source(persona) != BackgroundNoiseSourceEnum.NONE.value


def _resolve_custom_ambient_s3_key(persona: Any) -> Optional[str]:
    asset_id = getattr(persona, "background_noise_asset_id", None)
    if asset_id:
        try:
            from app.database import SessionLocal
            from app.models.database import AmbientNoiseAsset

            db = SessionLocal()
            try:
                row = db.query(AmbientNoiseAsset).filter(AmbientNoiseAsset.id == asset_id).first()
                if row and row.s3_key:
                    return str(row.s3_key)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Failed to resolve ambient asset {}: {}", asset_id, exc)
    legacy_key = getattr(persona, "background_noise_s3_key", None)
    return str(legacy_key) if legacy_key else None


async def resolve_ambient_mixer(persona: Any, sample_rate: int) -> Optional[AmbientMixer]:
    """Build an AmbientMixer for a persona at the given sample rate, or None."""
    source = persona_ambient_source(persona)
    volume = persona_ambient_volume(persona)

    if source == BackgroundNoiseSourceEnum.NONE.value:
        return None

    if source == BackgroundNoiseSourceEnum.PLATFORM.value:
        preset = normalize_ambient_preset(getattr(persona, "background_noise_preset", None))
        if not preset:
            logger.warning("Persona {} has platform ambient source but no preset", getattr(persona, "id", "?"))
            return None
        provider = get_ambient_asset_provider()
        try:
            file_bytes = provider.load_wav(preset)
        except FileNotFoundError:
            logger.warning(
                "Ambient preset {} is not available (install ambient asset pack or set EFFICIENTAI_AMBIENT_DIR)",
                preset,
            )
            return None
        return AmbientMixer.from_pcm_bytes(file_bytes, sample_rate=sample_rate, volume=volume)

    if source == BackgroundNoiseSourceEnum.CUSTOM.value:
        s3_key = _resolve_custom_ambient_s3_key(persona)
        if not s3_key:
            logger.warning(
                "Persona {} has custom ambient source but no resolvable audio",
                getattr(persona, "id", "?"),
            )
            return None
        try:
            from app.services.storage.s3_service import s3_service

            if not s3_service.is_enabled():
                logger.warning("Blob storage disabled; cannot load custom ambient audio for persona {}", getattr(persona, "id", "?"))
                return None
            file_bytes = s3_service.download_file_by_key(str(s3_key))
        except Exception as exc:
            logger.warning("Failed to load custom ambient audio for persona {}: {}", getattr(persona, "id", "?"), exc)
            return None
        return AmbientMixer.from_pcm_bytes(file_bytes, sample_rate=sample_rate, volume=volume)

    logger.warning("Unknown ambient source {} on persona {}", source, getattr(persona, "id", "?"))
    return None
