# Gemini Live + WebRTC and WebSocket transports with EfficientAI OTLP export.
#
# WebRTC: http://localhost:7860/client → **WebRTC** → Connect
# Protobuf WS client (optional): cd client && npm run dev → http://localhost:5173
# This file enables both transports in transport_params.
#
# .env:
#   cp /path/to/efficientAI/docs/examples/pipecat.env.example .env
#   GOOGLE_API_KEY=...
#
# Install:
#   uv pip install "pipecat-ai[silero,websocket,google,runner,webrtc]>=1.4.0"
#   uv pip install "efficientai[otel] @ git+https://github.com/EfficientAI-tech/efficientAI.git"
#
# Run:
#   cp /path/to/efficientAI/docs/examples/pipecat_upstream_websocket_tracing.py bot.py
#   uv run bot.py

from dotenv import load_dotenv

load_dotenv(override=True)

import os

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
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner

from efficientai.integrations.efficientai_traces import (
    close_trace_session,
    ensure_trace_session,
    resolve_trace_transport,
    setup_pipecat_worker_tracing,
    warn_deployment_trace_env,
)

SYSTEM_INSTRUCTION = """
You are Gemini Chatbot, a friendly, helpful robot.
Keep responses brief — one or two sentences.
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


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    trace_transport = _trace_transport(runner_args, transport)
    warn_deployment_trace_env()
    trace_ctx = await ensure_trace_session(transport=trace_transport)
    tracing = setup_pipecat_worker_tracing(trace_ctx)
    if not tracing.get("enabled"):
        logger.warning("EfficientAI tracing off: {}", trace_ctx.get("error"))
    logger.info(
        "EfficientAI trace session transport={} call_short_id={}",
        trace_transport,
        tracing["call_short_id"],
    )

    llm = GeminiLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        settings=GeminiLiveLLMService.Settings(
            voice="Puck",
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        realtime_service_mode=True,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            user_aggregator,
            llm,
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
        enable_tracing=bool(tracing.get("enabled")),
        additional_span_attributes=tracing.get("additional_span_attributes") or {},
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info("Pipecat client ready.")
        context.add_message({"role": "developer", "content": "Start by introducing yourself."})
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Pipecat client connected (transport={})", trace_transport)

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
