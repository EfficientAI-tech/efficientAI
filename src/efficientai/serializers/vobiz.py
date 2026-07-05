#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Vobiz WebSocket frame serializer for audio streaming."""

import base64
import json
from typing import Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel

from efficientai.audio.dtmf.types import KeypadEntry
from efficientai.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm
from efficientai.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
)
from efficientai.serializers.base_serializer import FrameSerializer, FrameSerializerType


class VobizFrameSerializer(FrameSerializer):
    """Serializer for Vobiz bidirectional audio WebSocket protocol."""

    class InputParams(BaseModel):
        vobiz_sample_rate: int = 8000
        sample_rate: Optional[int] = None
        auto_hang_up: bool = True
        api_base: str = "https://api.vobiz.ai"

    def __init__(
        self,
        stream_id: str,
        call_id: Optional[str] = None,
        auth_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        params: Optional[InputParams] = None,
    ):
        self._stream_id = stream_id
        self._call_id = call_id
        self._auth_id = auth_id
        self._auth_token = auth_token
        self._params = params or VobizFrameSerializer.InputParams()

        self._vobiz_sample_rate = self._params.vobiz_sample_rate
        self._sample_rate = 0

        self._input_resampler = create_stream_resampler()
        self._output_resampler = create_stream_resampler()
        self._hangup_attempted = False

    @property
    def type(self) -> FrameSerializerType:
        return FrameSerializerType.TEXT

    async def setup(self, frame: StartFrame):
        self._sample_rate = self._params.sample_rate or frame.audio_in_sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if (
            self._params.auto_hang_up
            and not self._hangup_attempted
            and isinstance(frame, (EndFrame, CancelFrame))
        ):
            self._hangup_attempted = True
            await self._hang_up_call()
            return None
        if isinstance(frame, InterruptionFrame):
            answer = {"event": "clearAudio", "streamId": self._stream_id}
            return json.dumps(answer)
        if isinstance(frame, AudioRawFrame):
            data = frame.audio
            serialized_data = await pcm_to_ulaw(
                data, frame.sample_rate, self._vobiz_sample_rate, self._output_resampler
            )
            if serialized_data is None or len(serialized_data) == 0:
                return None

            payload = base64.b64encode(serialized_data).decode("utf-8")
            answer = {
                "event": "playAudio",
                "media": {
                    "contentType": "audio/x-mulaw",
                    "sampleRate": self._vobiz_sample_rate,
                    "payload": payload,
                },
                "streamId": self._stream_id,
            }
            return json.dumps(answer)
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return json.dumps(frame.message)
        return None

    async def _hang_up_call(self):
        try:
            auth_id = self._auth_id
            auth_token = self._auth_token
            call_id = self._call_id

            if not call_id or not auth_id or not auth_token:
                missing = []
                if not call_id:
                    missing.append("call_id")
                if not auth_id:
                    missing.append("auth_id")
                if not auth_token:
                    missing.append("auth_token")
                logger.warning(
                    "Cannot hang up Vobiz call: missing required parameters: %s",
                    ", ".join(missing),
                )
                return

            api_base = self._params.api_base.rstrip("/")
            endpoint = f"{api_base}/api/v1/Account/{auth_id}/Call/{call_id}/"
            headers = {
                "X-Auth-ID": auth_id,
                "X-Auth-Token": auth_token,
            }

            async with aiohttp.ClientSession() as session:
                async with session.delete(endpoint, headers=headers) as response:
                    if response.status in (200, 204, 404):
                        logger.debug("Successfully terminated Vobiz call %s", call_id)
                    else:
                        error_text = await response.text()
                        logger.error(
                            "Failed to terminate Vobiz call %s: Status %s, Response: %s",
                            call_id,
                            response.status,
                            error_text,
                        )
        except Exception as e:
            logger.exception("Failed to hang up Vobiz call: %s", e)

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON message: %s", data)
            return None

        if message.get("event") == "media":
            media = message.get("media", {})
            payload_base64 = media.get("payload")
            if not payload_base64:
                return None

            payload = base64.b64decode(payload_base64)
            deserialized_data = await ulaw_to_pcm(
                payload, self._vobiz_sample_rate, self._sample_rate, self._input_resampler
            )
            if deserialized_data is None or len(deserialized_data) == 0:
                return None

            return InputAudioRawFrame(
                audio=deserialized_data,
                num_channels=1,
                sample_rate=self._sample_rate,
            )
        if message.get("event") == "dtmf":
            dtmf_data = message.get("dtmf", {})
            digit = dtmf_data.get("digit")
            if digit:
                try:
                    return InputDTMFFrame(KeypadEntry(digit))
                except ValueError:
                    logger.warning("Invalid DTMF digit received: %s", digit)
                    return None
        return None
