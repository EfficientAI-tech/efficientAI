"""
Retell WebRTC Bridge Service

Bridges WebSocket-based test agent to Retell's WebRTC calls using LiveKit.
Handles audio streaming, format conversion, and connection management.

IMPORTANT: Retell uses LiveKit as their WebRTC infrastructure.
The access_token from create_web_call is a LiveKit JWT token.
"""

import asyncio
import json
import time
import tempfile
import os
import base64
from typing import Optional, Callable, Awaitable
from uuid import UUID
from loguru import logger

try:
    from livekit import rtc
    from livekit.rtc import Room, RoomOptions, AudioFrame, AudioSource, LocalAudioTrack, TrackPublishOptions, TrackSource
except ImportError as e:
    logger.error(f"LiveKit SDK not installed: {e}")
    logger.error("Install with: pip install livekit")
    raise

import numpy as np

from app.models.database import Agent, VoiceBundle, EvaluatorResult

# Retell's LiveKit WebSocket URL
# Retell uses LiveKit Cloud infrastructure
# Found by inspecting retell-client-js-sdk source code:
#   await this.room.connect("wss://retell-ai-4ihahnq7.livekit.cloud", t.accessToken)
RETELL_LIVEKIT_URL = "wss://retell-ai-4ihahnq7.livekit.cloud"


