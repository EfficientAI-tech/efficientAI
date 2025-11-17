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

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

SYSTEM_INSTRUCTION = f"""
"You are Gemini Chatbot, a friendly, helpful robot.
Your goal is to demonstrate your capabilities in a succinct way.
Your output will be converted to audio so don't include special characters in your answers.
Respond to what the user said in a creative and helpful way. Keep your responses brief. One or two sentences at most.
"""

async def run_bot(websocket_client, google_api_key: str):
    """
    Run the voice agent bot with the provided Google API key.
    
    Args:
        websocket_client: WebSocket client connection
        google_api_key: Decrypted Google API key for Gemini
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

        logger.info("Setting up GeminiLiveLLMService...")
        llm = GeminiLiveLLMService(
            api_key=google_api_key,
            voice_id="Puck",  # Aoede, Charon, Fenrir, Kore, Puck
            transcribe_model_audio=True,
            system_instruction=SYSTEM_INSTRUCTION,
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

        logger.info("Setting up Pipeline...")
        pipeline = Pipeline(
            [
                ws_transport.input(),
                context_aggregator.user(),
                rtvi,
                llm,  # LLM
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
    except Exception as e:
        logger.error(f"Error in run_bot: {e}", exc_info=True)
        raise

