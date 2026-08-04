"""Validate provider-specific persona TTS configuration."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Allowed top-level keys per provider (nested dicts allowed where noted).
PERSONA_TTS_KEYS: Dict[str, frozenset[str]] = {
    "cartesia": frozenset(
        {"speed", "language", "generation_config", "generation_config_speed", "generation_config_volume", "generation_config_emotion"}
    ),
    "elevenlabs": frozenset(
        {
            "speed",
            "stability",
            "similarity_boost",
            "style",
            "use_speaker_boost",
            "optimize_streaming_latency",
            "apply_text_normalization",
        }
    ),
    "openai": frozenset({"speed", "instructions"}),
    "sarvam": frozenset({"pace", "pitch", "loudness", "temperature", "enable_preprocessing"}),
    "smallest": frozenset({"speed", "language"}),
    "murf": frozenset({"speed", "rate", "pitch", "style"}),
    "voicemaker": frozenset({"output_format", "sample_rate_hz"}),
}


def _check_range(name: str, value: Any, lo: float, hi: float) -> None:
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"tts_config.{name} must be a number") from exc
    if num < lo or num > hi:
        raise ValueError(f"tts_config.{name} must be between {lo} and {hi}")


def _normalize_cartesia_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten UI-friendly generation_config_* keys into nested generation_config."""
    out = dict(config)
    gen: Dict[str, Any] = dict(out.pop("generation_config", None) or {})
    for src, dst in (
        ("generation_config_speed", "speed"),
        ("generation_config_volume", "volume"),
        ("generation_config_emotion", "emotion"),
    ):
        if src in out:
            gen[dst] = out.pop(src)
    if gen:
        out["generation_config"] = gen
    return out


def validate_persona_tts_config(provider: Optional[str], tts_config: Optional[Dict[str, Any]]) -> None:
    if not tts_config:
        return
    if not provider:
        raise ValueError("tts_config requires tts_provider to be set")
    key = provider.strip().lower()
    allowed = PERSONA_TTS_KEYS.get(key)
    if allowed is None:
        raise ValueError(f"Unsupported tts_provider for persona tts_config: {provider}")

    normalized = _normalize_cartesia_config(tts_config) if key == "cartesia" else dict(tts_config)
    unknown = set(normalized.keys()) - allowed
    if unknown:
        raise ValueError(f"Unsupported tts_config keys for {key}: {sorted(unknown)}")

    if key == "cartesia":
        speed = normalized.get("speed")
        if speed is not None and speed not in ("slow", "normal", "fast"):
            raise ValueError("tts_config.speed must be slow, normal, or fast")
        gen = normalized.get("generation_config") or {}
        if gen.get("speed") is not None:
            _check_range("generation_config.speed", gen["speed"], 0.6, 1.5)
        if gen.get("volume") is not None:
            _check_range("generation_config.volume", gen["volume"], 0.5, 2.0)
    elif key == "elevenlabs":
        for field, lo, hi in (
            ("speed", 0.25, 4.0),
            ("stability", 0.0, 1.0),
            ("similarity_boost", 0.0, 1.0),
            ("style", 0.0, 1.0),
        ):
            if normalized.get(field) is not None:
                _check_range(field, normalized[field], lo, hi)
        lat = normalized.get("optimize_streaming_latency")
        if lat is not None:
            try:
                lat_int = int(lat)
            except (TypeError, ValueError) as exc:
                raise ValueError("tts_config.optimize_streaming_latency must be an integer") from exc
            if lat_int < 0 or lat_int > 4:
                raise ValueError("tts_config.optimize_streaming_latency must be between 0 and 4")
        norm = normalized.get("apply_text_normalization")
        if norm is not None and norm not in ("auto", "on", "off"):
            raise ValueError("tts_config.apply_text_normalization must be auto, on, or off")
    elif key == "openai":
        if normalized.get("speed") is not None:
            _check_range("speed", normalized["speed"], 0.25, 4.0)
    elif key == "sarvam":
        if normalized.get("pace") is not None:
            _check_range("pace", normalized["pace"], 0.3, 3.0)
        if normalized.get("pitch") is not None:
            _check_range("pitch", normalized["pitch"], -0.75, 0.75)
        if normalized.get("loudness") is not None:
            _check_range("loudness", normalized["loudness"], 0.1, 3.0)
        if normalized.get("temperature") is not None:
            _check_range("temperature", normalized["temperature"], 0.01, 1.0)
    elif key == "smallest":
        if normalized.get("speed") is not None:
            _check_range("speed", normalized["speed"], 0.5, 2.0)


def normalize_persona_tts_config(provider: Optional[str], tts_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not tts_config:
        return None
    key = (provider or "").strip().lower()
    if key == "cartesia":
        return _normalize_cartesia_config(tts_config)
    return dict(tts_config)
