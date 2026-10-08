"""Streaming TTS for the simulation test agent.

Runs the same pipecat TTS service the voice-bundle telephony pipeline uses
(built by ``voice_bundle._instantiate_tts_service``) in a tiny standalone
pipeline, so the test agent gets each sentence's audio as the provider
streams it instead of waiting for a whole clip over plain HTTP.

Segments are synthesized one at a time: the next sentence is requested as
soon as the provider signals the previous one is complete (TTSStoppedFrame),
which is usually well before it has finished playing, so synthesis still
overlaps playback. Waiting for the provider's own completion signal (not an
audio gap) keeps a mid-sentence pause from splitting or truncating a sentence.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Optional

import numpy as np
from loguru import logger

# A segment ends on the provider's TTSStoppedFrame. Services without an explicit
# completion message (Sarvam WS, ElevenLabs HTTP) emit it after this much audio
# silence (pipecat's default is 2 s); lowered so the next sentence is requested
# sooner, still well above normal inter-chunk gaps.
PROVIDER_STOP_TIMEOUT_S = 1.0
# Safety net if a provider never sends a stop frame.
SEGMENT_IDLE_FALLBACK_S = 8.0
FIRST_AUDIO_TIMEOUT_S = 6.0

_STOPPED = object()


def _default_service_factory(
    provider: str,
    api_key: str,
    voice_id: Optional[str],
    model: Optional[str],
    sample_rate: Optional[int],
    elevenlabs_api_base_url: Optional[str],
) -> Any:
    from app.services.voice_agent.voice_bundle import _get_tts_providers, _instantiate_tts_service

    tts_cfg = _get_tts_providers().get(provider)
    if not tts_cfg:
        raise ValueError(f"Unsupported TTS provider '{provider}'")
    return _instantiate_tts_service(
        provider,
        tts_cfg,
        api_key=api_key,
        voice_id=voice_id or tts_cfg["default_voice"],
        model=model or tts_cfg["default_model"],
        sample_rate=sample_rate,
        elevenlabs_api_base_url=elevenlabs_api_base_url if provider == "elevenlabs" else None,
    )


def _service_sample_rate(provider: str, target_rate: int) -> Optional[int]:
    """Ask the provider for the bridge rate when it supports it; else its default."""
    from app.services.voice_agent.tts_sample_rate import (
        provider_accepts_sample_rate_kwarg,
        tts_sample_rates_for_provider,
    )

    if provider_accepts_sample_rate_kwarg(provider) and target_rate in tts_sample_rates_for_provider(provider):
        return target_rate
    return None


class AgentTTSStreamer:
    """Stream TTS audio for test-agent sentences through a pipecat TTS service."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        sample_rate: int,
        voice_id: Optional[str] = None,
        model: Optional[str] = None,
        elevenlabs_api_base_url: Optional[str] = None,
        service_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.provider = (provider or "").lower()
        self.sample_rate = sample_rate
        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model
        self._elevenlabs_api_base_url = elevenlabs_api_base_url
        self._service_factory = service_factory or _default_service_factory

        self._tts: Any = None
        self._task: Any = None
        self._runner_task: Optional[asyncio.Task] = None
        self._started = asyncio.Event()
        self._healthy = False
        self._lock = asyncio.Lock()
        # Audio for the segment currently being synthesized; None drops audio
        # (e.g. stale audio still arriving after a barge-in).
        self._active: Optional[asyncio.Queue] = None
        self._bot_speaking = False

    @property
    def healthy(self) -> bool:
        return self._healthy and self._runner_task is not None and not self._runner_task.done()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, timeout: float = 10.0) -> bool:
        try:
            from efficientai.frames.frames import ErrorFrame, TTSAudioRawFrame, TTSStoppedFrame
            from efficientai.pipeline.pipeline import Pipeline
            from efficientai.pipeline.runner import PipelineRunner
            from efficientai.pipeline.task import PipelineParams, PipelineTask
            from efficientai.processors.frame_processor import FrameDirection, FrameProcessor

            streamer = self

            class _AudioSink(FrameProcessor):
                async def process_frame(self, frame, direction: FrameDirection):
                    await super().process_frame(frame, direction)
                    if isinstance(frame, TTSAudioRawFrame):
                        streamer._on_audio(frame.audio, frame.sample_rate)
                    elif isinstance(frame, TTSStoppedFrame):
                        streamer._on_stopped()
                    elif isinstance(frame, ErrorFrame):
                        streamer._on_error(frame.error)
                    await self.push_frame(frame, direction)

            tts = self._service_factory(
                self.provider,
                self._api_key,
                self._voice_id,
                self._model,
                _service_sample_rate(self.provider, self.sample_rate),
                self._elevenlabs_api_base_url,
            )
            # There is no output transport to send BotStoppedSpeakingFrame, so
            # services that pause between utterances would block forever.
            if hasattr(tts, "_pause_frame_processing"):
                tts._pause_frame_processing = False
            if getattr(tts, "_push_stop_frames", False):
                tts._stop_frame_timeout_s = PROVIDER_STOP_TIMEOUT_S
            self._tts = tts

            self._task = PipelineTask(
                Pipeline([tts, _AudioSink()]),
                params=PipelineParams(audio_out_sample_rate=self.sample_rate, allow_interruptions=True),
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
                name=f"agent-tts-{self.provider}",
            )
            await asyncio.wait_for(self._started.wait(), timeout=timeout)
            logger.info(f"[AgentTTS] Started streaming {self.provider} TTS at {self.sample_rate} Hz")
            return self.healthy
        except Exception as e:
            logger.warning(f"[AgentTTS] Failed to start {self.provider} streaming TTS: {e}")
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
        # voice_bundle creates an aiohttp session for ElevenLabs HTTP and never closes it.
        session = getattr(self._tts, "_session", None)
        if session is not None and hasattr(session, "closed") and not session.closed:
            try:
                await session.close()
            except Exception:
                pass

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
    # Synthesis
    # ------------------------------------------------------------------

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield 16-bit mono PCM at ``sample_rate`` for ``text`` as it streams in.

        Raises RuntimeError if the service errors before producing any audio,
        so callers can fall back to one-shot TTS for that segment.
        """
        from efficientai.frames.frames import BotStartedSpeakingFrame, TTSSpeakFrame

        async with self._lock:
            queue: asyncio.Queue = asyncio.Queue()
            self._active = queue
            try:
                if not self._bot_speaking:
                    # Lets interruptible (websocket) services reset on barge-in.
                    self._bot_speaking = True
                    await self._task.queue_frame(BotStartedSpeakingFrame())
                await self._task.queue_frame(TTSSpeakFrame(text))

                got_audio = False
                while True:
                    timeout = SEGMENT_IDLE_FALLBACK_S if got_audio else FIRST_AUDIO_TIMEOUT_S
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        if not got_audio:
                            raise RuntimeError(f"no audio within {FIRST_AUDIO_TIMEOUT_S:.0f}s")
                        logger.warning(
                            f"[AgentTTS] {self.provider} sent no stop frame within "
                            f"{SEGMENT_IDLE_FALLBACK_S:.0f}s of audio; ending segment"
                        )
                        return
                    if item is _STOPPED:
                        if got_audio:
                            return
                        # A stop before any audio is stale (from an interrupted
                        # segment); keep waiting for this segment's audio.
                        continue
                    if isinstance(item, Exception):
                        if not got_audio:
                            raise RuntimeError(str(item))
                        logger.warning(f"[AgentTTS] {self.provider} error mid-segment: {item}")
                        return
                    got_audio = True
                    yield item
            finally:
                self._active = None

    async def finish_utterance(self) -> None:
        """Call after the last segment of a reply has played."""
        from efficientai.frames.frames import BotStoppedSpeakingFrame

        if self._bot_speaking and self._task is not None:
            self._bot_speaking = False
            try:
                await self._task.queue_frame(BotStoppedSpeakingFrame())
            except Exception:
                pass

    async def interrupt(self) -> None:
        """Barge-in: stop the provider and drop any audio still in flight."""
        from efficientai.frames.frames import InterruptionFrame

        self._active = None
        if self._task is None or not self.healthy:
            return
        try:
            await self._task.queue_frame(InterruptionFrame())
        except Exception as e:
            logger.debug(f"[AgentTTS] interrupt failed: {e}")
        await self.finish_utterance()

    # ------------------------------------------------------------------
    # Sink callbacks
    # ------------------------------------------------------------------

    def _on_audio(self, audio: bytes, rate: int) -> None:
        queue = self._active
        if queue is None or not audio:
            return
        if rate and rate != self.sample_rate:
            from app.services.audio.ambient_mixer import resample_mono_int16

            audio = resample_mono_int16(np.frombuffer(audio, dtype=np.int16), rate, self.sample_rate).tobytes()
        queue.put_nowait(audio)

    def _on_stopped(self) -> None:
        queue = self._active
        if queue is not None:
            queue.put_nowait(_STOPPED)

    def _on_error(self, error: Any) -> None:
        logger.warning(f"[AgentTTS] {self.provider} TTS error: {error}")
        queue = self._active
        if queue is not None:
            queue.put_nowait(RuntimeError(str(error)))
