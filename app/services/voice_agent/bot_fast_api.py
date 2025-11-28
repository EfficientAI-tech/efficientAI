#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#
import os
import sys
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import Frame, AudioRawFrame, EndFrame, StartFrame, CancelFrame
import wave
import tempfile
import subprocess
import uuid
import time
from app.services.s3_service import s3_service



logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

SYSTEM_INSTRUCTION = f"""
"You are Gemini Chatbot, a friendly, helpful robot.
Your goal is to demonstrate your capabilities in a succinct way.
Your output will be converted to audio so don't include special characters in your answers.
Respond to what the user said in a creative and helpful way. Keep your responses brief. One or two sentences at most.
"""

class AudioRecorder(FrameProcessor):
    def __init__(self, filename: str, start_time: float):
        super().__init__()
        self.filename = filename
        self.start_time = start_time
        self.wave_file = None
        self.params_set = False
        self.total_samples_written = 0
        self.sample_rate = 0
        self.num_channels = 0

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, AudioRawFrame):
            current_time = time.time()
            
            if not self.wave_file:
                try:
                    self.wave_file = wave.open(self.filename, 'wb')
                    self.num_channels = frame.num_channels
                    self.sample_rate = frame.sample_rate
                    self.wave_file.setnchannels(self.num_channels)
                    self.wave_file.setsampwidth(2) # 16-bit PCM
                    self.wave_file.setframerate(self.sample_rate)
                    self.params_set = True
                except Exception as e:
                    logger.error(f"Failed to open wave file {self.filename}: {e}")
            
            if self.wave_file and self.params_set:
                # Calculate expected samples based on time elapsed since start
                elapsed_seconds = current_time - self.start_time
                if elapsed_seconds < 0: elapsed_seconds = 0
                
                expected_samples = int(elapsed_seconds * self.sample_rate)
                
                # If we are behind, pad with silence
                # Limit padding to avoid huge files if something goes wrong (e.g. max 10 seconds gap per frame)
                samples_to_pad = expected_samples - self.total_samples_written
                
                if samples_to_pad > 0:
                    # Cap padding to avoid massive writes on glitches
                    if samples_to_pad > self.sample_rate * 10:
                         samples_to_pad = self.sample_rate * 10
                    
                    # Create silence frame
                    # 2 bytes per sample * num_channels
                    silence_bytes = b'\x00' * (samples_to_pad * self.num_channels * 2)
                    try:
                        self.wave_file.writeframes(silence_bytes)
                        self.total_samples_written += samples_to_pad
                    except Exception as e:
                        logger.error(f"Error writing silence: {e}")

                try:
                    self.wave_file.writeframes(frame.audio)
                    # Update total samples based on frame length
                    # frame.audio is bytes. 16-bit = 2 bytes.
                    num_samples = len(frame.audio) // (self.num_channels * 2)
                    self.total_samples_written += num_samples
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