class RetellWebRTCBridge:
    """
    Bridges test agent (WebSocket) to Retell WebRTC call using LiveKit.
    
    This class handles:
    - LiveKit room connection to Retell
    - Audio streaming between test agent and Retell
    - Audio format conversion (PCM)
    - Connection lifecycle management
    
    Retell uses LiveKit for their WebRTC infrastructure. The access_token
    from create_web_call is a LiveKit JWT that contains:
    - room: The room name (e.g., "web_call_xxx")
    - roomJoin: true
    """
    
    def __init__(
        self,
        call_id: str,
        access_token: str,
        sample_rate: int = 24000,
    ):
        """
        Initialize Retell WebRTC bridge.
        
        Args:
            call_id: Retell call ID (used to derive room name)
            access_token: LiveKit JWT token from Retell's create_web_call
            sample_rate: Audio sample rate (default 24000 for Retell)
        """
        self.call_id = call_id
        self.access_token = access_token
        self.sample_rate = sample_rate
        
        # LiveKit connection
        self._room: Optional[Room] = None
        self._audio_source: Optional[AudioSource] = None
        self._audio_track: Optional[LocalAudioTrack] = None
        
        # Audio processing
        self._audio_queue = asyncio.Queue()
        
        # WebSocket connection for test agent
        self.test_agent_ws = None
        
        # Recording
        self.recording_enabled = False
        self.audio_recording_path: Optional[str] = None
        self._recording_buffer: list = []
        
        # State
        self.is_connected = False
        self.is_bridging = False
        self._connection_event = asyncio.Event()
        self._disconnection_event = asyncio.Event()
        
        # Callbacks
        self.on_call_ended: Optional[Callable[[], Awaitable[None]]] = None
        self.on_audio_received: Optional[Callable[[bytes], Awaitable[None]]] = None
        self.on_transcript_received: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_agent_start_talking: Optional[Callable[[], Awaitable[None]]] = None
        self.on_agent_stop_talking: Optional[Callable[[], Awaitable[None]]] = None
        
        # Transcript accumulator
        self._current_transcript = ""
        self._agent_is_talking = False
        
        # Extract room name from access_token or call_id
        # Retell's access token is a JWT that contains the room name
        self._room_name = self._extract_room_from_token(access_token, call_id)
        
        logger.info(f"[RetellWebRTC] Initialized with room_name={self._room_name}")
    
    def _extract_room_from_token(self, token: str, call_id: str) -> str:
        """
        Extract the room name from the LiveKit JWT token.
        
        Args:
            token: LiveKit JWT access token
            call_id: Fallback call ID if token parsing fails
            
        Returns:
            Room name string
        """
        try:
            # LiveKit tokens are JWTs - decode the payload (without verification)
            import base64
            
            # Split the token into parts
            parts = token.split('.')
            if len(parts) != 3:
                raise ValueError("Invalid JWT format")
            
            # Decode the payload (second part)
            # Add padding if needed
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            
            payload_json = base64.urlsafe_b64decode(payload).decode('utf-8')
            payload_data = json.loads(payload_json)
            
            logger.debug(f"[RetellWebRTC] Token payload: {payload_data}")
            
            # Extract room from video grants
            video_grants = payload_data.get('video', {})
            room_name = video_grants.get('room')
            
            if room_name:
                logger.info(f"[RetellWebRTC] Extracted room from token: {room_name}")
                return room_name
            
            # Log helpful info
            logger.warning(f"[RetellWebRTC] No room found in token. Token issuer: {payload_data.get('iss')}")
            
        except Exception as e:
            logger.warning(f"[RetellWebRTC] Failed to parse token: {e}")
        
        # Fallback to constructing room name from call_id
        if call_id.startswith("call_"):
            room_name = f"web_call_{call_id[5:]}"
        else:
            room_name = f"web_call_{call_id}"
        
        logger.info(f"[RetellWebRTC] Using fallback room name: {room_name}")
        return room_name
    
    async def connect_to_retell(self) -> bool:
        """
        Connect to Retell WebRTC call via LiveKit.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"[RetellWebRTC] Connecting to Retell call {self.call_id}")
            logger.info(f"[RetellWebRTC] Using LiveKit URL: {RETELL_LIVEKIT_URL}")
            logger.info(f"[RetellWebRTC] Room name: {self._room_name}")
            
            # Create LiveKit room
            self._room = Room()
            
            # Set up event handlers
            @self._room.on("connected")
            def on_connected():
                logger.info("[RetellWebRTC] ✅ Connected to Retell LiveKit room")
                self.is_connected = True
                self._connection_event.set()
            
            @self._room.on("disconnected")
            def on_disconnected(reason=None):
                logger.info(f"[RetellWebRTC] Disconnected from Retell. Reason: {reason}")
                self.is_connected = False
                self._disconnection_event.set()
                if self.on_call_ended:
                    asyncio.create_task(self.on_call_ended())
            
            @self._room.on("participant_connected")
            def on_participant_connected(participant):
                logger.info(f"[RetellWebRTC] Participant connected: {participant.identity}")
            
            @self._room.on("participant_disconnected")
            def on_participant_disconnected(participant):
                logger.info(f"[RetellWebRTC] Participant disconnected: {participant.identity}")
                # If Retell agent (identity="server") disconnects, end the call
                if participant.identity == "server":
                    logger.info("[RetellWebRTC] Retell server disconnected, ending call")
                    if self.on_call_ended:
                        asyncio.create_task(self.on_call_ended())
            
            @self._room.on("track_subscribed")
            def on_track_subscribed(track, publication, participant):
                logger.info(f"[RetellWebRTC] Track subscribed: {track.kind} from {participant.identity}")
                if track.kind == rtc.TrackKind.KIND_AUDIO:
                    # Start processing audio from Retell
                    asyncio.create_task(self._process_retell_audio(track))
            
            @self._room.on("track_unsubscribed")
            def on_track_unsubscribed(track, publication, participant):
                logger.info(f"[RetellWebRTC] Track unsubscribed: {track.kind} from {participant.identity}")
            
            @self._room.on("data_received")
            def on_data_received(data_packet):
                """Handle data messages from Retell (contains transcripts, events, etc.)"""
                # LiveKit SDK passes a DataPacket object
                # Extract the data bytes and participant info
                try:
                    data_bytes = bytes(data_packet.data)
                    participant_identity = data_packet.participant.identity if data_packet.participant else None
                    asyncio.create_task(self._handle_retell_data_packet(data_bytes, participant_identity))
                except Exception as e:
                    logger.error(f"[RetellWebRTC] Error handling data packet: {e}")
            
            # Connect to Retell's LiveKit room
            logger.info("[RetellWebRTC] Connecting to LiveKit room...")
            try:
                await self._room.connect(
                    RETELL_LIVEKIT_URL,
                    self.access_token,
                    options=RoomOptions(auto_subscribe=True)
                )
                logger.info(f"[RetellWebRTC] room.connect() completed, connection_state={self._room.connection_state}")
            except Exception as conn_error:
                error_str = str(conn_error).lower()
                
                # Log helpful messages based on error type
                if "401" in error_str or "unauthorized" in error_str:
                    logger.error("[RetellWebRTC] ❌ Token invalid or expired!")
                    logger.error("[RetellWebRTC] Retell access tokens expire after 30 seconds.")
                    logger.error("[RetellWebRTC] Make sure to connect IMMEDIATELY after create_web_call.")
                elif "timeout" in error_str:
                    logger.error("[RetellWebRTC] Connection timed out. Check network connectivity.")
                else:
                    logger.error(f"[RetellWebRTC] Connection failed: {conn_error}")
                raise
            
            # The room.connect() may return before the "connected" event fires
            # Check if we're already connected
            if self._room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
                logger.info("[RetellWebRTC] Already connected after room.connect()")
                self.is_connected = True
                self._connection_event.set()
            
            # Wait for connection event with timeout (may already be set)
            logger.info("[RetellWebRTC] Waiting for connection event...")
            try:
                await asyncio.wait_for(self._connection_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error(f"[RetellWebRTC] Connection timeout - connection_state={self._room.connection_state}")
                logger.error("[RetellWebRTC] Did not receive 'connected' event within 30 seconds")
                return False
            
            logger.info(f"[RetellWebRTC] Room state: {self._room.connection_state}")
            logger.info(f"[RetellWebRTC] Local participant: {self._room.local_participant.sid}")
            
            # Set up audio source for sending audio to Retell
            self._audio_source = AudioSource(
                sample_rate=self.sample_rate,
                num_channels=1
            )
            
            self._audio_track = LocalAudioTrack.create_audio_track(
                "test-agent-audio",
                self._audio_source
            )
            
            # Publish audio track
            options = TrackPublishOptions()
            options.source = TrackSource.SOURCE_MICROPHONE
            await self._room.local_participant.publish_track(self._audio_track, options)
            
            logger.info("[RetellWebRTC] ✅ Audio track published to Retell")
            
            return True
            
        except Exception as e:
            logger.error(f"[RetellWebRTC] Failed to connect: {e}", exc_info=True)
            return False
    
    async def _process_retell_audio(self, track):
        """
        Process incoming audio from Retell and forward to test agent.
        
        Args:
            track: Audio track from Retell
        """
        try:
            logger.info("[RetellWebRTC] Starting to process Retell audio")
            
            audio_stream = rtc.AudioStream(track)
            
            async for event in audio_stream:
                if isinstance(event, rtc.AudioFrameEvent):
                    frame = event.frame
                    
                    # Convert to PCM bytes
                    audio_data = frame.data.tobytes()
                    
                    # Record if enabled
                    if self.recording_enabled:
                        self._recording_buffer.append(audio_data)
                    
                    # Forward to test agent
                    if self.on_audio_received:
                        await self.on_audio_received(audio_data)
                    
                    # Also forward via WebSocket if connected
                    if self.test_agent_ws and self.is_bridging:
                        await self._send_audio_to_test_agent(audio_data)
                        
        except Exception as e:
            logger.error(f"[RetellWebRTC] Error processing Retell audio: {e}", exc_info=True)
    
    async def _send_audio_to_test_agent(self, audio_bytes: bytes):
        """
        Send audio to test agent via WebSocket.
        
        Args:
            audio_bytes: PCM audio bytes to send
        """
        if not self.test_agent_ws:
            return
        
        try:
            # Check if websocket is open
            if hasattr(self.test_agent_ws, 'closed') and self.test_agent_ws.closed:
                return
            
            # Send as JSON with base64 encoded audio
            frame_data = {
                "type": "audio",
                "data": base64.b64encode(audio_bytes).decode('utf-8'),
                "sample_rate": self.sample_rate,
                "channels": 1,
            }
            
            await self.test_agent_ws.send(json.dumps(frame_data))
            
        except Exception as e:
            logger.error(f"[RetellWebRTC] Error sending audio to test agent: {e}")
    
    async def _handle_retell_data_packet(self, data: bytes, participant_identity: str):
        """
        Handle data messages from Retell (called from LiveKit event).
        
        Args:
            data: Raw bytes of the data message
            participant_identity: Identity string of the sender
        """
        # Only process messages from the server (Retell agent)
        if participant_identity and participant_identity != "server":
            return
        
        await self._handle_retell_data(data, participant_identity)
    
    async def _deliver_accumulated_transcript(self):
        """
        Deliver the accumulated transcript to the test agent.
        
        Extracts the latest agent message from the full transcript,
        delivers it via on_transcript_received, and resets the accumulator.
        
        Must be called AFTER on_agent_stop_talking so that
        test_agent.agent_is_talking is False when the transcript arrives.
        """
        if not self._current_transcript:
            logger.debug("[RetellWebRTC] No accumulated transcript to deliver on agent stop")
            return

        latest_agent_text = self._extract_latest_agent_message(self._current_transcript)
        self._current_transcript = ""

        if latest_agent_text and self.on_transcript_received:
            logger.info(
                f"[RetellWebRTC] Delivering accumulated agent transcript "
                f"({len(latest_agent_text)} chars): {latest_agent_text[:100]}..."
            )
            await self.on_transcript_received(latest_agent_text)
        elif not latest_agent_text:
            logger.debug("[RetellWebRTC] No agent message extracted from transcript")

    async def _handle_retell_data(self, data: bytes, participant_identity: str = None):
        """
        Handle data messages from Retell.
        
        Retell sends JSON messages with various event types:
        - update: Contains real-time transcript updates
        - agent_start_talking: Agent started speaking
        - agent_stop_talking: Agent finished speaking
        - metadata: Call metadata
        - node_transition: State machine transitions
        
        Turn-taking strategy:
        - update events accumulate the full transcript during the agent's turn
        - agent_start_talking sets agent speaking state
        - agent_stop_talking signals stop BEFORE delivering transcript,
          ensuring test_agent.agent_is_talking is False when transcript arrives
        
        Args:
            data: Raw bytes of the data message
            participant_identity: Identity string of the sender
        """
        try:
            # Only process messages from the server (Retell agent)
            if participant_identity and participant_identity != "server":
                return
            
            # Decode and parse the JSON message
            message_str = data.decode('utf-8')
            message = json.loads(message_str)
            
            event_type = message.get("event_type")
            
            if event_type == "update":
                # Transcript update from Retell
                transcript = message.get("transcript", "")
                if transcript:
                    logger.debug(f"[RetellWebRTC] Transcript update: {transcript[:50] if isinstance(transcript, str) else '(list)'}...")
                    self._current_transcript = transcript
                    
                    # Also check for turn completion
                    turn_id = message.get("turn_id")
                    if turn_id:
                        logger.debug(f"[RetellWebRTC] Turn ID: {turn_id}")
            
            elif event_type == "agent_start_talking":
                logger.info("[RetellWebRTC] Retell agent started speaking")
                self._agent_is_talking = True
                if self.on_agent_start_talking:
                    await self.on_agent_start_talking()
            
            elif event_type == "agent_stop_talking":
                logger.info("[RetellWebRTC] Retell agent stopped speaking")
                self._agent_is_talking = False
                # Signal stop BEFORE delivering transcript, so
                # test_agent.agent_is_talking is False when transcript arrives
                if self.on_agent_stop_talking:
                    await self.on_agent_stop_talking()
                # Deliver accumulated transcript now that the agent finished speaking
                await self._deliver_accumulated_transcript()
            
            elif event_type == "metadata":
                logger.debug(f"[RetellWebRTC] Metadata: {message}")
            
            elif event_type == "node_transition":
                logger.debug(f"[RetellWebRTC] Node transition: {message.get('node_id')}")
            
            else:
                logger.debug(f"[RetellWebRTC] Unknown event type: {event_type}")
                
        except json.JSONDecodeError as e:
            logger.warning(f"[RetellWebRTC] Failed to parse data message: {e}")
        except Exception as e:
            logger.error(f"[RetellWebRTC] Error handling data message: {e}", exc_info=True)
    
    def _extract_latest_agent_message(self, transcript) -> str:
        """
        Extract the latest agent message from the transcript.
        
        Retell sends transcript as a list of messages:
        [{'role': 'agent', 'content': '...'}, {'role': 'user', 'content': '...'}, ...]
        
        We need to extract the latest consecutive agent messages (agent's turn).
        
        Args:
            transcript: List of message dicts or string
            
        Returns:
            The extracted agent message text
        """
        if isinstance(transcript, str):
            return transcript.strip()
        
        if not isinstance(transcript, list) or not transcript:
            return ""
        
        # Find the latest consecutive agent messages (their current turn)
        agent_parts = []
        for msg in reversed(transcript):
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "agent":
                    agent_parts.insert(0, content)
                else:
                    # Stop when we hit a non-agent message (user spoke)
                    if agent_parts:
                        break
        
        return " ".join(agent_parts).strip()
    
    async def receive_audio_from_test_agent(self, audio_bytes: bytes):
        """
        Receive audio from test agent and forward to Retell.
        
        Args:
            audio_bytes: PCM audio bytes from test agent (16-bit, mono)
        """
        if not self.is_connected or not self._audio_source:
            return
        
        try:
            # Record if enabled
            if self.recording_enabled:
                self._recording_buffer.append(audio_bytes)
            
            # Convert bytes to numpy array (int16)
            samples = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # Calculate samples per channel
            samples_per_channel = len(samples)
            
            # Create LiveKit AudioFrame
            frame = AudioFrame(
                data=audio_bytes,
                sample_rate=self.sample_rate,
                num_channels=1,
                samples_per_channel=samples_per_channel
            )
            
            # Send to Retell via LiveKit
            await self._audio_source.capture_frame(frame)
                
        except Exception as e:
            logger.error(f"[RetellWebRTC] Error forwarding audio to Retell: {e}", exc_info=True)
    
    async def start_recording(self, output_path: Optional[str] = None):
        """
        Start recording the bridged conversation.
        
        Args:
            output_path: Optional path for recording file
        """
        if not output_path:
            fd, self.audio_recording_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
        else:
            self.audio_recording_path = output_path
        
        self._recording_buffer = []
        self.recording_enabled = True
        logger.info(f"[RetellWebRTC] Started recording to {self.audio_recording_path}")
    
    async def stop_recording(self) -> Optional[str]:
        """
        Stop recording and save to file.
        
        Returns:
            Path to recorded audio file, or None if recording failed
        """
        self.recording_enabled = False
        
        if not self._recording_buffer or not self.audio_recording_path:
            logger.warning("[RetellWebRTC] No recording data to save")
            return None
        
        try:
            import wave
            
            # Concatenate all audio chunks
            all_audio = b''.join(self._recording_buffer)
            
            # Write WAV file
            with wave.open(self.audio_recording_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.sample_rate)
                wf.writeframes(all_audio)
            
            logger.info(f"[RetellWebRTC] Saved recording: {self.audio_recording_path} ({len(all_audio)} bytes)")
            
            self._recording_buffer = []
            return self.audio_recording_path
            
        except Exception as e:
            logger.error(f"[RetellWebRTC] Error saving recording: {e}", exc_info=True)
            return None
    
    async def disconnect(self):
        """Disconnect from Retell call and cleanup."""
        try:
            logger.info("[RetellWebRTC] Disconnecting from Retell call")
            
            self.is_bridging = False
            self.is_connected = False
            
            if self._room:
                await self._room.disconnect()
                self._room = None
            
            if self.test_agent_ws:
                try:
                    await self.test_agent_ws.close()
                except:
                    pass
                self.test_agent_ws = None
            
            logger.info("[RetellWebRTC] Disconnected")
            
        except Exception as e:
            logger.error(f"[RetellWebRTC] Error during disconnect: {e}", exc_info=True)
    
    async def wait_for_disconnect(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the call to end.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if disconnected, False if timeout
        """
        try:
            await asyncio.wait_for(self._disconnection_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
