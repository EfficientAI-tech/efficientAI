#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#
import os
import sys
from loguru import logger
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
from efficientai.processors.frame_processor import FrameProcessor
from efficientai.frames.frames import (
    Frame, AudioRawFrame, OutputAudioRawFrame, TTSAudioRawFrame,
    EndFrame, StartFrame, CancelFrame
)
import wave
import tempfile
import time
import numpy as np
from app.services.voice_agent.utils.audio_merge import merge_and_upload_audio



logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

# Default system instruction (used as fallback if no agent description is provided)
DEFAULT_SYSTEM_INSTRUCTION = """
You are Gemini Chatbot, a friendly, helpful robot.
Your goal is to demonstrate your capabilities in a succinct way.
Your output will be converted to audio so don't include special characters in your answers.
Respond to what the user said in a creative and helpful way. Keep your responses brief. One or two sentences at most.
"""

class AudioRecorder(FrameProcessor):
    def __init__(self, filename: str, start_time: float, target_sample_rate: int = 24000, recorder_name: str = "AudioRecorder"):
        super().__init__()
        self.filename = filename
        self.start_time = start_time
        self.target_sample_rate = target_sample_rate
        self.recorder_name = recorder_name
        self.wave_file = None
        self.params_set = False
        self.sample_rate = 0
        self.num_channels = 0
        self.frames_received = 0
        self.audio_frames_received = 0
        self.last_frame_time = None  # Track when last frame was received
        self.total_samples_written = 0  # Track total samples written

    def _resample_audio(self, audio_bytes: bytes, in_rate: int, out_rate: int, num_channels: int) -> bytes:
        """Resample audio using simple linear interpolation."""
        if in_rate == out_rate:
            return audio_bytes
        
        # Convert bytes to numpy array (16-bit signed integers)
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        
        # Reshape for multi-channel if needed
        if num_channels > 1:
            audio_array = audio_array.reshape(-1, num_channels)
        
        # Calculate resampling ratio
        ratio = out_rate / in_rate
        original_length = len(audio_array)
        new_length = int(original_length * ratio)
        
        # Create indices for interpolation
        old_indices = np.arange(original_length)
        new_indices = np.linspace(0, original_length - 1, new_length)
        
        # Interpolate
        if num_channels > 1:
            resampled = np.zeros((new_length, num_channels), dtype=np.int16)
            for ch in range(num_channels):
                resampled[:, ch] = np.interp(new_indices, old_indices, audio_array[:, ch]).astype(np.int16)
            return resampled.tobytes()
        else:
            resampled = np.interp(new_indices, old_indices, audio_array).astype(np.int16)
            return resampled.tobytes()

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)
        
        self.frames_received += 1
        
        # Handle both input and output audio frames
        # OutputAudioRawFrame (TTSAudioRawFrame) is a subclass of AudioRawFrame
        if isinstance(frame, AudioRawFrame):
            self.audio_frames_received += 1
            if not self.wave_file:
                try:
                    self.wave_file = wave.open(self.filename, 'wb')
                    self.num_channels = frame.num_channels
                    # Use target sample rate for the file
                    self.sample_rate = self.target_sample_rate
                    self.wave_file.setnchannels(self.num_channels)
                    self.wave_file.setsampwidth(2) # 16-bit PCM
                    self.wave_file.setframerate(self.sample_rate)
                    self.params_set = True
                except Exception as e:
                    logger.error(f"Failed to open wave file {self.filename}: {e}")
            
            if self.wave_file and self.params_set:
                try:
                    current_time = time.time()
                    
                    # Resample if needed
                    if frame.sample_rate != self.sample_rate:
                        audio_to_write = self._resample_audio(
                            frame.audio,
                            frame.sample_rate,
                            self.sample_rate,
                            frame.num_channels
                        )
                    else:
                        audio_to_write = frame.audio
                    
                    # Verify channels match
                    if frame.num_channels != self.num_channels:
                        logger.warning(
                            f"Channel mismatch: expected {self.num_channels}ch, got {frame.num_channels}ch. Skipping frame."
                        )
                    else:
                        # Calculate expected position based on time elapsed
                        elapsed_time = current_time - self.start_time
                        expected_samples = int(elapsed_time * self.sample_rate)
                        
                        # If we're behind (gap in audio), pad with silence
                        if expected_samples > self.total_samples_written:
                            samples_to_pad = expected_samples - self.total_samples_written
                            # Limit padding to reasonable amount (max 1 second gap)
                            if samples_to_pad <= self.sample_rate:
                                silence_bytes = b'\x00' * (samples_to_pad * self.num_channels * 2)
                                self.wave_file.writeframes(silence_bytes)
                                self.total_samples_written += samples_to_pad
                        
                        # Write audio frame
                        num_samples = len(audio_to_write) // (self.num_channels * 2)
                        self.wave_file.writeframes(audio_to_write)
                        self.total_samples_written += num_samples
                        self.last_frame_time = current_time
                except Exception as e:
                    logger.error(f"Error writing audio frame: {e}")
        
        elif isinstance(frame, (EndFrame, CancelFrame)):
            if self.wave_file:
                self.wave_file.close()
                self.wave_file = None
        
        await self.push_frame(frame, direction)

    async def cleanup(self):
        if self.wave_file:
            self.wave_file.close()
            self.wave_file = None


