"""Lightweight Google TTS helper for app-level synthesis."""

import time
from typing import Any, Dict, Optional, Tuple


def synthesize_google_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech via Google TTS and return (audio_bytes, ttfb_ms)."""
    try:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice_config = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=voice if voice else None,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )
        start = time.time()
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_config,
            audio_config=audio_config,
        )
        ttfb_ms = (time.time() - start) * 1000
        return response.audio_content, ttfb_ms
    except ImportError:
        raise RuntimeError("Google Cloud TTS library not installed.")
    except Exception as e:
        raise RuntimeError(f"Google TTS synthesis failed: {e}")

