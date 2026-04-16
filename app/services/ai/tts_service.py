"""
TTS service for converting text to speech using various TTS providers.
"""

import time
from typing import Optional, Dict, Any, Tuple
from uuid import UUID

from app.models.database import ModelProvider, AIProvider, Integration
from app.services.storage.s3_service import s3_service
from efficientai.services.cartesia.http_tts import synthesize_cartesia_bytes
from efficientai.services.deepgram.http_tts import synthesize_deepgram_bytes
from efficientai.services.elevenlabs.http_tts import synthesize_elevenlabs_bytes
from efficientai.services.google.http_tts import synthesize_google_bytes
from efficientai.services.murf.tts import synthesize_murf_stream_bytes
from efficientai.services.openai.http_tts import synthesize_openai_bytes
from efficientai.services.sarvam.http_tts import synthesize_sarvam_bytes
from efficientai.services.smallest.http_tts import synthesize_smallest_bytes
from efficientai.services.voicemaker.http_tts import synthesize_voicemaker_bytes
from sqlalchemy.orm import Session


ELEVENLABS_HZ_TO_OUTPUT_FORMAT = {
    8000: "pcm_8000",
    16000: "pcm_16000",
    22050: "mp3_22050_32",
    24000: "pcm_24000",
    44100: "mp3_44100_128",
}

PROVIDER_SUPPORTED_SAMPLE_RATES: Dict[str, list] = {
    "elevenlabs": [8000, 16000, 22050, 24000, 44100],
    "cartesia": [8000, 16000, 22050, 24000, 44100],
    "deepgram": [8000, 16000, 24000, 48000],
    "smallest": [8000, 16000, 24000],
    "voicemaker": [8000, 16000, 22050, 24000, 44100, 48000],
}


def get_audio_file_extension(provider: str, sample_rate_hz: Optional[int] = None) -> str:
    """Determine audio file extension based on provider and requested sample rate."""
    if provider == "sarvam":
        # Sarvam HTTP TTS returns base64 WAV audio.
        return "wav"
    if provider == "smallest":
        return "wav"
    if provider == "elevenlabs" and sample_rate_hz:
        fmt = ELEVENLABS_HZ_TO_OUTPUT_FORMAT.get(sample_rate_hz, "")
        if fmt.startswith(("pcm_", "ulaw_")):
            return "wav"
    return "mp3"


class TTSService:
    """Service for converting text to speech using various TTS providers."""

    def __init__(self):
        self._provider_handlers: Dict[str, Any] = {}

    def _get_ai_provider(self, provider: ModelProvider, db: Session, organization_id: UUID) -> Optional[AIProvider]:
        """Get AI provider configuration from database."""
        from sqlalchemy import func

        provider_value = provider.value if hasattr(provider, "value") else provider

        ai_provider = db.query(AIProvider).filter(
            AIProvider.provider == provider_value,
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True,
        ).first()

        if not ai_provider:
            ai_provider = db.query(AIProvider).filter(
                func.lower(AIProvider.provider) == provider_value.lower(),
                AIProvider.organization_id == organization_id,
                AIProvider.is_active == True,
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
        provider_value = provider.value if hasattr(provider, "value") else provider
        integration = db.query(Integration).filter(
            func.lower(Integration.platform) == provider_value.lower(),
            Integration.organization_id == organization_id,
            Integration.is_active == True,
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
    ) -> Tuple[bytes, float]:
        return synthesize_openai_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # Google (unary RPC - no streaming; TTFB ~= total API time)
    # ------------------------------------------------------------------

    def _synthesize_with_google(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        return synthesize_google_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # ElevenLabs
    # ------------------------------------------------------------------

    def _synthesize_with_elevenlabs(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        return synthesize_elevenlabs_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # Cartesia
    # ------------------------------------------------------------------

    def _synthesize_with_cartesia(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        return synthesize_cartesia_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # Deepgram
    # ------------------------------------------------------------------

    def _synthesize_with_deepgram(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        return synthesize_deepgram_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # Sarvam
    # ------------------------------------------------------------------

    def _synthesize_with_sarvam(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        return synthesize_sarvam_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # VoiceMaker
    # ------------------------------------------------------------------

    def _synthesize_with_voicemaker(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        return synthesize_voicemaker_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # Smallest.ai
    # ------------------------------------------------------------------

    def _synthesize_with_smallest(
        self, text: str, model: str, api_key: str,
        voice: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        return synthesize_smallest_bytes(text=text, model=model, api_key=api_key, voice=voice, config=config)

    # ------------------------------------------------------------------
    # Main synthesis entry point
    # ------------------------------------------------------------------

    def register_tts_provider(self, provider: str, handler: Any) -> None:
        """Register/override a TTS provider handler dynamically."""
        self._provider_handlers[provider.strip().lower()] = handler

    def _get_tts_handler(self, tts_provider: ModelProvider):
        provider_key = (tts_provider.value if hasattr(tts_provider, "value") else str(tts_provider)).lower()

        # Prefer explicitly registered handlers.
        handler = self._provider_handlers.get(provider_key)
        if handler:
            return handler

        # Fallback convention: _synthesize_with_<provider>.
        handler = getattr(self, f"_synthesize_with_{provider_key}", None)
        if callable(handler):
            # Cache resolved handler to avoid repeated getattr lookups.
            self._provider_handlers[provider_key] = handler
            return handler

        if not handler:
            raise NotImplementedError(f"TTS provider {tts_provider} not supported")
        return handler

    def _synthesize_with_murf(
        self,
        text: str,
        model: str,
        api_key: str,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bytes, float]:
        """Delegate Murf synthesis to shared efficientai Murf service helper."""
        try:
            return synthesize_murf_stream_bytes(
                text=text,
                model=model,
                api_key=api_key,
                voice=voice,
                config=config,
            )
        except ImportError:
            raise RuntimeError("requests library not installed. Install with: pip install requests")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            raise RuntimeError(f"Murf TTS synthesis failed: {str(e)}\nDetails: {error_details}")

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
        """
        Synthesize speech from text.

        Args:
            text: Text to convert to speech
            tts_provider: TTS provider to use
            tts_model: TTS model name
            organization_id: Organization ID
            db: Database session
            voice: Voice selection (if applicable)
            config: Additional provider-specific configuration

        Returns:
            Audio bytes (MP3 format)
        """
        api_key = self._get_api_key_for_provider(tts_provider, db, organization_id)
        handler = self._get_tts_handler(tts_provider)
        audio_bytes, _ttfb_ms = handler(text, tts_model, api_key, voice, config)
        return audio_bytes

    def synthesize_timed(
        self,
        text: str,
        tts_provider: ModelProvider,
        tts_model: str,
        organization_id: UUID,
        db: Session,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bytes, float, float]:
        """Synthesize and return (audio_bytes, total_latency_ms, ttfb_ms)."""
        api_key = self._get_api_key_for_provider(tts_provider, db, organization_id)
        handler = self._get_tts_handler(tts_provider)
        start = time.time()
        audio_bytes, ttfb_ms = handler(text, tts_model, api_key, voice, config)
        total_latency_ms = (time.time() - start) * 1000
        return audio_bytes, total_latency_ms, ttfb_ms

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
