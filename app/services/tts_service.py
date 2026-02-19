"""
TTS service for converting text to speech using various TTS providers.
"""

import time
import tempfile
import os
import requests
from typing import Optional, Dict, Any, Tuple
from uuid import UUID
from pathlib import Path
from loguru import logger

from app.models.database import ModelProvider, AIProvider, Integration
from app.services.s3_service import s3_service
from sqlalchemy.orm import Session


class TTSService:
    """Service for converting text to speech using various TTS providers."""

    def __init__(self):
        pass

    def _get_ai_provider(self, provider: ModelProvider, db: Session, organization_id: UUID) -> Optional[AIProvider]:
        """Get AI provider configuration from database."""
        from sqlalchemy import func

        provider_value = provider.value if hasattr(provider, 'value') else provider

        ai_provider = db.query(AIProvider).filter(
            AIProvider.provider == provider_value,
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True
        ).first()

        if not ai_provider:
            ai_provider = db.query(AIProvider).filter(
                func.lower(AIProvider.provider) == provider_value.lower(),
                AIProvider.organization_id == organization_id,
                AIProvider.is_active == True
            ).first()

        return ai_provider

    def _get_api_key_for_provider(
        self, provider: ModelProvider, db: Session, organization_id: UUID
    ) -> str:
        """Resolve and decrypt API key from AIProvider or Integration tables."""
        from app.core.encryption import decrypt_api_key
        from sqlalchemy import func

        ai_provider = self._get_ai_provider(provider, db, organization_id)
        if ai_provider:
            return decrypt_api_key(ai_provider.api_key)

        # Fallback: check Integration table for cartesia/elevenlabs/deepgram
        provider_value = provider.value if hasattr(provider, 'value') else provider
        integration = db.query(Integration).filter(
            func.lower(Integration.platform) == provider_value.lower(),
            Integration.organization_id == organization_id,
            Integration.is_active == True
        ).first()
        if integration:
            return decrypt_api_key(integration.api_key)

        raise RuntimeError(f"No API key configured for provider {provider_value}")

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    def _synthesize_with_openai(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = "alloy", config: Optional[Dict[str, Any]] = None
    ) -> bytes:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            request_params = {"model": model, "input": text, "voice": voice or "alloy"}
            if config:
                request_params.update(config)

            response = client.audio.speech.create(**request_params)
            audio_bytes = b""
            for chunk in response.iter_bytes():
                audio_bytes += chunk
            return audio_bytes
        except ImportError:
            raise RuntimeError("OpenAI library not installed. Install with: pip install openai")
        except Exception as e:
            raise RuntimeError(f"OpenAI TTS synthesis failed: {e}")

    # ------------------------------------------------------------------
    # Google
    # ------------------------------------------------------------------

    def _synthesize_with_google(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> bytes:
        try:
            from google.cloud import texttospeech

            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice_config = texttospeech.VoiceSelectionParams(
                language_code="en-US", name=voice if voice else None,
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            response = client.synthesize_speech(
                input=synthesis_input, voice=voice_config, audio_config=audio_config,
            )
            return response.audio_content
        except ImportError:
            raise RuntimeError("Google Cloud TTS library not installed.")
        except Exception as e:
            raise RuntimeError(f"Google TTS synthesis failed: {e}")

    # ------------------------------------------------------------------
    # ElevenLabs
    # ------------------------------------------------------------------

    def _synthesize_with_elevenlabs(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> bytes:
        voice_id = voice or "21m00Tcm4TlvDq8ikWAM"  # default: Rachel
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        body: Dict[str, Any] = {
            "text": text,
            "model_id": model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        if config:
            body.update(config)

        resp = requests.post(url, json=body, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(
                f"ElevenLabs TTS failed ({resp.status_code}): {resp.text[:500]}"
            )
        return resp.content

    # ------------------------------------------------------------------
    # Cartesia
    # ------------------------------------------------------------------

    def _synthesize_with_cartesia(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> bytes:
        voice_id = voice or "a0e99841-438c-4a64-b679-ae501e7d6091"  # default: Barbershop Man
        url = "https://api.cartesia.ai/tts/bytes"
        headers = {
            "X-API-Key": api_key,
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "model_id": model,
            "transcript": text,
            "voice": {"mode": "id", "id": voice_id},
            "output_format": {
                "container": "mp3",
                "bit_rate": 128000,
                "sample_rate": 44100,
            },
        }
        if config:
            body.update(config)

        resp = requests.post(url, json=body, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Cartesia TTS failed ({resp.status_code}): {resp.text[:500]}"
            )
        return resp.content

    # ------------------------------------------------------------------
    # Deepgram
    # ------------------------------------------------------------------

    def _synthesize_with_deepgram(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> bytes:
        voice_model = voice or "aura-asteria-en"
        url = f"https://api.deepgram.com/v1/speak?model={voice_model}"
        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        body = {"text": text}

        resp = requests.post(url, json=body, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Deepgram TTS failed ({resp.status_code}): {resp.text[:500]}"
            )
        return resp.content

    # ------------------------------------------------------------------
    # Main synthesis entry point
    # ------------------------------------------------------------------

    def synthesize(
        self,
        text: str,
        tts_provider: ModelProvider,
        tts_model: str,
        organization_id: UUID,
        db: Session,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Synthesize speech from text. Returns audio bytes (MP3)."""
        api_key = self._get_api_key_for_provider(tts_provider, db, organization_id)

        dispatch = {
            ModelProvider.OPENAI: self._synthesize_with_openai,
            ModelProvider.GOOGLE: self._synthesize_with_google,
            ModelProvider.ELEVENLABS: self._synthesize_with_elevenlabs,
            ModelProvider.CARTESIA: self._synthesize_with_cartesia,
            ModelProvider.DEEPGRAM: self._synthesize_with_deepgram,
        }

        handler = dispatch.get(tts_provider)
        if not handler:
            raise NotImplementedError(f"TTS provider {tts_provider} not supported")

        return handler(text, tts_model, api_key, voice, config)

    def synthesize_timed(
        self,
        text: str,
        tts_provider: ModelProvider,
        tts_model: str,
        organization_id: UUID,
        db: Session,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bytes, float]:
        """Synthesize and return (audio_bytes, latency_ms)."""
        start = time.time()
        audio = self.synthesize(text, tts_provider, tts_model, organization_id, db, voice, config)
        latency_ms = (time.time() - start) * 1000
        return audio, latency_ms

    def synthesize_and_upload(
        self,
        text: str,
        tts_provider: ModelProvider,
        tts_model: str,
        organization_id: UUID,
        db: Session,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        file_prefix: str = "tts_output",
    ) -> str:
        """Synthesize speech and upload to S3. Returns S3 key."""
        audio_bytes = self.synthesize(text, tts_provider, tts_model, organization_id, db, voice, config)

        import uuid as _uuid
        file_id = _uuid.uuid4()
        s3_key = s3_service.upload_file(
            file_id=file_id,
            file_content=audio_bytes,
            file_format="mp3",
            organization_id=organization_id,
        )
        return s3_key


# Singleton instance
tts_service = TTSService()

