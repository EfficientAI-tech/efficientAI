#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Bot FastAPI module - uses lazy imports to avoid loading heavy dependencies at module import.

This module defers importing efficientai services until run_bot() is actually called,
allowing the API/worker to start without loading Google AI SDKs at import time.
"""

import os
import sys
import tempfile
import time

from loguru import logger

from app.services.voice_agent.audio_recorder import get_audio_recorder_class
from app.services.voice_agent.utils.audio_merge import merge_and_upload_audio


def _get_lazy_imports():
    """Lazy import all efficientai dependencies when needed.
    
    Returns a dict with all required classes/functions for the bot.
    This avoids loading heavy AI SDKs at module import time.
    """
    from efficientai.audio.vad.silero import SileroVADAnalyzer
    from efficientai.frames.frames import (
        LLMRunFrame, Frame, AudioRawFrame, OutputAudioRawFrame, 
        TTSAudioRawFrame, EndFrame, StartFrame, CancelFrame
    )
    from efficientai.pipeline.pipeline import Pipeline
    from efficientai.pipeline.runner import PipelineRunner
    from efficientai.pipeline.task import PipelineParams, PipelineTask
    from efficientai.processors.aggregators.llm_context import LLMContext
    from efficientai.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from efficientai.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
    from efficientai.serializers.protobuf import ProtobufFrameSerializer
    from efficientai.services.google.gemini_live.llm import GeminiLiveLLMService
    from efficientai.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )
    from efficientai.processors.frame_processor import FrameProcessor
    
    return {
        "SileroVADAnalyzer": SileroVADAnalyzer,
        "LLMRunFrame": LLMRunFrame,
        "Frame": Frame,
        "AudioRawFrame": AudioRawFrame,
        "OutputAudioRawFrame": OutputAudioRawFrame,
        "TTSAudioRawFrame": TTSAudioRawFrame,
        "EndFrame": EndFrame,
        "StartFrame": StartFrame,
        "CancelFrame": CancelFrame,
        "Pipeline": Pipeline,
        "PipelineRunner": PipelineRunner,
        "PipelineParams": PipelineParams,
        "PipelineTask": PipelineTask,
        "LLMContext": LLMContext,
        "LLMContextAggregatorPair": LLMContextAggregatorPair,
        "RTVIConfig": RTVIConfig,
        "RTVIObserver": RTVIObserver,
        "RTVIProcessor": RTVIProcessor,
        "ProtobufFrameSerializer": ProtobufFrameSerializer,
        "GeminiLiveLLMService": GeminiLiveLLMService,
        "FastAPIWebsocketParams": FastAPIWebsocketParams,
        "FastAPIWebsocketTransport": FastAPIWebsocketTransport,
        "FrameProcessor": FrameProcessor,
    }


# Cache for lazy imports (loaded once, reused)
_imports_cache = None


def _get_imports():
    """Get cached lazy imports."""
    global _imports_cache
    if _imports_cache is None:
        _imports_cache = _get_lazy_imports()
    return _imports_cache



logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

# Default system instruction (used as fallback if no agent description is provided)
DEFAULT_SYSTEM_INSTRUCTION = """
You are Gemini Chatbot, a friendly, helpful robot.
Your goal is to demonstrate your capabilities in a succinct way.
Your output will be converted to audio so don't include special characters in your answers.
Respond to what the user said in a creative and helpful way. Keep your responses brief. One or two sentences at most.
"""


async def run_bot(websocket_client, google_api_key: str, system_instruction: str = None, organization_id: str = None, agent_id: str = None, persona_id: str = None, scenario_id: str = None, evaluator_id: str = None, result_id: str = None, model_name: str = None, serializer=None, telephony_mode: bool = False, call_short_id: str = None, silence_hangup_secs: float | None = None, workspace_id: str = None, persona=None, call_direction: str = "outbound", persona_speaks_via_tts: bool = False):
    """
    Run the voice agent bot with the provided Google API key.
    
    Args:
        websocket_client: WebSocket client connection
        google_api_key: Decrypted Google API key for Gemini
        system_instruction: Optional system instruction (overrides default)
        organization_id: Organization ID for organizing S3 uploads
    """
    # Lazy load all efficientai dependencies
    imports = _get_imports()
    AudioRecorder = get_audio_recorder_class()
    
    # Initialize variables for return values
    call_start_time = time.time()
    s3_key_result = None
    duration_result = None
    transcript_text = None
    conversation_turns = []
    
    try:
        transport_serializer = serializer or imports["ProtobufFrameSerializer"]()
        from app.services.voice_agent.tts_sample_rate import (
            resolve_websocket_audio_in_sample_rate_hz,
            resolve_websocket_audio_out_sample_rate_hz,
        )

        transport_in_sample_rate = resolve_websocket_audio_in_sample_rate_hz(
            telephony_mode=telephony_mode,
        )
        transport_out_sample_rate = resolve_websocket_audio_out_sample_rate_hz(
            telephony_mode=telephony_mode,
        )
        ambient_mixer = None
        ambient_input_processor = None
        if persona is not None and telephony_mode:
            from app.services.audio.ambient_telephony import resolve_ambient_for_telephony
            from app.services.audio.ambient_input_processor import get_ambient_input_processor_class

            ambient_config = await resolve_ambient_for_telephony(
                persona,
                call_direction=call_direction,
                input_sample_rate=transport_in_sample_rate,
                output_sample_rate=transport_out_sample_rate,
                persona_speaks_via_tts=persona_speaks_via_tts,
            )
            ambient_mixer = ambient_config.output_mixer
            if ambient_config.input_bed is not None:
                AmbientInputProcessor = get_ambient_input_processor_class()
                ambient_input_processor = AmbientInputProcessor(ambient_config.input_bed)
        elif persona is not None:
            from app.services.audio.ambient_catalog import resolve_ambient_mixer

            ambient_mixer = await resolve_ambient_mixer(persona, transport_out_sample_rate)
        ws_transport = imports["FastAPIWebsocketTransport"](
            websocket=websocket_client,
            params=imports["FastAPIWebsocketParams"](
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                audio_in_sample_rate=transport_in_sample_rate if telephony_mode else None,
                audio_out_sample_rate=transport_out_sample_rate if telephony_mode else None,
                vad_analyzer=imports["SileroVADAnalyzer"](),
                serializer=transport_serializer,
                audio_out_mixer=ambient_mixer,
            ),
        )

        # Use provided system instruction or fallback to default
        if system_instruction and system_instruction.strip():
            instruction = system_instruction.strip()
        else:
            instruction = DEFAULT_SYSTEM_INSTRUCTION.strip()

        # Validate API key before passing to Gemini
        if not google_api_key or not google_api_key.strip():
            raise ValueError("Google API key is empty or invalid")
        
        # Determine model name
        if model_name:
            if not model_name.startswith("models/"):
                formatted_model_name = f"models/{model_name}"
            else:
                formatted_model_name = model_name
        else:
            formatted_model_name = "models/gemini-2.5-flash-native-audio-preview-12-2025"
        logger.info(f"Using Gemini Live model: {formatted_model_name}")
        
        # Gemini S2S uses native voices (e.g. Puck), not provider voice IDs from Persona/VoiceBundle.
        llm = imports["GeminiLiveLLMService"](
            api_key=google_api_key,
            voice_id="Puck",
            transcribe_model_audio=True,
            system_instruction=instruction,
            model=formatted_model_name,
        )
        context = imports["LLMContext"](
            [
                {
                    "role": "user",
                    "content": "Start by greeting the user warmly and introducing yourself based on the system instruction.",
                }
            ],
        )

        context_aggregator = imports["LLMContextAggregatorPair"](context)

        recorder_sample_rate = 8000 if telephony_mode else 24000

        if telephony_mode:
            from app.services.voice_agent.telephony_recording_paths import telephony_recording_temp_path

            user_audio_path = telephony_recording_temp_path(suffix=".wav")
            bot_audio_path = telephony_recording_temp_path(suffix=".wav")
        else:
            user_audio_fd, user_audio_path = tempfile.mkstemp(suffix=".wav")
            os.close(user_audio_fd)
            bot_audio_fd, bot_audio_path = tempfile.mkstemp(suffix=".wav")
            os.close(bot_audio_fd)
        
        # Use a common start time for synchronization
        start_time = time.time()
        recording_ambient_bed = None
        if telephony_mode and ambient_mixer is not None:
            recording_ambient_bed = ambient_mixer.bed.clone()
        user_recorder = AudioRecorder(
            user_audio_path,
            start_time,
            target_sample_rate=recorder_sample_rate,
            recorder_name="UserAudioRecorder",
            alignment_mode="wall_clock",
            capture="input",
        )
        bot_recorder = AudioRecorder(
            bot_audio_path,
            start_time,
            target_sample_rate=recorder_sample_rate,
            recorder_name="BotAudioRecorder",
            alignment_mode="wall_clock",
            capture="output",
            ambient_bed=recording_ambient_bed,
        )

        from app.services.voice_agent.live_transcript_processor import create_live_transcript_processor

        live_transcript_processor = create_live_transcript_processor(call_short_id) if telephony_mode else None
        user_transcript_processor = live_transcript_processor
        agent_transcript_processor = (
            create_live_transcript_processor(call_short_id) if telephony_mode and call_short_id else None
        )

        pipeline_task_ref: list = []

        async def on_silence_hangup():
            if pipeline_task_ref:
                await pipeline_task_ref[0].cancel()

        silence_hangup_processor = None
        if silence_hangup_secs is not None and silence_hangup_secs > 0:
            from app.services.voice_agent.call_silence_hangup import CallSilenceHangupProcessor

            silence_hangup_processor = CallSilenceHangupProcessor(
                timeout_secs=silence_hangup_secs,
                on_hangup=on_silence_hangup,
            )

        if telephony_mode:
            pipeline_processors = [ws_transport.input()]
            if ambient_input_processor:
                pipeline_processors.append(ambient_input_processor)
            if silence_hangup_processor:
                pipeline_processors.append(silence_hangup_processor)
            pipeline_processors.extend([user_recorder, context_aggregator.user()])
            if user_transcript_processor:
                pipeline_processors.append(user_transcript_processor)
            pipeline_processors.append(llm)
            from app.services.usage.voice_usage_processor import create_llm_usage_recorder

            usage_recorder = create_llm_usage_recorder(
                organization_id=organization_id,
                workspace_id=workspace_id,
                product_section="agents" if agent_id else ("telephony" if telephony_mode else "playground"),
                resource_id=agent_id,
                resource_type="agent" if agent_id else None,
            )
            if usage_recorder:
                pipeline_processors.append(usage_recorder)
            if agent_transcript_processor:
                pipeline_processors.append(agent_transcript_processor)
            pipeline_processors.extend([
                bot_recorder,
                ws_transport.output(),
                context_aggregator.assistant(),
            ])
            pipeline = imports["Pipeline"](pipeline_processors)
            task = imports["PipelineTask"](
                pipeline,
                params=imports["PipelineParams"](
                    enable_metrics=True,
                    enable_usage_metrics=True,
                    audio_in_sample_rate=transport_in_sample_rate,
                    audio_out_sample_rate=transport_out_sample_rate,
                ),
            )
            pipeline_task_ref.append(task)

            @ws_transport.event_handler("on_client_connected")
            async def on_client_connected(transport, client):
                logger.info("Vobiz telephony client connected via WebSocket")
                await task.queue_frames([imports["LLMRunFrame"]()])

            @ws_transport.event_handler("on_client_disconnected")
            async def on_client_disconnected(transport, client):
                logger.info("Vobiz telephony client disconnected")
                await task.cancel()
        else:
            # RTVI events for efficientai client UI
            rtvi = imports["RTVIProcessor"](config=imports["RTVIConfig"](config=[]))

            from app.services.usage.voice_usage_processor import create_llm_usage_recorder

            usage_recorder = create_llm_usage_recorder(
                organization_id=organization_id,
                workspace_id=workspace_id,
                product_section="agents" if agent_id else "playground",
                resource_id=agent_id,
                resource_type="agent" if agent_id else None,
            )
            pipeline_steps = [
                ws_transport.input(),
                user_recorder,
                context_aggregator.user(),
                rtvi,
                llm,
            ]
            if usage_recorder:
                pipeline_steps.append(usage_recorder)
            pipeline_steps.extend(
                [
                    bot_recorder,
                    ws_transport.output(),
                    context_aggregator.assistant(),
                ]
            )
            pipeline = imports["Pipeline"](pipeline_steps)

            task = imports["PipelineTask"](
                pipeline,
                params=imports["PipelineParams"](
                    enable_metrics=True,
                    enable_usage_metrics=True,
                ),
                observers=[imports["RTVIObserver"](rtvi)],
            )

            @rtvi.event_handler("on_client_ready")
            async def on_client_ready(rtvi):
                await rtvi.set_bot_ready()
                await task.queue_frames([imports["LLMRunFrame"]()])

            @ws_transport.event_handler("on_client_connected")
            async def on_client_connected(transport, client):
                logger.info("efficientai client connected via WebSocket")

            @ws_transport.event_handler("on_client_disconnected")
            async def on_client_disconnected(transport, client):
                logger.info("efficientai Client disconnected")
                await task.cancel()

        # Verify WebSocket is still open before starting
        if websocket_client.client_state.name != "CONNECTED":
            raise Exception(f"WebSocket is not in CONNECTED state: {websocket_client.client_state.name}")
        runner = imports["PipelineRunner"](handle_sigint=False)
        
        try:
            await runner.run(task)
        except Exception as run_error:
            logger.error(f"Error in runner.run(): {run_error}", exc_info=True)
            raise
        finally:
            # Close recorders explicitly to ensure files are flushed
            await user_recorder.cleanup()
            await bot_recorder.cleanup()
            s3_key_result, duration_result = merge_and_upload_audio(
                user_audio_path=user_audio_path,
                bot_audio_path=bot_audio_path,
                call_start_time=call_start_time,
                organization_id=organization_id,
                evaluator_id=evaluator_id,
                result_id=result_id,
                call_direction=call_direction if telephony_mode else None,
                user_audio_frames=user_recorder.audio_frames_received,
                bot_audio_frames=bot_recorder.audio_frames_received,
            )
            
            # Extract conversation transcript from the LLM context
            try:
                raw_messages = context.messages if hasattr(context, 'messages') else []
                conversation_turns = []
                transcript_parts = []
                elapsed = 0.0
                for msg in raw_messages:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if not content or role == "system":
                        continue
                    from app.services.telephony.call_recording_lifecycle import is_bootstrap_user_message

                    if role == "user" and is_bootstrap_user_message(content):
                        continue
                    speaker = "user" if role == "user" else "assistant"
                    turn_duration = max(1.0, len(content.split()) * 0.4)
                    conversation_turns.append({
                        "speaker": speaker,
                        "text": content,
                        "start": round(elapsed, 2),
                        "end": round(elapsed + turn_duration, 2),
                    })
                    transcript_parts.append(f"{speaker}: {content}")
                    elapsed += turn_duration
                transcript_text = "\n".join(transcript_parts) if transcript_parts else None
                logger.info(f"Captured {len(conversation_turns)} conversation turns from live Gemini pipeline")
            except Exception as ctx_err:
                logger.warning(f"Failed to extract conversation context: {ctx_err}")
                conversation_turns = []
                transcript_text = None

            if telephony_mode and call_short_id:
                from app.database import SessionLocal
                from app.services.telephony.call_recording_lifecycle import persist_telephony_call_artifacts

                db = SessionLocal()
                try:
                    persist_telephony_call_artifacts(
                        db,
                        call_short_id=call_short_id,
                        conversation_turns=conversation_turns,
                        transcript_text=transcript_text,
                        s3_key=s3_key_result,
                        duration=duration_result,
                    )
                finally:
                    db.close()

    except Exception as e:
        logger.error(f"Error in run_bot: {e}", exc_info=True)
        return {
            "s3_key": s3_key_result,
            "duration": duration_result,
            "agent_id": agent_id,
            "persona_id": persona_id,
            "scenario_id": scenario_id,
            "transcription": transcript_text,
            "speaker_segments": conversation_turns if conversation_turns else None,
            "error": str(e)
        }
    
    metadata = {
        "s3_key": s3_key_result,
        "duration": duration_result,
        "agent_id": agent_id,
        "persona_id": persona_id,
        "scenario_id": scenario_id,
        "transcription": transcript_text,
        "speaker_segments": conversation_turns if conversation_turns else None,
    }
    if not s3_key_result and not transcript_text:
        metadata["error"] = "No audio file was uploaded and no transcript captured"
    return metadata

