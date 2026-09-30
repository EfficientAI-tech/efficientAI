# Multi-agent Pipecat bot (greeter ↔ support handoff) with EfficientAI Call Traces.
#
# Stack: Fireworks LLM (2 agents), ElevenLabs TTS, STT = ElevenLabs or Deepgram.
#
# .env — copy template, then add provider keys:
#   EXAMPLES="https://raw.githubusercontent.com/EfficientAI-tech/efficientAI/otel-traces/docs/examples"
#   curl -fsSL "$EXAMPLES/pipecat.env.example" -o .env
#   # or: cp /path/to/efficientAI/docs/examples/pipecat.env.example .env
#   # Sandbox (default): EFFICIENTAI_API_BASE + EFFICIENTAI_OTLP_ENDPOINT → sandbox.efficientai.cloud
#   # Local dev only: swap to localhost block in pipecat.env.example (separate workspace UUID)
#   # Or: GET /api/v1/observability/traces/setup → paste env_block (see pipecat-integration docs)
#   FIREWORKS_API_KEY=...
#   ELEVENLABS_API_KEY=...
#   ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM          # optional
#   FIREWORKS_MODEL=accounts/fireworks/models/deepseek-v4-flash-0731  # optional
#   PIPECAT_STT_PROVIDER=elevenlabs                    # or deepgram
#   DEEPGRAM_API_KEY=...                                # when STT=deepgram
#
# Install:
#   uv pip install "pipecat-ai[silero,elevenlabs,fireworks,deepgram,runner,webrtc]>=1.4.0"
#   uv pip install "efficientai[otel] @ git+https://github.com/EfficientAI-tech/efficientAI.git@otel-traces"
#   # or: uv pip install -e '/path/to/efficientAI[otel]' while developing the SDK
#
# Run:
#   curl -fsSL "$EXAMPLES/pipecat_multi_agent_webrtc_tracing.py" -o bot.py
#   uv run bot.py
#   Browser → http://localhost:7860/client → WebRTC → traces in sandbox Calls hub

from dotenv import load_dotenv

load_dotenv(override=True)

import os
from collections import deque
from functools import lru_cache

import httpx

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.bus import BusBridgeProcessor
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.fireworks.llm import FireworksLLMService
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.livekit.transport import LiveKitParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.llm import LLMWorker, LLMWorkerActivationArgs, tool
from pipecat.workers.runner import WorkerRunner

from efficientai.integrations.efficientai_traces import (
    close_trace_session,
    ensure_trace_session,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
    warn_deployment_trace_env,
)

MAIN_NAME = "acme"
GREETER_NAME = "greeter"
SUPPORT_NAME = "support"

DEFAULT_FIREWORKS_MODEL = "accounts/fireworks/models/deepseek-v4-flash-0731"

_PREFERRED_FIREWORKS_MODELS = (
    "accounts/fireworks/models/deepseek-v4-flash-0731",
    "accounts/fireworks/models/kimi-k2p6",
    "accounts/fireworks/models/gpt-oss-120b",
    "accounts/fireworks/models/qwen3p7-plus",
    "accounts/fireworks/models/llama-v3p2-3b-instruct",
)
DEFAULT_ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"

transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
    "websocket": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,
        serializer=ProtobufFrameSerializer(),
    ),
    "livekit": lambda: LiveKitParams(audio_in_enabled=True, audio_out_enabled=True),
}


def _trace_transport(runner_args: RunnerArguments, transport: BaseTransport) -> str:
    return resolve_trace_transport(runner_args, transport)


def _stt_provider() -> str:
    return (os.getenv("PIPECAT_STT_PROVIDER") or "elevenlabs").strip().lower()


def _require_provider_keys() -> None:
    missing = [
        name
        for name in ("FIREWORKS_API_KEY", "ELEVENLABS_API_KEY")
        if not (os.getenv(name) or "").strip()
    ]
    if _stt_provider() == "deepgram" and not (os.getenv("DEEPGRAM_API_KEY") or "").strip():
        missing.append("DEEPGRAM_API_KEY")
    if missing:
        raise ValueError("Missing keys in .env: " + ", ".join(missing))


