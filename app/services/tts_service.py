"""
TTS service for converting text to speech using various TTS providers.
"""

import time
import tempfile
import os
from typing import Optional, Dict, Any
from uuid import UUID
from pathlib import Path

from app.models.database import ModelProvider, AIProvider
from app.services.s3_service import s3_service
from sqlalchemy.orm import Session


class TTSService:
    """Service for converting text to speech using various TTS providers."""

    def __init__(self):
        """Initialize TTS service."""
        pass

    def _get_ai_provider(self, provider: ModelProvider, db: Session, organization_id: UUID) -> Optional[AIProvider]:
        """Get AI provider configuration from database."""
        from sqlalchemy import func
        
        # Handle both string and enum comparisons (database might have uppercase or lowercase)
        provider_value = provider.value if hasattr(provider, 'value') else provider
        
        # Try exact match first
        ai_provider = db.query(AIProvider).filter(
            AIProvider.provider == provider_value,
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True
        ).first()
        
        # If not found, try case-insensitive match
        if not ai_provider:
            ai_provider = db.query(AIProvider).filter(
                func.lower(AIProvider.provider) == provider_value.lower(),
                AIProvider.organization_id == organization_id,
                AIProvider.is_active == True
            ).first()
        
        return ai_provider

    def _synthesize_with_openai(
        self,
        text: str,
        model: str,
        api_key: str,
        voice: Optional[str] = "alloy",
        config: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """Synthesize speech using OpenAI TTS API."""
        try:
            from openai import OpenAI
            
            client = OpenAI(api_key=api_key)
            
            # Prepare request parameters
            request_params = {
                "model": model,
                "input": text,
                "voice": voice or "alloy",
            }
            
            # Add any additional config
            if config:
                request_params.update(config)
            
            response = client.audio.speech.create(**request_params)
            
            # Read audio bytes
            audio_bytes = b""
            for chunk in response.iter_bytes():
                audio_bytes += chunk
            
            return audio_bytes
        except ImportError:
            raise RuntimeError("OpenAI library not installed. Install with: pip install openai")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            raise RuntimeError(f"OpenAI TTS synthesis failed: {str(e)}\nDetails: {error_details}")

    def _synthesize_with_google(
        self,
        text: str,
        model: str,
        api_key: str,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """Synthesize speech using Google TTS API."""
        try:
            from google.cloud import texttospeech
            
            client = texttospeech.TextToSpeechClient()
            
            # Prepare synthesis input
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            # Prepare voice selection
            voice_config = texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name=voice if voice else None,
            )
            
            # Prepare audio config
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            
            # Generate speech
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice_config,
                audio_config=audio_config
            )
            
            return response.audio_content
        except ImportError:
            raise RuntimeError("Google Cloud TTS library not installed. Install with: pip install google-cloud-texttospeech")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            raise RuntimeError(f"Google TTS synthesis failed: {str(e)}\nDetails: {error_details}")

    def synthesize(
        self,
        text: str,
        tts_provider: ModelProvider,
        tts_model: str,
        organization_id: UUID,
        db: Session,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
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
        start_time = time.time()
        
        # Get provider API key
        ai_provider = self._get_ai_provider(tts_provider, db, organization_id)
        if not ai_provider:
            raise RuntimeError(f"AI provider {tts_provider} not configured for this organization.")
        
        # Decrypt API key
        from app.core.encryption import decrypt_api_key
        try:
            api_key = decrypt_api_key(ai_provider.api_key)
        except Exception as e:
            raise RuntimeError(f"Failed to decrypt API key for provider {tts_provider}: {str(e)}")
        
        # Synthesize based on provider
        if tts_provider == ModelProvider.OPENAI:
            audio_bytes = self._synthesize_with_openai(text, tts_model, api_key, voice, config)
        elif tts_provider == ModelProvider.GOOGLE:
            audio_bytes = self._synthesize_with_google(text, tts_model, api_key, voice, config)
        else:
            raise NotImplementedError(f"TTS provider {tts_provider} not yet implemented")
        
        processing_time = time.time() - start_time
        
        return audio_bytes

    def synthesize_and_upload(
        self,
        text: str,
        tts_provider: ModelProvider,
        tts_model: str,
        organization_id: UUID,
        db: Session,
        voice: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        file_prefix: str = "tts_output"
    ) -> str:
        """
        Synthesize speech and upload to S3.
        
        Returns:
            S3 key of uploaded audio file
        """
        # Synthesize audio
        audio_bytes = self.synthesize(text, tts_provider, tts_model, organization_id, db, voice, config)
        
        # Upload to S3
        import uuid
        file_id = uuid.uuid4()
        s3_key = s3_service.upload_file(
            file_id=file_id,
            file_content=audio_bytes,
            file_format="mp3",
            organization_id=organization_id
        )
        
        return s3_key


# Singleton instance
tts_service = TTSService()

