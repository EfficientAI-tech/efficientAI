#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
import time
import wave
import uuid

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
from efficientai.processors.audio.audio_buffer_processor import AudioBufferProcessor
from efficientai.runner.types import RunnerArguments
from efficientai.runner.utils import create_transport
from efficientai.serializers.protobuf import ProtobufFrameSerializer
from efficientai.services.cartesia.tts import CartesiaTTSService
from efficientai.services.deepgram.stt import DeepgramSTTService
from efficientai.services.elevenlabs.tts import ElevenLabsHttpTTSService
from efficientai.services.openai.llm import OpenAILLMService
from efficientai.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from efficientai.transports.base_transport import BaseTransport, TransportParams
from efficientai.turns.bot.turn_analyzer_bot_turn_start_strategy import TurnAnalyzerBotTurnStartStrategy
from efficientai.turns.turn_start_strategies import TurnStartStrategies
from app.services.s3_service import s3_service

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Provider Registries  (STT & TTS)
# ---------------------------------------------------------------------------
# Each entry contains:
#   - "env_key"        : environment variable name for the API key
#   - "default_model"  : fallback model name (None if the service doesn't need one)
#   - "factory"        : callable(**kwargs) -> service instance
#
# TTS entries additionally have:
#   - "default_voice"  : fallback voice ID when the voice bundle doesn't specify one
#
# To add a new provider, simply add a dict entry to the relevant registry.
# ---------------------------------------------------------------------------

# ---- STT Providers --------------------------------------------------------
STT_PROVIDERS = {
    "deepgram": {
        "env_key": "DEEPGRAM_API_KEY",
        "default_model": None,  # Deepgram defaults to nova-3-general internally
        "factory": lambda api_key, model: DeepgramSTTService(
            api_key=api_key,
            **({"model": model} if model else {}),
        ),
    },
    # To add a new STT provider, e.g. "assemblyai":
    # "assemblyai": {
    #     "env_key": "ASSEMBLYAI_API_KEY",
    #     "default_model": None,
    #     "factory": lambda api_key, model: AssemblyAISTTService(
    #         api_key=api_key,
    #     ),
    # },
}

DEFAULT_STT_PROVIDER = "deepgram"

# ---- TTS Providers --------------------------------------------------------
TTS_PROVIDERS = {
    "cartesia": {
        "env_key": "CARTESIA_API_KEY",
        "default_voice": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",  # British Reading Lady
        "default_model": None,
        "factory": lambda api_key, voice_id, model: CartesiaTTSService(
            api_key=api_key,
            voice_id=voice_id,
        ),
    },
    "elevenlabs": {
        "env_key": "ELEVENLABS_API_KEY",
        "default_voice": "JBFqnCBsd6RMkjVDRZzb",
        "default_model": "eleven_multilingual_v2",
        "factory": lambda api_key, voice_id, model: ElevenLabsHttpTTSService(
            api_key=api_key,
            voice_id=voice_id,
            model=model,
            aiohttp_session=__import__("aiohttp").ClientSession(),
        ),
    },
    # To add a new TTS provider, e.g. "azure":
    # "azure": {
    #     "env_key": "AZURE_SPEECH_API_KEY",
    #     "default_voice": "en-US-JennyNeural",
    #     "default_model": None,
    #     "factory": lambda api_key, voice_id, model: AzureTTSService(
    #         api_key=api_key,
    #         voice_id=voice_id,
    #     ),
    # },
}

DEFAULT_TTS_PROVIDER = "cartesia"