def _build_stt():
    provider = _stt_provider()
    if provider == "deepgram":
        try:
            from pipecat.services.deepgram.stt import DeepgramSTTService
        except ImportError as exc:
            raise ValueError(
                "Deepgram STT requires compatible packages. Try: "
                "uv pip install 'pipecat-ai[deepgram]' 'deepgram-sdk>=3.0'"
            ) from exc
        logger.info("STT provider: Deepgram")
        return DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])
    if provider != "elevenlabs":
        raise ValueError(
            f"Unknown PIPECAT_STT_PROVIDER={provider!r} (use 'elevenlabs' or 'deepgram')"
        )
    logger.info("STT provider: ElevenLabs")
    return ElevenLabsRealtimeSTTService(api_key=os.environ["ELEVENLABS_API_KEY"])


def _build_tts() -> ElevenLabsTTSService:
    return ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(
            voice=os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_ELEVENLABS_VOICE),
        ),
    )


def _fetch_fireworks_model_ids() -> list[str]:
    api_key = (os.getenv("FIREWORKS_API_KEY") or "").strip()
    if not api_key:
        return []
    try:
        resp = httpx.get(
            "https://api.fireworks.ai/inference/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        return [
            str(m.get("id"))
            for m in (resp.json().get("data") or [])
            if m.get("id")
        ]
    except Exception as exc:
        logger.warning("Could not list Fireworks models: {}", exc)
        return []


@lru_cache(maxsize=1)
def _fireworks_model() -> str:
    explicit = (os.getenv("FIREWORKS_MODEL") or "").strip()
    if explicit:
        return explicit

    available = _fetch_fireworks_model_ids()
    if available:
        avail_set = set(available)
        for candidate in _PREFERRED_FIREWORKS_MODELS:
            if candidate in avail_set:
                logger.info(
                    "Auto-selected Fireworks model {} (override with FIREWORKS_MODEL)",
                    candidate,
                )
                return candidate
        for mid in available:
            low = mid.lower()
            if "/models/" not in mid:
                continue
            if any(skip in low for skip in ("router", "reranker", "embedding")):
                continue
            logger.info(
                "Auto-selected Fireworks model {} (override with FIREWORKS_MODEL)",
                mid,
            )
            return mid

    logger.warning(
        "FIREWORKS_MODEL not set and model list unavailable; falling back to {}",
        DEFAULT_FIREWORKS_MODEL,
    )
    return DEFAULT_FIREWORKS_MODEL


def _fireworks_llm(*, system_instruction: str) -> FireworksLLMService:
    model = _fireworks_model()
    logger.info("LLM provider: Fireworks model={}", model)
    return FireworksLLMService(
        api_key=os.environ["FIREWORKS_API_KEY"],
        settings=FireworksLLMService.Settings(
            model=model,
            system_instruction=system_instruction,
        ),
    )


def _worker_trace_attrs(base: dict[str, str], role: str) -> dict[str, str]:
    return {**base, "efficientai.agent_role": role}


class AcmeLLMWorker(LLMWorker):
    """LLMWorker with tracing enabled (LLMWorker itself does not forward tracing kwargs)."""

    def __init__(
        self,
        name: str,
        *,
        llm: LLMService,
        span_attrs: dict[str, str],
        trace_ctx: dict | None = None,
        bridged: tuple[str, ...] | None = (),
        enable_tracing: bool = True,
    ):
        self._defer_tool_frames = True
        self._tool_call_inflight = 0
        self._deferred_frames: deque = deque()
        self._pending_handover = None
        self._closing = False
        self._trace_ctx = trace_ctx
        self._llm = llm
        self._register_tools(llm)

        PipelineWorker.__init__(
            self,
            Pipeline([self._llm]),
            name=name,
            bridged=bridged,
            enable_rtvi=bridged is None,
            idle_timeout_secs=None,
            enable_tracing=enable_tracing,
            additional_span_attributes=span_attrs if enable_tracing else {},
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
        )
        self._active = False
        self._pending_activation = False

    @tool(cancel_on_interruption=False)
    async def transfer_to_agent(self, params: FunctionCallParams, agent: str, reason: str):
        """Transfer the user to another agent.

        Args:
            agent: Target agent name ('greeter' or 'support').
            reason: Short reason for the handoff.
        """
        logger.info("Worker '{}': transferring to '{}' ({})", self.name, agent, reason)
        await params.result_callback(None)
        await self.activate_worker(
            agent,
            args=LLMWorkerActivationArgs(
                messages=[{"role": "developer", "content": reason}],
            ),
            deactivate_self=True,
        )

    @tool
    async def end_conversation(self, params: FunctionCallParams, reason: str):
        """End the call when the user says goodbye."""
        logger.info("Worker '{}': ending conversation ({})", self.name, reason)
        await params.result_callback(reason)
        if self._trace_ctx:
            await close_trace_session(self._trace_ctx)
        await self.end(reason=reason)


