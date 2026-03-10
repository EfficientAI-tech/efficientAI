"""Lightweight VoiceMaker TTS helper for app-level synthesis."""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

_VOICE_LANG_CACHE: Dict[str, str] | None = None


def _infer_language_code(voice_id: str) -> str:
    """Resolve the LanguageCode for a VoiceMaker voice ID.

    Checks the bundled voicemaker_voices.json first, then falls back to en-US.
    """
    global _VOICE_LANG_CACHE
    if _VOICE_LANG_CACHE is None:
        _VOICE_LANG_CACHE = {}
        config_path = Path(__file__).resolve().parents[4] / "app" / "config" / "voicemaker_voices.json"
        if config_path.exists():
            try:
                voices = json.loads(config_path.read_text())
                for v in voices:
                    vid = v.get("id", "")
                    lang = v.get("language_code", "")
                    if vid and lang:
                        _VOICE_LANG_CACHE[vid] = lang
            except Exception:
                pass

    return _VOICE_LANG_CACHE.get(voice_id, "en-US")


def synthesize_voicemaker_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via VoiceMaker and return (audio_bytes, ttfb_ms)."""
    effective_config = dict(config) if config else {}
    sample_rate_hz = effective_config.pop("sample_rate_hz", None)

    voice_id = voice or effective_config.pop("VoiceId", "ai3-Jony")
    language_code = effective_config.pop("LanguageCode", None) or effective_config.pop("language_code", None)
    if not language_code:
        language_code = _infer_language_code(voice_id)

    payload: Dict[str, Any] = {
        "VoiceId": voice_id,
        "Text": text,
        "LanguageCode": language_code,
        "OutputFormat": effective_config.pop("OutputFormat", "mp3"),
        "SampleRate": str(int(sample_rate_hz)) if sample_rate_hz else str(effective_config.pop("SampleRate", "48000")),
        "ResponseType": effective_config.pop("ResponseType", "file"),
    }
    if model:
        payload["Engine"] = model
    if effective_config:
        payload.update(effective_config)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = "https://developer.voicemaker.in/api/v1/voice/convert"

    start = time.time()
    response = requests.post(url, json=payload, headers=headers, timeout=90)
    if response.status_code != 200:
        error_text = response.text[:500] if response.text else ""
        raise RuntimeError(f"VoiceMaker TTS failed ({response.status_code}): {error_text}")
    ttfb_ms = (time.time() - start) * 1000

    data = response.json()
    audio_path = data.get("path")
    if not audio_path:
        raise RuntimeError("VoiceMaker TTS returned no audio path")

    audio_response = requests.get(audio_path, timeout=120)
    if audio_response.status_code != 200:
        raise RuntimeError(
            f"VoiceMaker audio download failed ({audio_response.status_code}): {audio_response.text[:300]}"
        )
    return audio_response.content, ttfb_ms

