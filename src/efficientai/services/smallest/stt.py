"""Smallest Pulse realtime speech-to-text service implementation."""

import json
from typing import AsyncGenerator, Optional

from loguru import logger
from pydantic import BaseModel

from efficientai.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from efficientai.processors.frame_processor import FrameDirection
from efficientai.services.stt_service import WebsocketSTTService
from efficientai.utils.time import time_now_iso8601
from efficientai.utils.tracing.service_decorators import traced_stt

try:
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error(
        "In order to use Smallest realtime STT, you need to "
        "`pip install efficientai-ai[elevenlabs]` (websockets dependency)."
    )
    raise Exception(f"Missing module: {e}")


class SmallestSTTService(WebsocketSTTService):
    """Realtime STT over Smallest Pulse WebSocket API."""

    class InputParams(BaseModel):
        language: str = "en"
        encoding: str = "linear16"
        word_timestamps: bool = True
        sentence_timestamps: bool = True
        full_transcript: bool = False
        format: bool = True
        diarize: bool = False
        finalize_on_words: bool = True
        eou_timeout_ms: Optional[int] = None

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "pulse-v4",
        base_url: str = "api.smallest.ai",
        sample_rate: Optional[int] = None,
        params: Optional[InputParams] = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._api_key = api_key
        self._base_url = base_url
        self._params = params or SmallestSTTService.InputParams()
        self._receive_task = None
        self._metrics_started = False
        self.set_model_name(model)
        self._settings = {"language": self._params.language}

    def can_generate_metrics(self) -> bool:
        return True

    async def set_language(self, language):
        logger.info(f"Switching Smallest STT language to: [{language}]")
        self._params.language = str(language)
        self._settings["language"] = self._params.language
        await self._disconnect()
        await self._connect()

    async def set_model(self, model: str):
        await super().set_model(model)
        logger.info(f"Switching Smallest STT model to: [{model}]")

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStoppedSpeakingFrame):
            await self._send_finalize_signal()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        if not self._websocket or self._websocket.state is State.CLOSED:
            await self._connect()

        if not audio:
            yield None
            return

        if not self._metrics_started:
            await self.start_ttfb_metrics()
            await self.start_processing_metrics()
            self._metrics_started = True

        try:
            await self.send_with_retry(audio, self._report_error)
        except Exception as e:
            logger.error(f"Failed to send audio chunk to Smallest STT: {e}")
            yield ErrorFrame(error=f"Smallest STT send failed: {e}")
        yield None

    async def _connect(self):
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()
        self._metrics_started = False

    async def _connect_websocket(self):
        if self._websocket and self._websocket.state is State.OPEN:
            return

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "language": self._params.language,
            "encoding": self._params.encoding,
            "sample_rate": str(self.sample_rate or 16000),
            "word_timestamps": str(self._params.word_timestamps).lower(),
            "sentence_timestamps": str(self._params.sentence_timestamps).lower(),
            "full_transcript": str(self._params.full_transcript).lower(),
            "format": str(self._params.format).lower(),
            "diarize": str(self._params.diarize).lower(),
            "finalize_on_words": str(self._params.finalize_on_words).lower(),
        }
        if self._params.eou_timeout_ms is not None:
            headers["eou_timeout_ms"] = str(self._params.eou_timeout_ms)

        ws_url = f"wss://{self._base_url}/waves/v1/pulse/get_text"

        logger.debug("Connecting to Smallest Pulse realtime STT")
        self._websocket = await websocket_connect(ws_url, additional_headers=headers)
        await self._call_event_handler("on_connected")

    async def _disconnect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                logger.debug("Disconnecting from Smallest Pulse realtime STT")
                await self._websocket.close()
        except Exception as e:
            logger.error(f"{self} error closing Smallest websocket: {e}")
        finally:
            self._websocket = None
            await self._call_event_handler("on_disconnected")

    async def _receive_messages(self):
        async for message in self._get_websocket():
            if isinstance(message, (bytes, bytearray)):
                continue
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"Smallest STT returned non-JSON message: {message}")
                continue
            await self._process_response(data)

    async def _process_response(self, data: dict):
        transcript = (data.get("transcript") or "").strip()
        is_final = bool(data.get("is_final"))
        is_last = bool(data.get("is_last"))
        language = data.get("language") or self._params.language

        if transcript:
            await self.stop_ttfb_metrics()

            if is_final:
                await self._handle_transcription(transcript, True, language)
                await self.push_frame(
                    TranscriptionFrame(
                        transcript,
                        self._user_id,
                        time_now_iso8601(),
                        language,
                        result=data,
                    )
                )
                if self._metrics_started:
                    await self.stop_processing_metrics()
                    self._metrics_started = False
            else:
                await self.push_frame(
                    InterimTranscriptionFrame(
                        transcript,
                        self._user_id,
                        time_now_iso8601(),
                        language,
                        result=data,
                    )
                )

        if is_last and self._metrics_started:
            await self.stop_processing_metrics()
            self._metrics_started = False

    async def _send_finalize_signal(self):
        if not self._websocket or self._websocket.state is not State.OPEN:
            return
        try:
            await self._websocket.send(json.dumps({"type": "finalize"}))
        except Exception as e:
            logger.warning(f"Failed to send Smallest finalize signal: {e}")

    async def _report_error(self, error: ErrorFrame):
        await self._call_event_handler("on_connection_error", error.error)
        await self.push_error(error)

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Websocket not connected")

    @traced_stt
    async def _handle_transcription(
        self, transcript: str, is_final: bool, language: Optional[str] = None
    ):
        pass