async def run_bot(websocket_client, google_api_key: str, system_instruction: str = None):
    """
    Run the voice agent bot with the provided Google API key.
    
    Args:
        websocket_client: WebSocket client connection
        google_api_key: Decrypted Google API key for Gemini
        system_instruction: Optional system instruction (overrides default)
    """
    try:
        logger.info("Setting up FastAPIWebsocketTransport...")
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
        logger.info("FastAPIWebsocketTransport created")

        # Use provided system instruction or fallback to default
        instruction = system_instruction if system_instruction else SYSTEM_INSTRUCTION

        logger.info("Setting up GeminiLiveLLMService...")
        llm = GeminiLiveLLMService(
            api_key=google_api_key,
            voice_id="Puck",  # Aoede, Charon, Fenrir, Kore, Puck
            transcribe_model_audio=True,
            system_instruction=instruction,
        )
        logger.info("GeminiLiveLLMService created")
        context = LLMContext(
            [
                {
                    "role": "user",
                    "content": "Start by greeting the user warmly and introducing yourself.",
                }
            ],
        )

        context_aggregator = LLMContextAggregatorPair(context)

        # RTVI events for Pipecat client UI
        # RTVIProcessor handles the RTVI protocol handshake with the client
        rtvi = RTVIProcessor(config=RTVIConfig(config=[]))
        logger.info("RTVIProcessor created - will handle RTVI protocol handshake")

        # Create temporary files for recording
        user_audio_fd, user_audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(user_audio_fd)
        bot_audio_fd, bot_audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(bot_audio_fd)
        
        logger.info(f"Recording user audio to: {user_audio_path}")
        logger.info(f"Recording bot audio to: {bot_audio_path}")
        
        # Use a common start time for synchronization
        start_time = time.time()
        user_recorder = AudioRecorder(user_audio_path, start_time)
        bot_recorder = AudioRecorder(bot_audio_path, start_time)

        logger.info("Setting up Pipeline...")
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

        logger.info("Pipeline created")

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=[RTVIObserver(rtvi)],
        )
        logger.info("PipelineTask created")

        @rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            logger.info("Pipecat client ready - RTVI handshake complete!")
            await rtvi.set_bot_ready()
            logger.info("Bot marked as ready, sending initial LLMRunFrame...")
            # Kick off the conversation.
            await task.queue_frames([LLMRunFrame()])
            logger.info("Initial LLMRunFrame queued")

        @ws_transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Pipecat Client connected via WebSocket")
            logger.info("Waiting for RTVI protocol handshake from client...")
            logger.info("Client should send RTVI protocol messages to complete handshake")
            # Note: The RTVI handshake is typically initiated by the client
            # If the client uses transport.connect() directly instead of startBotAndConnect(),
            # it might not send RTVI protocol messages automatically

        @ws_transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Pipecat Client disconnected")
            await task.cancel()

        # Verify WebSocket is still open before starting
        logger.info(f"WebSocket state before starting runner: {websocket_client.client_state}")
        if websocket_client.client_state.name != "CONNECTED":
            raise Exception(f"WebSocket is not in CONNECTED state: {websocket_client.client_state.name}")
        
        # Log transport state
        logger.info(f"Transport input processor: {ws_transport.input()}")
        logger.info(f"Transport output processor: {ws_transport.output()}")
        
        # The FastAPIWebsocketTransport should automatically receive messages when the pipeline runs
        # But let's verify the transport is set up correctly
        logger.info("Transport setup complete. Messages should be received automatically when pipeline runs.")
        
        logger.info("Starting PipelineRunner...")
        runner = PipelineRunner(handle_sigint=False)
        
        try:
            logger.info("PipelineRunner.run() starting - this should keep the connection alive...")
            logger.info("The transport should now start receiving messages from the WebSocket...")
            await runner.run(task)
            logger.info("PipelineRunner.run() completed")
        except Exception as run_error:
            logger.error(f"Error in runner.run(): {run_error}", exc_info=True)
            raise
        finally:
            logger.info("PipelineRunner finished")
            
            # Close recorders explicitly to ensure files are flushed
            await user_recorder.cleanup()
            await bot_recorder.cleanup()
            
            # Merge and upload audio
            try:
                if os.path.exists(user_audio_path) and os.path.exists(bot_audio_path):
                    # Check if files have content
                    user_size = os.path.getsize(user_audio_path)
                    bot_size = os.path.getsize(bot_audio_path)
                    
                    if user_size > 100 and bot_size > 100: # Check for valid header + data
                        merged_fd, merged_path = tempfile.mkstemp(suffix=".wav")
                        os.close(merged_fd)
                        
                        logger.info(f"Merging audio files to {merged_path}...")
                        
                        # Use ffmpeg to mix audio
                        # amix filter mixes multiple audio inputs
                        cmd = [
                            "ffmpeg",
                            "-y", # Overwrite output
                            "-i", user_audio_path,
                            "-i", bot_audio_path,
                            "-filter_complex", "amix=inputs=2:duration=longest",
                            merged_path
                        ]
                        
                        process = subprocess.run(cmd, capture_output=True, text=True)
                        
                        if process.returncode == 0 and os.path.exists(merged_path):
                            logger.info("Audio merged successfully. Uploading to S3...")
                            
                            with open(merged_path, "rb") as f:
                                file_content = f.read()
                                
                            file_id = uuid.uuid4()
                            s3_key = s3_service.upload_file(
                                file_content=file_content,
                                file_id=file_id,
                                file_format="wav"
                            )
                            
                            logger.info(f"✅ Conversation audio uploaded to S3: {s3_key}")
                            
                            # Clean up merged file
                            os.unlink(merged_path)
                        else:
                            logger.error(f"FFmpeg merge failed: {process.stderr}")
                    else:
                        logger.warning("Recorded audio files are too small, skipping merge/upload.")
                
                # Clean up temp files
                if os.path.exists(user_audio_path):
                    os.unlink(user_audio_path)
                if os.path.exists(bot_audio_path):
                    os.unlink(bot_audio_path)
                    
            except Exception as e:
                logger.error(f"Error processing recorded audio: {e}")

    except Exception as e:
        logger.error(f"Error in run_bot: {e}", exc_info=True)
        raise

