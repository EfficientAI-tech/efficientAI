# Multi-provider Pipecat bot (STT + LLM + TTS) with EfficientAI observability.
#
# This matches how prod customers run: separate APIs per component → real STT/LLM/TTS spans.
#
# One-time setup (pipecat-examples/websocket/.env):
#   DEEPGRAM_API_KEY=...
#   OPENAI_API_KEY=...
#   CARTESIA_API_KEY=...
#   EFFICIENTAI_API_KEY=<workspace api key>
#   EFFICIENTAI_WORKSPACE_ID=<workspace uuid>
#
# Install:
#   cd ~/Downloads/work/pipecat-examples/websocket
#   uv pip install "pipecat-ai[silero,websocket,deepgram,openai,cartesia,runner,webrtc]>=1.4.0"
#   uv pip install -e '/home/sami/Downloads/work/efficientAI[otel]'
#
# Run:
#   cp /path/to/efficientAI/docs/examples/pipecat_multi_provider_webrtc_tracing.py bot.py
#   uv run bot.py
#   Browser → http://localhost:7860/client → WebRTC → Connect

import os

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner

from efficientai.integrations.efficientai_traces import (
    close_trace_session,
    ensure_trace_session,
    require_deployment_trace_env,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
)

load_dotenv(override=True)
require_deployment_trace_env()

SYSTEM_INSTRUCTION = """
You are a helpful voice assistant. Keep responses to one or two short sentences.
Do not use markdown, bullets, or emojis — your reply is spoken aloud.
"""

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
}


def _trace_transport(runner_args: RunnerArguments, transport: BaseTransport) -> str:
    return resolve_trace_transport(runner_args, transport)


def _require_provider_keys() -> None:
    missing = [
        name
        for name in ("DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY")
        if not (os.getenv(name) or "").strip()
    ]
    if missing:
        raise ValueError(
            "Missing voice provider keys in .env: "
            + ", ".join(missing)
            + ". Get free/trial keys from Deepgram, OpenAI, and Cartesia."
        )


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    _require_provider_keys()

    trace_transport = _trace_transport(runner_args, transport)
    trace_ctx = await ensure_trace_session(transport=trace_transport)
    tracing = setup_pipecat_worker_tracing(trace_ctx)
    logger.info(
        "EfficientAI trace session transport={} call_short_id={}",
        trace_transport,
        tracing["call_short_id"],
    )

    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAILLMService.Settings(
            model="gpt-4o-mini",
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        settings=CartesiaTTSService.Settings(
            voice=os.getenv("CARTESIA_VOICE_ID", "71a7ad14-091c-4e8e-a314-022ece01c121"),
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        enable_tracing=True,
        additional_span_attributes=tracing["additional_span_attributes"],
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info("Pipecat client ready.")
        context.add_message(
            {"role": "developer", "content": "Greet the user briefly and ask how you can help."}
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Pipecat client disconnected")
        await worker.cancel()
        await close_trace_session(trace_ctx)

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