async def run_bot(websocket_client, google_api_key: str, system_instruction: str = None, organization_id: str = None, agent_id: str = None, persona_id: str = None, scenario_id: str = None, evaluator_id: str = None, result_id: str = None, model_name: str = None):
    """
    Run the voice agent bot with the provided Google API key.
    
    Args:
        websocket_client: WebSocket client connection
        google_api_key: Decrypted Google API key for Gemini
        system_instruction: Optional system instruction (overrides default)
        organization_id: Organization ID for organizing S3 uploads
    """
    # Initialize variables for return values
    call_start_time = time.time()
    s3_key_result = None
    duration_result = None
    
    try:
        ws_transport = FastAPIWebsocketTransport(
            websocket=websocket_client,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                vad_analyzer=SileroVADAnalyzer(),
                serializer=ProtobufFrameSerializer(),
            ),
        )

        # Use provided system instruction or fallback to default
        # If system_instruction is None or empty, use the default
        if system_instruction and system_instruction.strip():
            instruction = system_instruction.strip()
        else:
            instruction = DEFAULT_SYSTEM_INSTRUCTION.strip()

        # Validate API key before passing to Gemini
        if not google_api_key or not google_api_key.strip():
            raise ValueError("Google API key is empty or invalid")
        
        # Determine model name - use from agent's voice bundle if provided, otherwise use default
        if model_name:
            # Format model name for Gemini Live API (add "models/" prefix if not present)
            if not model_name.startswith("models/"):
                formatted_model_name = f"models/{model_name}"
            else:
                formatted_model_name = model_name
        else:
            # Fallback to default model if not provided
            formatted_model_name = "models/gemini-2.5-flash-native-audio-preview-12-2025"
        logger.info(f"Using Gemini Live model: {formatted_model_name}")
        
        llm = GeminiLiveLLMService(
            api_key=google_api_key,
            voice_id="Puck",  # Aoede, Charon, Fenrir, Kore, Puck
            transcribe_model_audio=True,
            system_instruction=instruction,
            model=formatted_model_name,
        )
        context = LLMContext(
            [
                {
                    "role": "user",
                    "content": "Start by greeting the user warmly and introducing yourself based on the system instruction.",
                }
            ],
        )

        context_aggregator = LLMContextAggregatorPair(context)

        # RTVI events for efficientai client UI
        # RTVIProcessor handles the RTVI protocol handshake with the client
        rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

        # Create temporary files for recording
        user_audio_fd, user_audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(user_audio_fd)
        bot_audio_fd, bot_audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(bot_audio_fd)
        
        # Use a common start time for synchronization
        start_time = time.time()
        user_recorder = AudioRecorder(user_audio_path, start_time, recorder_name="UserAudioRecorder")
        bot_recorder = AudioRecorder(bot_audio_path, start_time, recorder_name="BotAudioRecorder")

        pipeline = Pipeline(
            [
                ws_transport.input(),
                user_recorder, # Record user audio
                context_aggregator.user(),
                rtvi,
                llm,  # LLM
                bot_recorder, # Record bot audio
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
            # Kick off the conversation.
            await task.queue_frames([LLMRunFrame()])

        @ws_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("efficientai client connected via WebSocket")
            # Note: The RTVI handshake is typically initiated by the client
            # If the client uses transport.connect() directly instead of startBotAndConnect(),
            # it might not send RTVI protocol messages automatically

        @ws_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("efficientai Client disconnected")
            await task.cancel()

        # Verify WebSocket is still open before starting
        if websocket_client.client_state.name != "CONNECTED":
            raise Exception(f"WebSocket is not in CONNECTED state: {websocket_client.client_state.name}")
        runner = PipelineRunner(handle_sigint=False)
        
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
            )

    except Exception as e:
        logger.error(f"Error in run_bot: {e}", exc_info=True)
        # Still return metadata if we have it, even if there was an error
        return {
            "s3_key": s3_key_result,
            "duration": duration_result,
            "agent_id": agent_id,
            "persona_id": persona_id,
            "scenario_id": scenario_id,
            "error": str(e)
        }
    
    # Return call metadata for evaluator result creation
    # Only return if we have valid results
    if s3_key_result:
        return {
            "s3_key": s3_key_result,
            "duration": duration_result,
            "agent_id": agent_id,
            "persona_id": persona_id,
            "scenario_id": scenario_id
        }
    else:
        # Return empty result if no audio was uploaded
        return {
            "s3_key": None,
            "duration": duration_result,
            "agent_id": agent_id,
            "persona_id": persona_id,
            "scenario_id": scenario_id,
            "error": "No audio file was uploaded"
        }

