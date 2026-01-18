"""
Vapi WebRTC Bridge Service

Bridges WebSocket-based test agent to Vapi's WebRTC calls using Daily.co.
Handles audio streaming, format conversion, and connection management.

IMPORTANT: Vapi uses Daily.co as their WebRTC infrastructure.
The webCallUrl from create_web_call is a Daily.co room URL.
"""

import asyncio
import json
import time
import tempfile
import os
from typing import Optional, Callable, Awaitable
from loguru import logger

try:
    import daily
    DAILY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Daily.co SDK not installed: {e}")
    logger.warning("Install with: pip install daily-python")
    DAILY_AVAILABLE = False

import numpy as np
import threading
import queue

# Vapi uses 16kHz audio
VAPI_SAMPLE_RATE = 16000
NUM_CHANNELS = 1
# Match vapi_python SDK: 640 samples per chunk (40ms at 16kHz)
# For 16-bit mono audio: 640 samples * 2 bytes/sample = 1280 bytes
CHUNK_SIZE_SAMPLES = 640  # Number of samples per chunk
CHUNK_SIZE_BYTES = CHUNK_SIZE_SAMPLES * 2  # 1280 bytes for 16-bit audio

# Module-level flag to track if Daily SDK has been initialized
# Daily.init() must only be called ONCE per process
_daily_initialized = False
_daily_init_lock = threading.Lock()


