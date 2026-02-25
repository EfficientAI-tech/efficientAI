#
# Copyright (c) 2024–2025, EfficientAI
#

"""Murf text-to-speech service implementation.

This module provides integration with Murf's text-to-speech stream API for
generating high-quality synthetic speech from text input.
"""

import json
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel

from efficientai.frames.frames import (
    ErrorFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from efficientai.services.tts_service import TTSService
from efficientai.utils.tracing.service_decorators import traced_tts


class MurfTTSService(TTSService):
    """Murf Text-to-Speech service that generates audio from text.

    This service uses the Murf TTS stream API to generate PCM-encoded audio.
    Supports multiple voice models and configurable parameters for high-quality
    speech synthesis with streaming audio output.
    """

    MURF_SAMPLE_RATE = 24000  # Default to 24kHz

    class InputParams(BaseModel):
        """Input parameters for Murf TTS configuration.

        Parameters:
            multi_native_locale: Locale parameter for GEN2 models (e.g., "en-US").
        """
        multi_native_locale: Optional[str] = None

    def __init__(
        self,
        *,
        api_key: str,
        voice: str = "en-US-matthew",
        model: str = "GEN2",
        sample_rate: Optional[int] = None,
        params: Optional[InputParams] = None,
        **kwargs,
    ):
        """Initialize Murf TTS service.

        Args:
            api_key: Murf API key for authentication.
            voice: Voice ID to use for synthesis. Defaults to "en-US-matthew".
            model: TTS model to use. Defaults to "GEN2".
            sample_rate: Output audio sample rate in Hz. If None, uses default 24kHz.
            params: Optional synthesis controls like multi_native_locale.
            **kwargs: Additional keyword arguments passed to TTSService.
        """
        if sample_rate and sample_rate not in [8000, 24000, 44100, 48000]:
            logger.warning(
                f"Murf TTS may not support {sample_rate}Hz sample rate. "
                f"Standard rates are 8000, 24000, 44100, 48000Hz."
            )
        super().__init__(sample_rate=sample_rate or self.MURF_SAMPLE_RATE, **kwargs)

        self.api_key = api_key
        self.set_model_name(model)
        self.set_voice(voice)

        self._settings = {
            "multi_native_locale": params.multi_native_locale if params else None,
        }

    def can_generate_metrics(self) -> bool:
        """Check if this service can generate processing metrics.

        Returns:
            True, as Murf TTS service supports metrics generation.
        """
        return True

    async def set_model(self, model: str):
        """Set the TTS model to use.

        Args:
            model: The model name to use for text-to-speech synthesis.
        """
        logger.info(f"Switching TTS model to: [{model}]")
        self.set_model_name(model)

    async def start(self, frame: StartFrame):
        """Start the Murf TTS service.

        Args:
            frame: The start frame containing initialization parameters.
        """
        await super().start(frame)

    @traced_tts
    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        """Generate speech from text using Murf's TTS API.

        Args:
            text: The text to synthesize into speech.

        Yields:
            Frame: Audio frames containing the synthesized speech data.
        """
        logger.debug(f"{self}: Generating TTS [{text}]")
        try:
            await self.start_ttfb_metrics()

            url = "https://global.api.murf.ai/v1/speech/stream"
            headers = {
                "Content-Type": "application/json",
                "api-key": self.api_key,
            }

            payload = {
                "voiceId": self._voice_id,
                "text": text,
                "format": "PCM",
                "sampleRate": self.sample_rate,
                "modelId": self.model_name,
            }

            if self._settings["multi_native_locale"]:
                payload["multiNativeLocale"] = self._settings["multi_native_locale"]

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"{self} error getting audio (status: {response.status}, error: {error})")
                        yield ErrorFrame(error=f"Error getting audio (status: {response.status}, error: {error})")
                        return

                    await self.start_tts_usage_metrics(text)

                    CHUNK_SIZE = self.chunk_size

                    yield TTSStartedFrame()
                    async for chunk, _ in response.content.iter_chunks():
                        if not chunk:
                            break
                        
                        # Process the chunk in smaller piece if larger than CHUNK_SIZE
                        # iter_chunks might yield varying size chunks.
                        # Wait, we can just yield what we receive, or actually buffer if necessary.
                        # Often we just yield the chunk
                        if len(chunk) > 0:
                            await self.stop_ttfb_metrics()
                            # If chunk is too large we can split it, or just yield it directly.
                            # yielding it directly:
                            for i in range(0, len(chunk), CHUNK_SIZE):
                                c = chunk[i:i+CHUNK_SIZE]
                                frame = TTSAudioRawFrame(c, self.sample_rate, 1)
                                yield frame

                    yield TTSStoppedFrame()

        except Exception as e:
            logger.exception(f"{self} error generating TTS: {e}")
            yield ErrorFrame(error=f"{self} error: {e}")
