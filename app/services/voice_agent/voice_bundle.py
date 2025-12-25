#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
import tempfile
import time

from dotenv import load_dotenv
from loguru import logger

try:
    from efficientai.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
except Exception as e:  # pragma: no cover
    LocalSmartTurnAnalyzerV3 = None  # Optional dependency; fallback below
    logger.warning(
        "LocalSmartTurnAnalyzerV3 unavailable (missing optional deps like transformers). "
        "Continuing without smart turn analyzer. Error: %s",
        e,
    )
from efficientai.audio.vad.silero import SileroVADAnalyzer
from efficientai.audio.vad.vad_analyzer import VADParams
from efficientai.frames.frames import LLMRunFrame
from efficientai.pipeline.pipeline import Pipeline
from efficientai.pipeline.runner import PipelineRunner
from efficientai.pipeline.task import PipelineParams, PipelineTask
from efficientai.processors.aggregators.llm_context import LLMContext
from efficientai.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from efficientai.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from efficientai.runner.types import RunnerArguments
from efficientai.runner.utils import create_transport
from efficientai.serializers.protobuf import ProtobufFrameSerializer
from efficientai.services.cartesia.tts import CartesiaTTSService
from efficientai.services.deepgram.stt import DeepgramSTTService
from efficientai.services.openai.llm import OpenAILLMService
from efficientai.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from efficientai.transports.base_transport import BaseTransport, TransportParams
from efficientai.turns.bot.turn_analyzer_bot_turn_start_strategy import TurnAnalyzerBotTurnStartStrategy
from efficientai.turns.turn_start_strategies import TurnStartStrategies
from app.services.voice_agent.bot_fast_api import AudioRecorder
from app.services.voice_agent.utils.audio_merge import merge_and_upload_audio

load_dotenv(override=True)

