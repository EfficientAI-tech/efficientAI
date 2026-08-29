#
# VoiceMaker TTS service for Pipecat pipeline integration.
#

import base64
import json
from typing import Any, AsyncGenerator, Optional

from loguru import logger
from pydantic import BaseModel

from efficientai.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterruptionFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from efficientai.processors.frame_processor import FrameDirection
from efficientai.services.tts_service import InterruptibleTTSService
from efficientai.utils.tracing.service_decorators import traced_tts

from .http_tts import _infer_language_code

try:
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error("In order to use VoiceMaker, you need the websockets package.")
    raise Exception(f"Missing module: {e}") from e


VOICEMAKER_WS_URL = "wss://developer.voicemaker.in/api/v1/voice/convert"


def normalize_voicemaker_engine(model: Optional[str]) -> Optional[str]:
    """Strip the legacy voicemaker- prefix from an engine name."""
    if model is None:
        return None
    engine = model
    if engine.lower().startswith("voicemaker-"):
        engine = engine[len("voicemaker-") :]
    return engine


def build_voicemaker_ws_payload(
    *,
    text: str,
    voice_id: str,
    language_code: str,
    sample_rate: int,
    engine: Optional[str] = None,
) -> dict[str, Any]:
    """Build a VoiceMaker WebSocket convert payload."""
    payload: dict[str, Any] = {
        "VoiceId": voice_id,
        "Text": text,
        "LanguageCode": language_code,
        "OutputFormat": "wav",
        "SampleRate": str(sample_rate),
    }
    normalized = normalize_voicemaker_engine(engine)
    if normalized:
        payload["Engine"] = normalized
    return payload


def pcm_from_voicemaker_audio(audio_b64: str) -> bytes:
    """Decode a VoiceMaker audio chunk and strip a WAV header when present."""
    audio = base64.b64decode(audio_b64)
    if audio.startswith(b"RIFF") and len(audio) >= 44:
        return audio[44:]
    return audio


class VoiceMakerTTSService(InterruptibleTTSService):
    """VoiceMaker TTS service that streams audio over WebSocket."""

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
        url: str = VOICEMAKER_WS_URL,
        params: Optional[InputParams] = None,
        **kwargs,
    ):
        super().__init__(
            aggregate_sentences=True,
            push_text_frames=True,
            pause_frame_processing=True,
            push_stop_frames=False,
            sample_rate=sample_rate,
            **kwargs,
        )
        self._api_key = api_key
        self._model = model
        self._params = params or VoiceMakerTTSService.InputParams(sample_rate_hz=sample_rate)
        self._websocket_url = url
        self.set_model_name(model)
        self.set_voice(voice_id)
        self._started = False
        self._receive_task = None
        self._disconnecting = False

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        await super().push_frame(frame, direction)
        if isinstance(frame, (TTSStoppedFrame, InterruptionFrame)):
            self._started = False

    async def _connect(self):
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        try:
            self._disconnecting = True
            if self._receive_task:
                await self.cancel_task(self._receive_task, timeout=2.0)
                self._receive_task = None
            await self._disconnect_websocket()
        except Exception as e:
            logger.error(f"{self} exception: {e}")
            await self.push_error(ErrorFrame(error=f"{self} error: {e}"))
        finally:
            self._started = False
            self._websocket = None
            self._disconnecting = False

    async def _connect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return

            self._websocket = await websocket_connect(
                self._websocket_url,
                additional_headers={
                    "Authorization": f"Bearer {self._api_key}",
                },
            )
            logger.debug("Connected to VoiceMaker TTS Websocket")
            await self._call_event_handler("on_connected")
        except Exception as e:
            logger.error(f"{self} exception: {e}")
            await self.push_error(ErrorFrame(error=f"{self} error: {e}"))
            self._websocket = None
            await self._call_event_handler("on_connection_error", f"{e}")

    async def _disconnect_websocket(self):
        try:
            await self.stop_all_metrics()
            if self._websocket:
                logger.debug("Disconnecting from VoiceMaker")
                await self._websocket.close()
        except Exception as e:
            logger.error(f"{self} error closing websocket: {e}")
            await self.push_error(ErrorFrame(error=f"{self} error: {e}"))
        finally:
            self._started = False
            self._websocket = None
            await self._call_event_handler("on_disconnected")

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Websocket not connected")

    def _payload_sample_rate(self) -> int:
        return self.sample_rate or self._init_sample_rate or 24000

    async def _send_text(self, text: str):
        if self._disconnecting:
            logger.warning("Service is disconnecting, ignoring text send")
            return

        if self._websocket and self._websocket.state is State.OPEN:
            payload = build_voicemaker_ws_payload(
                text=text,
                voice_id=self._voice_id,
                language_code=_infer_language_code(self._voice_id),
                sample_rate=self._payload_sample_rate(),
                engine=self._model,
            )
            await self._websocket.send(json.dumps(payload))
        else:
            logger.warning("WebSocket not ready, cannot send text")

    async def _receive_messages(self):
        async for message in self._get_websocket():
            if not isinstance(message, str):
                continue
            msg = json.loads(message)
            if not msg.get("success", False):
                error_msg = msg.get("message") or "VoiceMaker TTS error"
                errors = msg.get("errors") or []
                if errors:
                    error_msg = f"{error_msg}: {'; '.join(str(item) for item in errors)}"
                logger.error(f"TTS Error: {error_msg}")
                await self.push_frame(ErrorFrame(error=error_msg))
                continue

            audio_b64 = msg.get("audio")
            if audio_b64:
                await self.stop_ttfb_metrics()
                pcm = pcm_from_voicemaker_audio(audio_b64)
                if len(pcm) % 2 == 1:
                    pcm = pcm + b"\x00"
                if pcm:
                    await self.push_frame(TTSAudioRawFrame(pcm, self._payload_sample_rate(), 1))

            if msg.get("isFinal"):
                await self.push_frame(TTSStoppedFrame())
                self._started = False

    @traced_tts
    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"Generating VoiceMaker TTS: [{text}]")

        try:
            if not self._websocket or self._websocket.state is State.CLOSED:
                await self._connect()

            try:
                if not self._started:
                    await self.start_ttfb_metrics()
                    yield TTSStartedFrame()
                    self._started = True
                await self._send_text(text)
                await self.start_tts_usage_metrics(text)
            except Exception as e:
                logger.error(f"{self} exception: {e}")
                yield ErrorFrame(error=f"{self} error: {e}")
                yield TTSStoppedFrame()
                await self._disconnect()
                await self._connect()
                return
            yield None
        except Exception as e:
            logger.error(f"{self} exception: {e}")
            yield ErrorFrame(error=f"{self} error: {e}")
