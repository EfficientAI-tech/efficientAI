#
# VoiceMaker TTS service for Pipecat pipeline integration.
#

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

from .http_tts import _infer_language_code


class VoiceMakerTTSService(TTSService):
    """VoiceMaker TTS service for real-time voice pipeline use.

    Downloads audio from VoiceMaker's REST API and yields PCM frames
    compatible with the Pipecat pipeline.
    """

    class InputParams(BaseModel):
        output_format: str = "wav"
        sample_rate_hz: int = 24000

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str = "ai3-Jony",
        model: str = "neural",
        sample_rate: int = 24000,
        params: Optional[InputParams] = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model
        self._params = params or VoiceMakerTTSService.InputParams(sample_rate_hz=sample_rate)
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
        logger.debug(f"Generating VoiceMaker TTS: [{text}]")

        language_code = _infer_language_code(self._voice_id)

        payload = {
            "VoiceId": self._voice_id,
            "Text": text,
            "LanguageCode": language_code,
            "OutputFormat": "wav",
            "SampleRate": str(self.sample_rate),
            "ResponseType": "file",
        }
        if self._model:
            engine = self._model
            if engine.lower().startswith("voicemaker-"):
                engine = engine[len("voicemaker-"):]
            payload["Engine"] = engine

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            session = await self._get_session()
            await self.start_ttfb_metrics()

            async with session.post(
                "https://developer.voicemaker.in/api/v1/voice/convert",
                json=payload,
                headers=headers,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"VoiceMaker TTS error: {response.status} - {error_text[:300]}")
                    yield ErrorFrame(error=f"VoiceMaker TTS error: {error_text[:300]}")
                    return

                data = await response.json()
                audio_url = data.get("path")
                if not audio_url:
                    yield ErrorFrame(error="VoiceMaker returned no audio path")
                    return

            await self.start_tts_usage_metrics(text)
            yield TTSStartedFrame()
            await self.stop_ttfb_metrics()

            async with session.get(audio_url) as audio_resp:
                if audio_resp.status != 200:
                    yield ErrorFrame(error=f"VoiceMaker audio download failed: {audio_resp.status}")
                    return

                audio_bytes = await audio_resp.read()

                # Strip WAV header (44 bytes) to get raw PCM
                pcm_data = audio_bytes[44:] if len(audio_bytes) > 44 else audio_bytes

                # Yield in chunks for smooth pipeline flow
                chunk_size = 4096
                for i in range(0, len(pcm_data), chunk_size):
                    chunk = pcm_data[i : i + chunk_size]
                    if chunk:
                        yield TTSAudioRawFrame(
                            audio=chunk,
                            sample_rate=self.sample_rate,
                            num_channels=1,
                        )

            yield TTSStoppedFrame()

        except Exception as e:
            logger.error(f"VoiceMaker TTS exception: {e}")
            yield ErrorFrame(error=f"VoiceMaker TTS exception: {str(e)}")
            yield TTSStoppedFrame()
