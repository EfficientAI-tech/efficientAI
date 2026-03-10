#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import json
import time
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

import aiohttp
import requests
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


def synthesize_murf_stream_bytes(
    text: str,
    model: str,
    api_key: str,
    voice: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, float]:
    """Synthesize speech bytes via Murf streaming REST API.

    Returns:
        Tuple of (audio_bytes, ttfb_ms).
    """
    model_map = {
        "murf-falcon": "FALCON",
        "murf-gen2": "GEN2",
    }
    murf_model = model_map.get((model or "").lower(), model or "GEN2")

    model_upper = str(murf_model).upper()
    # Murf currently supports FALCON on global endpoint, while GEN2 may require api.murf.ai.
    base_url = "https://api.murf.ai" if model_upper == "GEN2" else "https://global.api.murf.ai"
    url = f"{base_url}/v1/speech/stream"
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    effective_config = dict(config) if config else {}
    # Murf API uses `rate`; older callers may send `speed`.
    if "speed" in effective_config and "rate" not in effective_config:
        effective_config["rate"] = effective_config.pop("speed")

    sample_rate_hz = effective_config.pop("sample_rate_hz", None)
    voice_id = voice or "en-US-natalie"
    locale = effective_config.get("locale")
    if not locale and voice_id and "-" in voice_id:
        # Infer locale from voice IDs like "en-US-aarav" -> "en-US".
        parts = voice_id.split("-")
        if len(parts) >= 2:
            locale = f"{parts[0]}-{parts[1]}"

    default_sample_rate = 24000 if model_upper == "FALCON" else 44100
    payload: Dict[str, Any] = {
        "text": text,
        "voiceId": voice_id,
        "model": murf_model,
        "format": "MP3",
        "channelType": "MONO",
        "sampleRate": int(sample_rate_hz) if sample_rate_hz else default_sample_rate,
    }
    if locale:
        payload["locale"] = locale
    if effective_config:
        payload.update(effective_config)

    start = time.time()
    response = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
    if response.status_code != 200:
        error_text = response.text[:500] if response.text else ""

        # Fallback: Murf can reject a model on one base URL and instruct another.
        if (
            response.status_code == 400
            and "not available in global.api.murf.ai" in error_text
            and "api.murf.ai" in error_text
            and "global.api.murf.ai" in url
        ):
            fallback_url = "https://api.murf.ai/v1/speech/stream"
            response = requests.post(
                fallback_url, json=payload, headers=headers, stream=True, timeout=60
            )
            if response.status_code != 200:
                fallback_error = response.text[:500] if response.text else ""
                raise RuntimeError(
                    f"Murf stream failed ({response.status_code}) at {fallback_url}: {fallback_error}"
                )
        else:
            raise RuntimeError(
                f"Murf stream failed ({response.status_code}) at {url}: {error_text}"
            )

    ttfb_ms: Optional[float] = None
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            if ttfb_ms is None:
                ttfb_ms = (time.time() - start) * 1000
            chunks.append(chunk)

    audio_bytes = b"".join(chunks)
    if not audio_bytes:
        raise RuntimeError("Murf streaming API returned empty audio")

    return audio_bytes, ttfb_ms if ttfb_ms is not None else (time.time() - start) * 1000


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
