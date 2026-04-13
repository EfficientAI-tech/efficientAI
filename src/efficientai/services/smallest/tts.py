"""Smallest Lightning v3.1 HTTP TTS service for realtime pipelines."""

from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from efficientai.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from efficientai.services.tts_service import TTSService
from efficientai.utils.tracing.service_decorators import traced_tts


class SmallestTTSService(TTSService):
    """HTTP-based Smallest Lightning v3.1 TTS service."""

    class InputParams(BaseModel):
        language: str = "en"
        speed: float = Field(default=1.0, ge=0.5, le=2.0)
        output_format: str = "wav"
        sample_rate_hz: int = Field(default=24000)

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str = "daniel",
        model: str = "lightning-v3.1",
        sample_rate: int = 24000,
        params: Optional[InputParams] = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model or "lightning-v3.1"
        self._params = params or SmallestTTSService.InputParams(sample_rate_hz=sample_rate)
        self._session: Optional[aiohttp.ClientSession] = None

    def can_generate_metrics(self) -> bool:
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def stop(self, frame: Frame):
        await super().stop(frame)
        if self._session:
            await self._session.close()
            self._session = None

    async def cancel(self, frame: Frame):
        await super().cancel(frame)
        if self._session:
            await self._session.close()
            self._session = None

    @traced_tts
    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"Generating Smallest TTS: [{text}]")
        endpoint_model = self._model if self._model == "lightning-v3.1" else "lightning-v3.1"
        url = f"https://api.smallest.ai/waves/v1/{endpoint_model}/get_speech"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "audio/wav",
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "voice_id": self._voice_id,
            "sample_rate": int(self.sample_rate or self._params.sample_rate_hz),
            "speed": float(self._params.speed),
            "language": self._params.language,
            "output_format": self._params.output_format,
        }

        try:
            session = await self._get_session()
            await self.start_ttfb_metrics()
            await self.start_tts_usage_metrics(text)
            yield TTSStartedFrame()

            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Smallest TTS error: {response.status} - {error_text[:300]}")
                    yield ErrorFrame(error=f"Smallest TTS error: {error_text[:300]}")
                    return

                await self.stop_ttfb_metrics()
                audio_bytes = await response.read()

            # Strip WAV header for downstream PCM playback.
            if len(audio_bytes) > 44 and audio_bytes[:4] == b"RIFF":
                audio_bytes = audio_bytes[44:]

            chunk_size = 4096
            for i in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[i : i + chunk_size]
                if chunk:
                    yield TTSAudioRawFrame(audio=chunk, sample_rate=self.sample_rate, num_channels=1)

            yield TTSStoppedFrame()
        except Exception as e:
            logger.error(f"Smallest TTS exception: {e}")
            yield ErrorFrame(error=f"Smallest TTS exception: {str(e)}")
            yield TTSStoppedFrame()