# We store functions so objects (e.g. SileroVADAnalyzer) don't get
# instantiated. The function will be called when the desired transport gets
# selected.
transport_params = {
    "twilio": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info(f"Starting bot")

    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

    messages = [
        {
            "role": "system",
            "content": "You are a helpful LLM in a WebRTC call. Your goal is to demonstrate your capabilities in a succinct way. Your output will be spoken aloud, so avoid special characters that can't easily be spoken, such as emojis or bullet points. Respond to what the user said in a creative and helpful way.",
        },
    ]

    context = LLMContext(messages)
    context_aggregator = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),  # Transport user input
            stt,
            context_aggregator.user(),  # User responses
            llm,  # LLM
            tts,  # TTS
            transport.output(),  # Transport bot output
            context_aggregator.assistant(),  # Assistant spoken responses
        ]
    )

    bot_turn_strategies = []
    if LocalSmartTurnAnalyzerV3:
        bot_turn_strategies = [TurnAnalyzerBotTurnStartStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
    else:
        logger.info("Running without LocalSmartTurnAnalyzerV3 (optional dependency not installed).")

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            turn_start_strategies=TurnStartStrategies(bot=bot_turn_strategies),
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected")
        # Kick off the conversation.
        messages.append({"role": "system", "content": "Please introduce yourself to the user."})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with efficientai Cloud."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


async def run_voice_bundle_fastapi(
    websocket_client,
    system_instruction: str | None = None,
    organization_id: str | None = None,
    agent_id: str | None = None,
    persona_id: str | None = None,
    scenario_id: str | None = None,
    evaluator_id: str | None = None,
    result_id: str | None = None,
    voice_bundle=None,
    stt_api_key: str | None = None,
    tts_api_key: str | None = None,
    llm_api_key: str | None = None,
):
    """
    Run the STT+LLM+TTS voice bundle pipeline over a FastAPI WebSocket.
    Mirrors the S2S path in bot_fast_api but swaps in Deepgram (STT),
    OpenAI (LLM), and Cartesia (TTS).
    """

    call_start_time = time.time()
    s3_key_result = None
    duration_result = None

    # Resolve API keys: prefer provided values, otherwise fall back to environment
    stt_api_key = stt_api_key or os.getenv("DEEPGRAM_API_KEY")
    tts_api_key = tts_api_key or os.getenv("CARTESIA_API_KEY")
    llm_api_key = llm_api_key or os.getenv("OPENAI_API_KEY")

    missing = []
    if not stt_api_key:
        missing.append("DEEPGRAM_API_KEY")
    if not tts_api_key:
        missing.append("CARTESIA_API_KEY")
    if not llm_api_key:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise ValueError(f"Missing required API keys for voice bundle: {', '.join(missing)}")

    try:
        ws_transport = FastAPIWebsocketTransport(
            websocket=websocket_client,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                serializer=ProtobufFrameSerializer(),
            ),
        )

        # Configure STT/LLM/TTS services from the voice bundle when available
        stt = DeepgramSTTService(
            api_key=stt_api_key,
            model=getattr(voice_bundle, "stt_model", None),
        )

        tts_voice_id =  "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc" # British Reading Lady
        tts = CartesiaTTSService(
            api_key=tts_api_key,
            voice_id=tts_voice_id,
        )

        llm_model = getattr(voice_bundle, "llm_model", None) or "gpt-4.1"
        llm = OpenAILLMService(api_key=llm_api_key, model=llm_model)

        # Build context with provided system instruction or a default
        messages = [
            {
                "role": "system",
                "content": (
                    system_instruction.strip()
                    if system_instruction
                    else "You are a helpful voice assistant. Keep responses concise and speakable."
                ),
            },
            {
                "role": "user",
                "content": "Start by greeting the user warmly and introducing yourself based on the system instruction.",
            },
        ]

        context = LLMContext(messages)
        context_aggregator = LLMContextAggregatorPair(context)

        # RTVI events for efficientai client UI
        rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

        # Temporary files for recording user/bot audio (merged later)
        user_audio_fd, user_audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(user_audio_fd)
        bot_audio_fd, bot_audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(bot_audio_fd)

        start_time = time.time()
        user_recorder = AudioRecorder(user_audio_path, start_time, recorder_name="UserAudioRecorder")
        bot_recorder = AudioRecorder(bot_audio_path, start_time, recorder_name="BotAudioRecorder")

        pipeline = Pipeline(
            [
                ws_transport.input(),
                user_recorder,
                stt,
                context_aggregator.user(),
                rtvi,
                llm,
                tts,
                bot_recorder,
                ws_transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=[RTVIObserver(rtvi)],
        )

        @rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            await rtvi.set_bot_ready()
            await task.queue_frames([LLMRunFrame()])

        @ws_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("efficientai client connected via WebSocket (voice bundle)")

        @ws_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("efficientai Client disconnected (voice bundle)")
            await task.cancel()

        if websocket_client.client_state.name != "CONNECTED":
            raise Exception(f"WebSocket is not in CONNECTED state: {websocket_client.client_state.name}")

        runner = PipelineRunner(handle_sigint=False)

        try:
            await runner.run(task)
        finally:
            await user_recorder.cleanup()
            await bot_recorder.cleanup()
            s3_key_result, duration_result = merge_and_upload_audio(
                user_audio_path=user_audio_path,
                bot_audio_path=bot_audio_path,
                call_start_time=call_start_time,
                organization_id=organization_id,
                evaluator_id=evaluator_id,
                result_id=result_id,
            )
    except Exception as e:
        logger.error(f"Error in run_voice_bundle_fastapi: {e}", exc_info=True)
        return {
            "s3_key": s3_key_result,
            "duration": duration_result,
            "agent_id": agent_id,
            "persona_id": persona_id,
            "scenario_id": scenario_id,
            "error": str(e),
        }

    if s3_key_result:
        return {
            "s3_key": s3_key_result,
            "duration": duration_result,
            "agent_id": agent_id,
            "persona_id": persona_id,
            "scenario_id": scenario_id,
        }

    return {
        "s3_key": None,
        "duration": duration_result,
        "agent_id": agent_id,
        "persona_id": persona_id,
        "scenario_id": scenario_id,
        "error": "No audio file was uploaded",
    }


if __name__ == "__main__":
    from efficientai.runner.run import main

    main()