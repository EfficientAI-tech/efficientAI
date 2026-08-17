#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Bot FastAPI module - uses lazy imports to avoid loading heavy dependencies at module import.

This module defers importing efficientai services until run_bot() is actually called,
allowing the API/worker to start without loading Google AI SDKs at import time.
"""

import sys
import time

from loguru import logger


def _get_lazy_imports():
    """Lazy import all efficientai dependencies when needed.

    Returns a dict with all required classes/functions for the bot.
    This avoids loading heavy AI SDKs at module import time.
    """
    from efficientai.audio.vad.silero import SileroVADAnalyzer
    from efficientai.frames.frames import LLMRunFrame
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

    return {
        "SileroVADAnalyzer": SileroVADAnalyzer,
        "LLMRunFrame": LLMRunFrame,
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


async def run_bot(
    websocket_client,
    google_api_key: str,
    system_instruction: str = None,
    organization_id: str = None,
    agent_id: str = None,
    persona_id: str = None,
    scenario_id: str = None,
    evaluator_id: str = None,
    result_id: str = None,
    model_name: str = None,
    serializer=None,
    telephony_mode: bool = False,
    call_short_id: str = None,
    silence_hangup_secs: float | None = None,
):
    """
    Run the voice agent bot with the provided Google API key.

    Args:
        websocket_client: WebSocket client connection
        google_api_key: Decrypted Google API key for Gemini
        system_instruction: Optional system instruction (overrides default)
        organization_id: Organization ID for organizing S3 uploads
    """
    imports = _get_imports()

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
            ),
        )

        if system_instruction and system_instruction.strip():
            instruction = system_instruction.strip()
        else:
            instruction = DEFAULT_SYSTEM_INSTRUCTION.strip()

        if not google_api_key or not google_api_key.strip():
            raise ValueError("Google API key is empty or invalid")

        if model_name:
            formatted_model_name = (
                model_name if model_name.startswith("models/") else f"models/{model_name}"
            )
        else:
            formatted_model_name = "models/gemini-2.5-flash-native-audio-preview-12-2025"
        logger.info(f"Using Gemini Live model: {formatted_model_name}")

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
        from app.services.voice_agent.conversation_recording import (
            ConversationRecordingCapture,
            RecordingTimeline,
            create_wall_clock_track_tap,
        )

        recording_capture = ConversationRecordingCapture()
        recording_timeline = RecordingTimeline()
        user_track_tap = create_wall_clock_track_tap(
            recording_capture,
            recording_timeline,
            track="user",
            sample_rate=recorder_sample_rate,
        )
        bot_track_tap = create_wall_clock_track_tap(
            recording_capture,
            recording_timeline,
            track="bot",
            sample_rate=recorder_sample_rate,
        )

        from app.services.voice_agent.live_transcript_processor import create_live_transcript_processor

        user_transcript_processor = (
            create_live_transcript_processor(call_short_id) if telephony_mode else None
        )
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
            if silence_hangup_processor:
                pipeline_processors.append(silence_hangup_processor)
            pipeline_processors.append(user_track_tap)
            pipeline_processors.append(context_aggregator.user())
            if user_transcript_processor:
                pipeline_processors.append(user_transcript_processor)
            pipeline_processors.append(llm)
            if agent_transcript_processor:
                pipeline_processors.append(agent_transcript_processor)
            pipeline_processors.extend([
                ws_transport.output(),
                bot_track_tap,
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
                recording_timeline.mark_started()
                await task.queue_frames([imports["LLMRunFrame"]()])

            @ws_transport.event_handler("on_client_disconnected")
            async def on_client_disconnected(transport, client):
                logger.info("Vobiz telephony client disconnected")
                await task.cancel()
        else:
            rtvi = imports["RTVIProcessor"](config=imports["RTVIConfig"](config=[]))

            pipeline = imports["Pipeline"](
                [
                    ws_transport.input(),
                    user_track_tap,
                    context_aggregator.user(),
                    rtvi,
                    llm,
                    ws_transport.output(),
                    bot_track_tap,
                    context_aggregator.assistant(),
                ]
            )

            task = imports["PipelineTask"](
                pipeline,
                params=imports["PipelineParams"](
                    enable_metrics=True,
                    enable_usage_metrics=True,
                ),
                observers=[imports["RTVIObserver"](rtvi)],
            )

            @ws_transport.event_handler("on_client_connected")
            async def on_client_connected(transport, client):
                logger.info("efficientai client connected via WebSocket")
                recording_timeline.mark_started()

            @rtvi.event_handler("on_client_ready")
            async def on_client_ready(rtvi):
                await rtvi.set_bot_ready()
                recording_timeline.mark_started()
                await task.queue_frames([imports["LLMRunFrame"]()])

            @ws_transport.event_handler("on_client_disconnected")
            async def on_client_disconnected(transport, client):
                logger.info("efficientai Client disconnected")
                await task.cancel()

        if websocket_client.client_state.name != "CONNECTED":
            raise Exception(f"WebSocket is not in CONNECTED state: {websocket_client.client_state.name}")
        runner = imports["PipelineRunner"](handle_sigint=False)

        try:
            await runner.run(task)
        except Exception as run_error:
            logger.error(f"Error in runner.run(): {run_error}", exc_info=True)
            raise
        finally:
            recording_metadata: dict = {}
            logger.info(
                "Gemini conversation recording stopped: user={} bytes bot={} bytes",
                len(recording_capture.user_audio),
                len(recording_capture.bot_audio),
            )

            if recording_capture.has_audio():
                from app.services.voice_agent.conversation_recording import upload_conversation_recording

                s3_key_result, duration_result, recording_metadata = upload_conversation_recording(
                    recording_capture,
                    call_start_time=call_start_time,
                    organization_id=organization_id,
                    evaluator_id=evaluator_id,
                    result_id=result_id,
                    prefer_stereo=True,
                )

            try:
                raw_messages = context.messages if hasattr(context, "messages") else []
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
                        recording_metadata=recording_metadata,
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
            "error": str(e),
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