def _resolve_provider(voice_bundle, attr: str, default: str) -> str:
    """Return the normalised provider name from a voice bundle attribute, falling back to *default*."""
    raw = getattr(voice_bundle, attr, None)
    if raw is None:
        return default
    value = raw.value if hasattr(raw, "value") else str(raw)
    return value.lower()


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
    Uses AudioBufferProcessor for proper conversation audio recording.
    """

    call_start_time = time.time()
    s3_key_result = None
    duration_result = None
    
    # Storage for audio data from the buffer processor
    recorded_audio_data = {"audio": None, "sample_rate": None, "num_channels": None}

    # Resolve STT provider config from the registry
    stt_provider_value = _resolve_provider(voice_bundle, "stt_provider", DEFAULT_STT_PROVIDER)
    stt_cfg = STT_PROVIDERS.get(stt_provider_value)
    if stt_cfg is None:
        supported = ", ".join(sorted(STT_PROVIDERS.keys()))
        raise ValueError(
            f"Unsupported STT provider '{stt_provider_value}'. Supported providers: {supported}"
        )

    # Resolve TTS provider config from the registry
    tts_provider_value = _resolve_provider(voice_bundle, "tts_provider", DEFAULT_TTS_PROVIDER)
    tts_cfg = TTS_PROVIDERS.get(tts_provider_value)
    if tts_cfg is None:
        supported = ", ".join(sorted(TTS_PROVIDERS.keys()))
        raise ValueError(
            f"Unsupported TTS provider '{tts_provider_value}'. Supported providers: {supported}"
        )

    # Resolve API keys: prefer provided values, otherwise fall back to environment
    stt_api_key = stt_api_key or os.getenv(stt_cfg["env_key"])
    tts_api_key = tts_api_key or os.getenv(tts_cfg["env_key"])
    llm_api_key = llm_api_key or os.getenv("OPENAI_API_KEY")

    missing = []
    if not stt_api_key:
        missing.append(stt_cfg["env_key"])
    if not tts_api_key:
        missing.append(tts_cfg["env_key"])
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

        # Instantiate STT service from the provider registry
        stt_model = getattr(voice_bundle, "stt_model", None) or stt_cfg["default_model"]
        stt = stt_cfg["factory"](api_key=stt_api_key, model=stt_model)

        # Instantiate TTS service from the provider registry
        tts_voice_id = getattr(voice_bundle, "tts_voice", None) or tts_cfg["default_voice"]
        tts_model = getattr(voice_bundle, "tts_model", None) or tts_cfg["default_model"]
        tts = tts_cfg["factory"](api_key=tts_api_key, voice_id=tts_voice_id, model=tts_model)

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

        # Use AudioBufferProcessor for proper conversation recording
        # - sample_rate=24000 for consistency with TTS
        # - num_channels=1 for mono (properly mixed user+bot audio via mix_audio)
        # Place it right after transport.input() to capture InputAudioRawFrame
        audio_buffer_input = AudioBufferProcessor(
            sample_rate=24000,
            num_channels=1,
        )
        
        # Second buffer to capture OutputAudioRawFrame (bot audio)
        audio_buffer_output = AudioBufferProcessor(
            sample_rate=24000,
            num_channels=1,
        )
        
        # Track audio from both sources separately, then merge at the end
        input_audio_chunks = []
        output_audio_chunks = []

        # Event handler to capture user (input) audio data
        @audio_buffer_input.event_handler("on_audio_data")
        async def on_input_audio_data(buffer, audio, sample_rate, num_channels):
            logger.debug(f"Input AudioBuffer captured {len(audio)} bytes")
            if audio and len(audio) > 0:
                input_audio_chunks.append(audio)

        # Event handler to capture bot (output) audio data
        @audio_buffer_output.event_handler("on_audio_data")
        async def on_output_audio_data(buffer, audio, sample_rate, num_channels):
            logger.debug(f"Output AudioBuffer captured {len(audio)} bytes")
            if audio and len(audio) > 0:
                output_audio_chunks.append(audio)
            # Store the sample rate/channels for final merge
            recorded_audio_data["sample_rate"] = sample_rate
            recorded_audio_data["num_channels"] = num_channels

        pipeline = Pipeline(
            [
                ws_transport.input(),
                audio_buffer_input,  # Capture user input audio here
                stt,
                context_aggregator.user(),
                rtvi,
                llm,
                tts,
                audio_buffer_output,  # Capture bot output audio here
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
            # Start recording on both buffers when client is ready
            await audio_buffer_input.start_recording()
            await audio_buffer_output.start_recording()
            logger.info("AudioBufferProcessors started recording (input + output)")
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
            # Stop recording and trigger final audio data handlers
            await audio_buffer_input.stop_recording()
            await audio_buffer_output.stop_recording()
            logger.info("AudioBufferProcessors stopped recording")
            
            # Calculate duration
            duration_result = time.time() - call_start_time
            
            # Merge captured audio chunks
            total_input_audio = b''.join(input_audio_chunks) if input_audio_chunks else b''
            total_output_audio = b''.join(output_audio_chunks) if output_audio_chunks else b''
            
            logger.info(f"Input audio: {len(total_input_audio)} bytes, Output audio: {len(total_output_audio)} bytes")
            
            # Upload the recorded audio to S3 if we have data
            if len(total_input_audio) > 100 or len(total_output_audio) > 100:
                try:
                    import io
                    from efficientai.audio.utils import mix_audio
                    
                    # Use the sample rate from the buffer (default to 24000 if not set)
                    sample_rate = recorded_audio_data.get("sample_rate") or 24000
                    num_channels = 1  # Output is always mono mixed audio
                    
                    # Mix the two audio streams into one mono stream
                    # mix_audio handles padding if streams have different lengths
                    mixed_audio = mix_audio(total_input_audio, total_output_audio)
                    logger.info(f"Mixed audio: {len(mixed_audio)} bytes")
                    
                    # Create WAV file in memory and upload to S3
                    wav_buffer = io.BytesIO()
                    with wave.open(wav_buffer, 'wb') as wf:
                        wf.setnchannels(num_channels)
                        wf.setsampwidth(2)  # 16-bit audio
                        wf.setframerate(sample_rate)
                        wf.writeframes(mixed_audio)
                    
                    wav_buffer.seek(0)
                    file_content = wav_buffer.read()
                    
                    file_id = uuid.uuid4()
                    meaningful_id = result_id if result_id else f"{int(time.time())}-{file_id.hex[:8]}"
                    
                    s3_key_result = s3_service.upload_file(
                        file_content=file_content,
                        file_id=file_id,
                        file_format="wav",
                        organization_id=organization_id,
                        evaluator_id=evaluator_id,
                        meaningful_id=meaningful_id,
                    )
                    logger.info(f"✅ Conversation audio uploaded to S3: {s3_key_result}")
                except Exception as e:
                    logger.error(f"Failed to upload audio to S3: {e}", exc_info=True)
            else:
                logger.warning("No audio data captured or audio too small to upload")
                
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