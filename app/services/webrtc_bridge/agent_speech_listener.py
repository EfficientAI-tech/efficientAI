"""
Streaming STT over the production agent's audio during synthetic tests.

The test agent should react to what it actually *hears*, not to the
provider's LLM text. This wraps an efficientai streaming STT service in a
tiny ``Pipeline([stt, sink])`` and exposes a turn-oriented API:

- ``push_audio(pcm)`` for every (real-time paced) inbound frame
- ``finalize_turn(timeout)`` once our turn detector says the agent stopped;
  it forces the STT to finalize and returns the transcript for that turn

If the STT cannot start or errors mid-call, ``healthy`` turns False and the
caller is expected to fall back to provider text.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, List, Optional

from loguru import logger

DEFAULT_STT_PROVIDER = "deepgram"
BYTES_PER_SAMPLE = 2

# After a forced finalize, how long to wait for trailing finals to settle once
# there is no un-finalized interim text left.
FINAL_SETTLE_S = 0.1

# Trailing silence pushed at end of turn. The bridge only forwards agent speech,
# so server-side-VAD STTs (Sarvam) otherwise never see a pause and hold the
# final until the next turn's audio arrives.
END_OF_TURN_SILENCE_S = 0.6
SILENCE_FRAME_S = 0.02

ServiceFactory = Callable[[str, str, Optional[str], Optional[str]], Any]


def _default_service_factory(
    provider: str, api_key: str, model: Optional[str], base_url: Optional[str]
) -> Any:
    from app.services.voice_agent.voice_bundle import (
        _elevenlabs_realtime_stt_factory,
        _get_stt_providers,
    )

    entry = _get_stt_providers().get(provider)
    if not entry:
        raise ValueError(f"Unsupported streaming STT provider '{provider}'")
    model = model or entry["default_model"]
    if provider == "elevenlabs":
        return _elevenlabs_realtime_stt_factory(api_key, model, base_url)
    return entry["factory"](api_key=api_key, model=model)


class AgentSpeechListener:
    """Transcribes the production agent's speech turn by turn."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        model: Optional[str] = None,
        sample_rate: int = 16000,
        base_url: Optional[str] = None,
        service_factory: Optional[ServiceFactory] = None,
        on_usage: Optional[Callable[[float], None]] = None,
    ):
        self.provider = (provider or DEFAULT_STT_PROVIDER).lower()
        self.model = model
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._base_url = base_url
        self._service_factory = service_factory or _default_service_factory
        self._on_usage = on_usage

        self._task = None
        self._runner_task: Optional[asyncio.Task] = None
        self._healthy = False
        self._started = asyncio.Event()

        self._in_turn = False
        self._stt: Any = None
        self._finals: List[str] = []
        self._pending_interim = ""
        self._final_event = asyncio.Event()
        self._audio_bytes = 0

    @property
    def healthy(self) -> bool:
        return self._healthy and self._runner_task is not None and not self._runner_task.done()

    @property
    def audio_seconds(self) -> float:
        return self._audio_bytes / (self._sample_rate * BYTES_PER_SAMPLE)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, timeout: float = 10.0) -> bool:
        try:
            from efficientai.frames.frames import (
                ErrorFrame,
                InterimTranscriptionFrame,
                TranscriptionFrame,
            )
            from efficientai.pipeline.pipeline import Pipeline
            from efficientai.pipeline.runner import PipelineRunner
            from efficientai.pipeline.task import PipelineParams, PipelineTask
            from efficientai.processors.frame_processor import FrameDirection, FrameProcessor

            listener = self

            class _TranscriptSink(FrameProcessor):
                async def process_frame(self, frame, direction: FrameDirection):
                    await super().process_frame(frame, direction)
                    if isinstance(frame, InterimTranscriptionFrame):
                        listener._on_interim(frame.text)
                    elif isinstance(frame, TranscriptionFrame):
                        listener._on_final(frame.text)
                    elif isinstance(frame, ErrorFrame):
                        listener._on_error(frame.error)
                    await self.push_frame(frame, direction)

            stt = self._service_factory(self.provider, self._api_key, self.model, self._base_url)
            self._stt = stt
            self._task = PipelineTask(
                Pipeline([stt, _TranscriptSink()]),
                params=PipelineParams(audio_in_sample_rate=self._sample_rate),
                idle_timeout_secs=None,
            )

            @self._task.event_handler("on_pipeline_started")
            async def _on_started(task, frame):
                self._started.set()

            @self._task.event_handler("on_pipeline_error")
            async def _on_pipeline_error(task, frame):
                self._on_error(getattr(frame, "error", frame))

            self._healthy = True
            self._runner_task = asyncio.create_task(
                PipelineRunner(handle_sigint=False).run(self._task),
                name=f"agent-stt-{self.provider}",
            )
            await asyncio.wait_for(self._started.wait(), timeout=timeout)
            logger.info(f"[AgentSTT] Started {self.provider} STT (model={self.model or 'default'})")
            return self.healthy
        except Exception as e:
            logger.warning(f"[AgentSTT] Failed to start {self.provider} STT: {e}")
            self._healthy = False
            await self._cancel_runner()
            return False

    async def close(self) -> None:
        if self._task is not None and self.healthy:
            try:
                from efficientai.frames.frames import EndFrame

                await self._task.queue_frame(EndFrame())
                await asyncio.wait_for(asyncio.shield(self._runner_task), timeout=5.0)
            except Exception:
                pass
        await self._cancel_runner()
        self._healthy = False

        if self._on_usage and self._audio_bytes:
            try:
                self._on_usage(self.audio_seconds)
            except Exception as e:
                logger.debug(f"[AgentSTT] usage record skipped: {e}")

    async def _cancel_runner(self) -> None:
        if self._runner_task and not self._runner_task.done():
            if self._task is not None:
                try:
                    await self._task.cancel()
                except Exception:
                    pass
            self._runner_task.cancel()
            try:
                await self._runner_task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------
    # Audio and turns
    # ------------------------------------------------------------------

    async def push_audio(self, pcm: bytes) -> None:
        if not pcm or not self.healthy:
            return
        from efficientai.frames.frames import InputAudioRawFrame, UserStartedSpeakingFrame

        try:
            if not self._in_turn:
                self._in_turn = True
                # Finals that landed after the previous finalize timed out belong
                # to the previous turn; never hand them to this one.
                if self._finals or self._pending_interim:
                    logger.debug(
                        f"[AgentSTT] Dropping {len(self._finals)} late final(s) from previous turn"
                    )
                self._finals.clear()
                self._pending_interim = ""
                await self._task.queue_frame(UserStartedSpeakingFrame())
            await self._task.queue_frame(
                InputAudioRawFrame(audio=pcm, sample_rate=self._sample_rate, num_channels=1)
            )
            self._audio_bytes += len(pcm)
        except Exception as e:
            self._on_error(e)

    async def _push_trailing_silence(self) -> None:
        from efficientai.frames.frames import InputAudioRawFrame

        frame_bytes = int(self._sample_rate * SILENCE_FRAME_S) * BYTES_PER_SAMPLE
        silence = b"\x00" * frame_bytes
        for _ in range(int(END_OF_TURN_SILENCE_S / SILENCE_FRAME_S)):
            await self._task.queue_frame(
                InputAudioRawFrame(audio=silence, sample_rate=self._sample_rate, num_channels=1)
            )

    async def _request_server_flush(self) -> None:
        """Ask STTs with a native flush (Sarvam) to finalize buffered audio now."""
        client = getattr(self._stt, "_socket_client", None)
        flush = getattr(client, "flush", None)
        if flush is None:
            return
        try:
            await flush()
        except Exception as e:
            logger.debug(f"[AgentSTT] {self.provider} flush failed: {e}")

    async def finalize_turn(self, timeout: float = 0.5) -> Optional[str]:
        """Force the STT to finalize and return what was heard this turn."""
        if self._task is None:
            return None

        if self._in_turn and self.healthy:
            from efficientai.frames.frames import UserStoppedSpeakingFrame

            self._in_turn = False
            self._final_event.clear()
            try:
                await self._push_trailing_silence()
                await self._task.queue_frame(UserStoppedSpeakingFrame())
                await self._request_server_flush()
            except Exception as e:
                self._on_error(e)

            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            if self._pending_interim or not self._finals:
                # Wait for the finalize response to the outstanding speech.
                try:
                    await asyncio.wait_for(self._final_event.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.debug(f"[AgentSTT] No final within {timeout:.1f}s; using partials")
            # Let back-to-back final segments land.
            remaining = deadline - loop.time()
            if remaining > 0:
                await asyncio.sleep(min(FINAL_SETTLE_S, remaining))

        parts = list(self._finals)
        if self._pending_interim:
            parts.append(self._pending_interim)
        self._finals.clear()
        self._pending_interim = ""
        text = " ".join(p.strip() for p in parts if p and p.strip()).strip()
        return text or None

    # ------------------------------------------------------------------
    # Sink callbacks
    # ------------------------------------------------------------------

    def _on_interim(self, text: str) -> None:
        self._pending_interim = (text or "").strip()

    def _on_final(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._finals.append(text)
        self._pending_interim = ""
        self._final_event.set()

    def _on_error(self, error: Any) -> None:
        if self._healthy:
            logger.warning(f"[AgentSTT] {self.provider} STT error, falling back to provider text: {error}")
        self._healthy = False
        self._final_event.set()
