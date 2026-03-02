#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import base64
import json
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel

from efficientai.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from efficientai.services.tts_service import TTSService
from efficientai.utils.tracing.service_decorators import traced_tts


class MurfTTSService(TTSService):
    """Murf TTS service using the streaming REST API."""

    class InputParams(BaseModel):
        pitch: Optional[int] = None
        speed: Optional[int] = None
        style: Optional[str] = None

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str = "en-US-natalie",
        model: str = "GEN2",
        sample_rate: int = 24000,
        params: Optional[InputParams] = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._api_key = api_key
        self._voice_id = voice_id
        self._model_name = model
        self._params = params or MurfTTSService.InputParams()
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
        logger.debug(f"Generating Murf TTS: [{text}]")

        url = "https://api.murf.ai/v1/speech/stream"
        headers = {
            "api-key": self._api_key,
            "Content-Type": "application/json",
        }
        
        # Map internal model names if they come in as murf-falcon/murf-gen2
        model_id = self._model_name
        if model_id.lower() == "murf-falcon":
            model_id = "FALCON"
        elif model_id.lower() == "murf-gen2":
            model_id = "GEN2"

        payload = {
            "text": text,
            "voiceId": self._voice_id,
            "model": model_id,
            "format": "PCM",
            "channelType": "MONO",
            "sampleRate": self.sample_rate,
        }

        if self._params.pitch is not None:
            payload["pitch"] = self._params.pitch
        if self._params.speed is not None:
            payload["speed"] = self._params.speed
        if self._params.style:
            payload["style"] = self._params.style

        try:
            session = await self._get_session()
            await self.start_ttfb_metrics()
            
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Murf TTS error: {response.status} - {error_text}")
                    yield ErrorFrame(error=f"Murf TTS error: {error_text}")
                    return

                await self.start_tts_usage_metrics(text)
                yield TTSStartedFrame()

                await self.stop_ttfb_metrics()

                # Murf streaming API returns raw PCM bytes in the response body
                # We yield them as TTSAudioRawFrames
                async for chunk in response.content.iter_chunked(4096):
                    if chunk:
                        yield TTSAudioRawFrame(
                            audio=chunk,
                            sample_rate=self.sample_rate,
                            num_channels=1
                        )
                
                yield TTSStoppedFrame()

        except Exception as e:
            logger.error(f"Murf TTS exception: {e}")
            yield ErrorFrame(error=f"Murf TTS exception: {str(e)}")
            yield TTSStoppedFrame()