def build_greeter(
    span_attrs: dict[str, str],
    trace_ctx: dict | None = None,
    enable_tracing: bool = True,
) -> AcmeLLMWorker:
    llm = _fireworks_llm(
        system_instruction=(
            "You are a friendly greeter for Acme Corp. Products: Rocket Boots, "
            "Invisible Paint, Tornado Kit. Ask which they want to hear about. "
            "When they pick one or ask product questions, call transfer_to_agent "
            "with agent 'support'. Do not answer product details yourself. "
            "If they say goodbye, call end_conversation. Keep replies to one "
            "or two short spoken sentences. No markdown."
        ),
    )
    return AcmeLLMWorker(
        GREETER_NAME,
        llm=llm,
        span_attrs=_worker_trace_attrs(span_attrs, GREETER_NAME),
        trace_ctx=trace_ctx,
        enable_tracing=enable_tracing,
    )


def build_support(
    span_attrs: dict[str, str],
    trace_ctx: dict | None = None,
    enable_tracing: bool = True,
) -> AcmeLLMWorker:
    llm = _fireworks_llm(
        system_instruction=(
            "You are Acme Corp support. Rocket Boots ($299, up to 60 mph), "
            "Invisible Paint ($49, 24h invisibility), Tornado Kit ($199). "
            "Answer product questions briefly. To browse other products, call "
            "transfer_to_agent with agent 'greeter'. On goodbye, call "
            "end_conversation. Spoken voice only — one or two short sentences."
        ),
    )
    return AcmeLLMWorker(
        SUPPORT_NAME,
        llm=llm,
        span_attrs=_worker_trace_attrs(span_attrs, SUPPORT_NAME),
        trace_ctx=trace_ctx,
        enable_tracing=enable_tracing,
    )


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    _require_provider_keys()

    trace_transport = _trace_transport(runner_args, transport)
    warn_deployment_trace_env()
    trace_ctx = await ensure_trace_session(transport=trace_transport)
    tracing = setup_pipecat_worker_tracing(trace_ctx)
    tracing_on = bool(tracing.get("enabled"))
    span_attrs = tracing.get("additional_span_attributes") or {} if tracing_on else {}
    if tracing_on:
        logger.info(
            "EfficientAI trace session transport={} call_short_id={}",
            trace_transport,
            tracing["call_short_id"],
        )
    else:
        logger.warning("EfficientAI tracing off: {}", trace_ctx.get("error"))

    logger.info(
        "Voice stack: STT={} | TTS=ElevenLabs | LLM=Fireworks ({}) | agents=greeter,support",
        _stt_provider(),
        _fireworks_model(),
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)

    stt = _build_stt()
    tts = _build_tts()

    context = LLMContext()
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    bridge = BusBridgeProcessor(
        bus=runner.bus,
        worker_name=MAIN_NAME,
        name=f"{MAIN_NAME}::BusBridge",
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            bridge,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        name=MAIN_NAME,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        enable_tracing=tracing_on,
        additional_span_attributes=span_attrs,
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )

    await runner.add_workers(
        build_greeter(span_attrs, trace_ctx, tracing_on),
        build_support(span_attrs, trace_ctx, tracing_on),
        worker,
    )

    greeter_activated = False

    async def activate_greeter(reason: str) -> None:
        nonlocal greeter_activated
        if greeter_activated:
            return
        greeter_activated = True
        logger.info("Activating greeter ({})", reason)
        await worker.activate_worker(
            GREETER_NAME,
            args=LLMWorkerActivationArgs(
                messages=[
                    {
                        "role": "developer",
                        "content": (
                            "Welcome the user to Acme Corp, name the three products, "
                            "and ask what they would like to explore."
                        ),
                    },
                ],
            ),
        )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        await activate_greeter("on_client_connected")

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant_id):
        await activate_greeter(f"on_first_participant_joined:{participant_id}")

    @transport.event_handler("on_audio_track_subscribed")
    async def on_audio_track_subscribed(transport, participant_id):
        await activate_greeter(f"on_audio_track_subscribed:{participant_id}")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await runner.cancel()
        await close_trace_session(trace_ctx)

    try:
        await runner.run()
    finally:
        # end_conversation can finish the bot before the dev UI closes the socket;
        # always flush OTLP and close the EfficientAI session row.
        await close_trace_session(trace_ctx)


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