class VapiWebRTCBridge:
    """
    Bridges test agent to Vapi WebRTC call using Daily.co.
    
    This class handles:
    - Daily.co room connection to Vapi
    - Audio streaming between test agent and Vapi
    - Audio format conversion (PCM 16-bit)
    - Connection lifecycle management
    
    Vapi uses Daily.co for their WebRTC infrastructure. The webCallUrl
    from create_web_call is a Daily.co room URL that we join directly.
    """
    
    def __init__(
        self,
        call_id: str,
        web_call_url: str,
        sample_rate: int = VAPI_SAMPLE_RATE,
    ):
        """
        Initialize Vapi WebRTC bridge.
        
        Args:
            call_id: Vapi call ID
            web_call_url: Daily.co room URL from Vapi's create_web_call
            sample_rate: Audio sample rate (default 16000 for Vapi)
        """
        if not DAILY_AVAILABLE:
            raise ImportError("Daily.co SDK not available. Install with: pip install daily-python")
        
        self.call_id = call_id
        self.web_call_url = web_call_url
        self.sample_rate = sample_rate
        
        # Daily.co client
        self._call_client: Optional[daily.CallClient] = None
        self._mic_device = None
        self._speaker_device = None
        
        # Audio queues for async bridging
        self._outgoing_audio_queue = queue.Queue()
        self._incoming_audio_queue = asyncio.Queue()
        
        # Recording
        self.recording_enabled = False
        self.audio_recording_path: Optional[str] = None
        self._recording_buffer: list = []
        
        # State
        self.is_connected = False
        self.is_bridging = False
        self._joined_event = threading.Event()
        self._quit_event = threading.Event()
        self._ready_to_send = threading.Event()  # Set when connection is fully ready for audio
        self._speaker_ready = False  # Track if Vapi speaker is playable
        self._inputs_ready = False  # Track if inputs (microphone) are ready
        
        # Callbacks
        self.on_call_ended: Optional[Callable[[], Awaitable[None]]] = None
        self.on_audio_received: Optional[Callable[[bytes], Awaitable[None]]] = None
        self.on_transcript_received: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_agent_start_talking: Optional[Callable[[], Awaitable[None]]] = None
        self.on_agent_stop_talking: Optional[Callable[[], Awaitable[None]]] = None
        
        # Transcript accumulator
        self._current_transcript = ""
        self._agent_is_talking = False
        
        # Background threads
        self._send_audio_thread: Optional[threading.Thread] = None
        self._receive_audio_thread: Optional[threading.Thread] = None
        
        logger.info(f"[VapiWebRTC] Initialized with call_id={call_id}, url={web_call_url[:50]}...")
    
    async def connect_to_vapi(self) -> bool:
        """
        Connect to Vapi WebRTC call via Daily.co.
        
        Returns:
            True if connection successful, False otherwise
        """
        global _daily_initialized
        
        try:
            logger.info(f"[VapiWebRTC] Connecting to Vapi call {self.call_id}")
            logger.info(f"[VapiWebRTC] Daily.co URL: {self.web_call_url[:60]}...")
            
            # Initialize Daily SDK (only once per process)
            with _daily_init_lock:
                if not _daily_initialized:
                    logger.info("[VapiWebRTC] Initializing Daily.co SDK...")
                    daily.Daily.init()
                    _daily_initialized = True
                    logger.info("[VapiWebRTC] Daily.co SDK initialized")
                else:
                    logger.debug("[VapiWebRTC] Daily.co SDK already initialized")
            
            # Create virtual audio devices with unique names per call
            # This avoids conflicts when multiple calls run in the same process
            mic_device_name = f"test-agent-mic-{self.call_id[:8]}"
            speaker_device_name = f"test-agent-speaker-{self.call_id[:8]}"
            
            self._mic_device = daily.Daily.create_microphone_device(
                mic_device_name,
                sample_rate=self.sample_rate,
                channels=NUM_CHANNELS
            )
            
            self._speaker_device = daily.Daily.create_speaker_device(
                speaker_device_name,
                sample_rate=self.sample_rate,
                channels=NUM_CHANNELS
            )
            daily.Daily.select_speaker_device(speaker_device_name)
            
            # Create event handler with reference to the current event loop
            # This allows async callbacks to be executed thread-safely
            loop = asyncio.get_event_loop()
            event_handler = VapiDailyEventHandler(self, loop)
            
            # Create call client
            self._call_client = daily.CallClient(event_handler=event_handler)
            
            # Configure inputs (microphone enabled, camera disabled)
            self._call_client.update_inputs({
                "camera": False,
                "microphone": {
                    "isEnabled": True,
                    "settings": {
                        "deviceId": mic_device_name,
                        "customConstraints": {
                            "autoGainControl": {"exact": True},
                            "noiseSuppression": {"exact": True},
                            "echoCancellation": {"exact": True},
                        }
                    }
                }
            })
            
            # Subscribe to remote audio only
            self._call_client.update_subscription_profiles({
                "base": {
                    "camera": "unsubscribed",
                    "microphone": "subscribed"
                }
            })
            
            # Join the Daily.co room
            logger.info("[VapiWebRTC] Joining Daily.co room...")
            self._call_client.join(self.web_call_url, completion=self._on_joined)
            
            # Wait for join to complete (with timeout)
            joined = self._joined_event.wait(timeout=30.0)
            if not joined:
                logger.error("[VapiWebRTC] ❌ Timeout waiting to join room")
                return False
            
            if not self.is_connected:
                logger.error("[VapiWebRTC] ❌ Failed to connect")
                return False
            
            logger.info("[VapiWebRTC] ✅ Connected to Vapi via Daily.co")
            
            # Start audio processing threads
            self._start_audio_threads()
            
            return True
            
        except Exception as e:
            logger.error(f"[VapiWebRTC] Failed to connect: {e}", exc_info=True)
            return False
    
    def _on_joined(self, data, error):
        """Callback when join completes."""
        if error:
            logger.error(f"[VapiWebRTC] Unable to join room: {error}")
            self.is_connected = False
        else:
            logger.info("[VapiWebRTC] Successfully joined Daily.co room")
            self.is_connected = True
            # Check if we should signal ready to send audio
            self._check_ready_to_send()
        self._joined_event.set()
    
    def _check_ready_to_send(self):
        """Check if we're ready to send audio and signal if so."""
        # We need: connected + inputs ready + speaker ready
        if self.is_connected and self._inputs_ready and self._speaker_ready:
            if not self._ready_to_send.is_set():
                logger.info("[VapiWebRTC] ✅ Ready to send audio (connected + inputs + speaker ready)")
                self._ready_to_send.set()
        elif self.is_connected and self._inputs_ready:
            # We're connected with inputs ready but waiting for speaker
            if not self._ready_to_send.is_set():
                logger.debug(f"[VapiWebRTC] Waiting for speaker ready... (connected={self.is_connected}, inputs={self._inputs_ready}, speaker={self._speaker_ready})")
    
    def _start_audio_threads(self):
        """Start background threads for audio I/O."""
        self._quit_event.clear()
        
        # Thread to send audio to Vapi (from test agent)
        self._send_audio_thread = threading.Thread(
            target=self._send_audio_loop,
            daemon=True
        )
        self._send_audio_thread.start()
        
        # Thread to receive audio from Vapi
        self._receive_audio_thread = threading.Thread(
            target=self._receive_audio_loop,
            daemon=True
        )
        self._receive_audio_thread.start()
        
        logger.info("[VapiWebRTC] Audio processing threads started")
    
    def _send_audio_loop(self):
        """Background thread to send audio to Vapi."""
        audio_sent_count = 0
        bytes_sent = 0
        
        while not self._quit_event.is_set():
            try:
                # Get audio from queue with timeout
                audio_bytes = self._outgoing_audio_queue.get(timeout=0.1)
                if audio_bytes and self._mic_device:
                    self._mic_device.write_frames(audio_bytes)
                    audio_sent_count += 1
                    bytes_sent += len(audio_bytes)
                    
                    # Log periodically
                    if audio_sent_count % 100 == 0:
                        logger.debug(f"[VapiWebRTC] Sent {audio_sent_count} audio chunks ({bytes_sent} bytes total)")
            except queue.Empty:
                continue
            except Exception as e:
                if not self._quit_event.is_set():
                    logger.error(f"[VapiWebRTC] Error sending audio: {e}")
        
        logger.info(f"[VapiWebRTC] Audio send loop ended - sent {audio_sent_count} chunks ({bytes_sent} bytes)")
    
    def _receive_audio_loop(self):
        """Background thread to receive audio from Vapi."""
        audio_received_count = 0
        bytes_received = 0
        
        while not self._quit_event.is_set():
            try:
                if self._speaker_device:
                    buffer = self._speaker_device.read_frames(CHUNK_SIZE_SAMPLES)  # Read samples, not bytes
                    if buffer and len(buffer) > 0:
                        audio_received_count += 1
                        bytes_received += len(buffer)
                        
                        # Log first audio received for debugging
                        if audio_received_count == 1:
                            logger.info(f"[VapiWebRTC] First audio received from Vapi: {len(buffer)} bytes")
                        
                        # Log periodically
                        if audio_received_count % 100 == 0:
                            logger.debug(f"[VapiWebRTC] Received {audio_received_count} audio chunks ({bytes_received} bytes total)")
                        
                        # Record if enabled
                        if self.recording_enabled:
                            self._recording_buffer.append(buffer)
                        
                        # Queue for async processing
                        try:
                            self._incoming_audio_queue.put_nowait(buffer)
                        except asyncio.QueueFull:
                            pass
            except Exception as e:
                if not self._quit_event.is_set():
                    logger.error(f"[VapiWebRTC] Error receiving audio: {e}")
        
        logger.info(f"[VapiWebRTC] Audio receive loop ended - received {audio_received_count} chunks ({bytes_received} bytes)")
    
    async def receive_audio_from_test_agent(self, audio_bytes: bytes):
        """
        Receive audio from test agent and forward to Vapi.
        
        Args:
            audio_bytes: PCM audio bytes from test agent (16-bit, mono)
        """
        if not self.is_connected:
            logger.warning("[VapiWebRTC] Not connected, dropping audio")
            return
        
        # Wait for connection to be fully ready (up to 5 seconds)
        if not self._ready_to_send.is_set():
            if not hasattr(self, '_waiting_logged'):
                logger.info("[VapiWebRTC] Waiting for connection to be ready before sending audio...")
                self._waiting_logged = True
            
            # Wait with timeout
            ready = self._ready_to_send.wait(timeout=5.0)
            if not ready:
                logger.warning("[VapiWebRTC] Timeout waiting for ready state, sending anyway")
                self._ready_to_send.set()  # Prevent further waits
        
        try:
            # Log first audio packet for debugging
            if not hasattr(self, '_first_audio_logged'):
                logger.info(f"[VapiWebRTC] First audio packet: {len(audio_bytes)} bytes, sample_rate={self.sample_rate}")
                self._first_audio_logged = True
            
            # Record if enabled
            if self.recording_enabled:
                self._recording_buffer.append(audio_bytes)
            
            # Queue for sending to Vapi
            self._outgoing_audio_queue.put(audio_bytes)
            
        except Exception as e:
            logger.error(f"[VapiWebRTC] Error forwarding audio to Vapi: {e}")
    
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
        logger.info(f"[VapiWebRTC] Started recording to {self.audio_recording_path}")
    
    async def stop_recording(self) -> Optional[str]:
        """
        Stop recording and save to file.
        
        Returns:
            Path to recorded audio file, or None if recording failed
        """
        self.recording_enabled = False
        
        if not self._recording_buffer or not self.audio_recording_path:
            logger.warning("[VapiWebRTC] No recording data to save")
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
            
            logger.info(f"[VapiWebRTC] Saved recording: {self.audio_recording_path} ({len(all_audio)} bytes)")
            
            self._recording_buffer = []
            return self.audio_recording_path
            
        except Exception as e:
            logger.error(f"[VapiWebRTC] Error saving recording: {e}", exc_info=True)
            return None
    
    async def disconnect(self):
        """Disconnect from Vapi call and cleanup."""
        try:
            logger.info("[VapiWebRTC] Disconnecting from Vapi call")
            
            self.is_bridging = False
            self.is_connected = False
            self._quit_event.set()
            
            # Wait for threads to finish
            if self._send_audio_thread:
                self._send_audio_thread.join(timeout=2.0)
            if self._receive_audio_thread:
                self._receive_audio_thread.join(timeout=2.0)
            
            # Leave the room
            if self._call_client:
                self._call_client.leave()
                self._call_client = None
            
            logger.info("[VapiWebRTC] Disconnected")
            
        except Exception as e:
            logger.error(f"[VapiWebRTC] Error during disconnect: {e}", exc_info=True)
    
    async def wait_for_disconnect(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the call to end.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if disconnected, False if timeout
        """
        start_time = asyncio.get_event_loop().time()
        while self.is_connected:
            await asyncio.sleep(1)
            if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                return False
        return True


class VapiDailyEventHandler(daily.EventHandler):
    """Event handler for Daily.co events."""
    
    def __init__(self, bridge: VapiWebRTCBridge, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.bridge = bridge
        self._participants = {}
        self._loop = loop  # Store reference to the asyncio event loop
    
    def _run_async(self, coro):
        """Safely run an async coroutine from a non-async thread."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:
            logger.warning("[VapiWebRTC] Event loop not running, cannot execute async callback")
    
    def on_inputs_updated(self, inputs):
        """Called when input devices are updated."""
        mic_enabled = inputs.get("microphone", {}).get("isEnabled", False)
        logger.info(f"[VapiWebRTC] Inputs updated: microphone enabled={mic_enabled}")
        if mic_enabled:
            self.bridge._inputs_ready = True
            self.bridge._check_ready_to_send()
    
    def on_participant_joined(self, participant):
        """Called when a participant joins the room."""
        self._participants[participant["id"]] = participant
        logger.info(f"[VapiWebRTC] Participant joined: {participant.get('info', {}).get('userName', 'unknown')}")
    
    def on_participant_left(self, participant, reason):
        """Called when a participant leaves the room."""
        if participant["id"] in self._participants:
            del self._participants[participant["id"]]
        
        # Check if Vapi agent left
        user_name = participant.get("info", {}).get("userName", "")
        if "Vapi" in user_name or "Speaker" in user_name:
            logger.info("[VapiWebRTC] Vapi agent disconnected, ending call")
            self.bridge.is_bridging = False
            self.bridge.is_connected = False
            if self.bridge.on_call_ended:
                self._run_async(self.bridge.on_call_ended())
        
        logger.info(f"[VapiWebRTC] Participant left: {user_name} (reason: {reason})")
    
    def on_participant_updated(self, participant):
        """Called when a participant's state changes."""
        self._participants[participant["id"]] = participant
        
        # Check if Vapi speaker is now playable (ready to receive audio from agent)
        user_name = participant.get("info", {}).get("userName", "")
        if "Vapi" in user_name or "Speaker" in user_name:
            mic = participant.get("media", {}).get("microphone", {})
            is_subscribed = mic.get("subscribed") == "subscribed"
            is_playable = mic.get("state") == "playable"
            
            if is_subscribed and is_playable and not self.bridge._speaker_ready:
                logger.info("[VapiWebRTC] Vapi speaker is now playable, sending 'playable' signal")
                # Send "playable" message to signal we're ready to receive audio
                # This is required by Vapi's protocol
                try:
                    if self.bridge._call_client:
                        self.bridge._call_client.send_app_message("playable")
                        logger.info("[VapiWebRTC] Sent 'playable' signal to Vapi")
                        self.bridge._speaker_ready = True
                        # Check if we should signal ready to send audio
                        self.bridge._check_ready_to_send()
                except Exception as e:
                    logger.error(f"[VapiWebRTC] Failed to send playable signal: {e}")
    
    def on_app_message(self, message, sender):
        """
        Handle app messages from Vapi.
        
        Vapi sends various events and messages via the app message channel.
        """
        try:
            # Log raw message for debugging
            logger.info(f"[VapiWebRTC] App message from {sender}: {str(message)[:300]}")
            
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    # Some messages might be simple strings like "playable"
                    logger.info(f"[VapiWebRTC] Simple app message: {message}")
                    return
            else:
                data = message
            
            # Try multiple possible type fields
            event_type = data.get("type") or data.get("event_type") or data.get("message_type")
            
            logger.info(f"[VapiWebRTC] App message parsed: type={event_type}, keys={list(data.keys())}")
            
            if event_type == "transcript":
                # Transcript update
                transcript = data.get("transcript", "") or data.get("text", "")
                if transcript:
                    logger.info(f"[VapiWebRTC] Transcript update: {transcript[:100]}...")
                    if self.bridge.on_transcript_received:
                        self._run_async(self.bridge.on_transcript_received(transcript))
            
            elif event_type in ["speech_start", "speech-start", "agent_start", "start"]:
                logger.info("[VapiWebRTC] Vapi agent started speaking")
                if self.bridge.on_agent_start_talking:
                    self._run_async(self.bridge.on_agent_start_talking())
            
            elif event_type in ["speech_end", "speech-end", "agent_end", "end"]:
                logger.info("[VapiWebRTC] Vapi agent stopped speaking")
                if self.bridge.on_agent_stop_talking:
                    self._run_async(self.bridge.on_agent_stop_talking())
            
            elif event_type in ["call_ended", "call-ended", "ended"]:
                logger.info("[VapiWebRTC] Call ended via app message")
                self.bridge.is_bridging = False
                if self.bridge.on_call_ended:
                    self._run_async(self.bridge.on_call_ended())
            
            # Check for transcript in message content (some Vapi versions)
            elif "content" in data and data.get("role") in ["assistant", "bot", "agent"]:
                # This is a message from the agent
                transcript = data.get("content", "")
                if transcript:
                    logger.info(f"[VapiWebRTC] Agent message: {transcript[:100]}...")
                    if self.bridge.on_transcript_received:
                        self._run_async(self.bridge.on_transcript_received(transcript))
            
            else:
                logger.info(f"[VapiWebRTC] Unhandled app message type: {event_type}, data: {str(data)[:200]}")
                
        except Exception as e:
            logger.error(f"[VapiWebRTC] Error handling app message: {e}", exc_info=True)
    
    def on_error(self, error):
        """Called when an error occurs."""
        logger.error(f"[VapiWebRTC] Error: {error}")
    
    def on_call_state_updated(self, state):
        """Called when call state changes."""
        logger.info(f"[VapiWebRTC] Call state: {state}")
        if state == "left":
            self.bridge.is_connected = False
            self.bridge.is_bridging = False
            if self.bridge.on_call_ended:
                self._run_async(self.bridge.on_call_ended())
