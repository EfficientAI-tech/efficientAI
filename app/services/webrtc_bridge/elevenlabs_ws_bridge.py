"""
ElevenLabs WebSocket Bridge Service

Bridges the test agent to an ElevenLabs Conversational AI agent via WebSocket.
Handles audio streaming, format conversion, and connection management.

ElevenLabs uses a WebSocket-based protocol (not WebRTC).
The signed URL from create_web_call is the WebSocket endpoint.

Audio format: 16-bit PCM mono at 16kHz.

Turn-taking strategy (ElevenLabs has NO explicit start/stop talking events):
  - ``agent_response`` events deliver the agent's full text; we accumulate them
    locally and only forward to ``on_transcript_received`` once inbound audio
    has been silent for ``SILENCE_THRESHOLD_S`` (text often arrives before TTS
    finishes — never flush on text alone).
  - ``audio`` events indicate the agent is actively speaking; inbound PCM is fed
    to the turn gate's Silero VAD for logging/backup only (ElevenLabs uses the
    bridge silence detector as the authoritative end-of-turn signal).
  - The silence detector delivers the held transcript, then fires
    ``on_agent_stop_talking`` so ProductionTurnGate flushes after ``stop_secs``.

All callbacks that may take a long time (LLM + TTS) are dispatched via
``asyncio.create_task`` so they never block the WebSocket receive loop.
"""

import asyncio
import base64
import json
import tempfile
import os
import time
from typing import Optional, Callable, Awaitable
from loguru import logger

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    logger.warning("websockets not installed: pip install websockets")
    WEBSOCKETS_AVAILABLE = False

ELEVENLABS_SAMPLE_RATE = 16000
NUM_CHANNELS = 1
# Silence fills mic gaps once speech has paused this long (between sentences
# of a streamed reply, or after it), keeping the caller track on real time.
MIC_SPEECH_GAP_S = 0.06
MIC_MAX_CATCHUP_FRAMES = 25  # 0.5 s
BYTES_PER_SAMPLE = 2  # 16-bit audio

# How long (seconds) after the last *played-out* frame before we consider the
# agent done. Audio is paced to real time first, so this only needs to clear
# ElevenLabs' inter-sentence gaps, not its faster-than-real-time bursts.
SILENCE_THRESHOLD_S = 0.8

# Inbound audio is re-sliced into frames of this size and released in real time.
PLAYOUT_FRAME_MS = 20


class ElevenLabsWSBridge:
    """
    Bridges the test agent to an ElevenLabs Conversational AI WebSocket.

    Mirrors the interface of RetellWebRTCBridge / VapiWebRTCBridge so that
    test_agent_bridge_service can treat all three providers uniformly.
    """

    def __init__(
        self,
        signed_url: str,
        sample_rate: int = ELEVENLABS_SAMPLE_RATE,
    ):
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError("websockets not available. Install with: pip install websockets")

        self.signed_url = signed_url
        self.sample_rate = sample_rate

        # WebSocket connection
        self._ws = None

        # ElevenLabs assigns the conversation_id after connection
        self.conversation_id: Optional[str] = None

        # Recording
        self.recording_enabled = False
        self.audio_recording_path: Optional[str] = None
        self._recording_buffer: list = []

        # State
        self.is_connected = False
        self.is_bridging = False
        self._should_stop = asyncio.Event()

        # Interrupt tracking (matches ElevenLabs SDK)
        self._last_interrupt_id = 0

        # Callbacks (same interface as Retell/Vapi bridges)
        self.on_call_ended: Optional[Callable[[], Awaitable[None]]] = None
        self.on_audio_received: Optional[Callable[[bytes], Awaitable[None]]] = None
        self.on_transcript_received: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_agent_start_talking: Optional[Callable[[], Awaitable[None]]] = None
        self.on_agent_stop_talking: Optional[Callable[[], Awaitable[None]]] = None

        # ----- Turn-taking state -----
        self._agent_is_talking = False
        # Accumulates the agent_response text for the current turn
        self._pending_agent_text = ""
        # Monotonic timestamp of the most recently *played-out* audio frame
        self._last_audio_ts: float = 0.0
        # Real-time playout pacer: ElevenLabs sends audio faster than real time,
        # so frames are queued and released at playback speed.
        self._playout_queue: asyncio.Queue = asyncio.Queue()
        self._playout_buf = bytearray()
        self._playout_generation = 0
        self._pacer_task: Optional[asyncio.Task] = None
        self._turn_rx_started: float = 0.0
        self._turn_rx_last: float = 0.0
        self._turn_audio_bytes = 0
        # When True, deliver turn end even without provider text (STT supplies it).
        self.deliver_empty_turns = False
        # Handle for the silence-detection background task
        self._silence_task: Optional[asyncio.Task] = None
        # Background task that simulates a live microphone by sending silence
        self._bg_silence_task: Optional[asyncio.Task] = None
        # When True, an external ambient mic pump feeds continuous PCM instead.
        self._external_mic_feed = False
        # Suppresses background silence while the test agent is actively sending audio
        self._user_is_sending = False
        # Mic timeline: bytes sent vs. wall clock since the first send. ElevenLabs
        # builds the caller track from samples received, so any shortfall makes
        # our speech land later on its timeline (cumulative over the call).
        self._mic_t0: Optional[float] = None
        self._mic_bytes_sent = 0
        self._last_user_audio_ts = 0.0

        logger.info(f"[ElevenLabsWS] Initialized bridge (sample_rate={sample_rate})")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect_to_elevenlabs(self) -> bool:
        """
        Connect to the ElevenLabs Conversational AI WebSocket.

        Returns True on success, False on failure.
        """
        try:
            logger.info("[ElevenLabsWS] Connecting to signed URL...")
            self._ws = await websockets.connect(
                self.signed_url,
                max_size=16 * 1024 * 1024,
                ping_interval=None,
            )

            # Send the initiation message (required by the protocol)
            initiation = {
                "type": "conversation_initiation_client_data",
                "conversation_config_override": {},
                "dynamic_variables": {},
            }
            await self._ws.send(json.dumps(initiation))
            logger.info("[ElevenLabsWS] Sent conversation_initiation_client_data")

            # Wait for conversation_initiation_metadata (contains conversation_id)
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=15.0)
                msg = json.loads(raw)
                if msg.get("type") == "conversation_initiation_metadata":
                    event = msg["conversation_initiation_metadata_event"]
                    self.conversation_id = event["conversation_id"]
                    logger.info(
                        f"[ElevenLabsWS] Connected — conversation_id={self.conversation_id}"
                    )
                    expected = f"pcm_{self.sample_rate}"
                    out_fmt = event.get("agent_output_audio_format")
                    if out_fmt and out_fmt != expected:
                        logger.warning(
                            f"[ElevenLabsWS] Agent output format {out_fmt} != {expected}; "
                            "pacing, VAD and STT assume raw PCM at the bridge sample rate"
                        )
                else:
                    logger.warning(
                        f"[ElevenLabsWS] Unexpected first message type: {msg.get('type')}"
                    )
            except asyncio.TimeoutError:
                logger.error("[ElevenLabsWS] Timeout waiting for initiation metadata")
                return False

            self.is_connected = True

            # Start background message receiver and the real-time playout pacer
            asyncio.create_task(self._receive_loop())
            self._pacer_task = asyncio.create_task(self._playout_loop())

            # Start continuous silence stream unless an external mic feed is active.
            if not self._external_mic_feed:
                self._bg_silence_task = asyncio.create_task(self._background_silence_loop())

            return True

        except Exception as e:
            logger.error(f"[ElevenLabsWS] Connection failed: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Sending audio
    # ------------------------------------------------------------------

    async def receive_audio_from_test_agent(self, audio_bytes: bytes):
        """
        Forward PCM audio from the test agent to ElevenLabs.

        The audio is base64-encoded and sent as a JSON message per the
        ElevenLabs protocol (``user_audio_chunk``).
        """
        if not self.is_connected or not self._ws:
            return

        try:
            self._user_is_sending = True

            if self.recording_enabled:
                self._recording_buffer.append(audio_bytes)

            chunk_b64 = base64.b64encode(audio_bytes).decode()
            await self._ws.send(json.dumps({"user_audio_chunk": chunk_b64}))
            self._count_mic_bytes(len(audio_bytes))
            self._last_user_audio_ts = time.monotonic()
        except Exception as e:
            logger.error(f"[ElevenLabsWS] Error sending audio: {e}")

    def _count_mic_bytes(self, n: int) -> None:
        if self._mic_t0 is None:
            self._mic_t0 = time.monotonic()
        self._mic_bytes_sent += n

    def _mic_deficit_bytes(self) -> int:
        """Bytes the mic stream is behind real time (frame-aligned, >= 0)."""
        if self._mic_t0 is None:
            return 0
        expected = int((time.monotonic() - self._mic_t0) * self.sample_rate) * BYTES_PER_SAMPLE
        return max(0, expected - self._mic_bytes_sent)

    def mark_user_audio_done(self):
        """Signal that the test agent finished sending its utterance.

        Called by the bridge service after ``send_audio_chunks`` completes
        so the background silence loop can resume.
        """
        self._user_is_sending = False

    def suppress_background_silence(self):
        """Stop the zero-silence mic loop when an ambient mic pump is active."""
        self._external_mic_feed = True
        if self._bg_silence_task and not self._bg_silence_task.done():
            self._bg_silence_task.cancel()
        self._bg_silence_task = None
        logger.info("[ElevenLabsWS] Background silence stream suppressed (external mic feed active)")

    async def send_silence(self, duration_ms: int = 500):
        """Send an explicit silence buffer (e.g. trailing silence after an utterance)."""
        if not self.is_connected or not self._ws:
            return

        try:
            chunk_samples = (self.sample_rate * 20) // 1000  # 20ms
            chunk_bytes = b"\x00" * (chunk_samples * BYTES_PER_SAMPLE)
            total_chunks = duration_ms // 20

            for _ in range(total_chunks):
                chunk_b64 = base64.b64encode(chunk_bytes).decode()
                await self._ws.send(json.dumps({"user_audio_chunk": chunk_b64}))
                await asyncio.sleep(0.02)

            logger.debug(f"[ElevenLabsWS] Sent {duration_ms}ms silence ({total_chunks} chunks)")
        except Exception as e:
            logger.error(f"[ElevenLabsWS] Error sending silence: {e}")

    async def _background_silence_loop(self):
        """Continuously stream silence to ElevenLabs to simulate a live microphone.

        A real browser mic sends a constant 16 kHz PCM stream (mostly zeros
        during silence).  Without this, ElevenLabs' VAD cannot detect
        end-of-speech between turns and the conversation stalls.

        Pacing is against the wall clock: every tick tops the stream up to
        real time with silence, so sleep overshoot, event-loop stalls and gaps
        between the test agent's sentences never make the caller track drift
        behind the agent track. Silence is withheld only while speech is
        actually flowing.
        """
        frame_bytes = (self.sample_rate * 20) // 1000 * BYTES_PER_SAMPLE  # 20 ms
        max_burst_bytes = frame_bytes * MIC_MAX_CATCHUP_FRAMES

        logger.info("[ElevenLabsWS] Background silence stream started")
        try:
            next_tick = time.monotonic()
            while self.is_connected and not self._should_stop.is_set():
                next_tick += 0.02
                speech_flowing = (
                    self._user_is_sending
                    and time.monotonic() - self._last_user_audio_ts < MIC_SPEECH_GAP_S
                )
                if not speech_flowing:
                    deficit = self._mic_deficit_bytes() if self._mic_t0 is not None else frame_bytes
                    if deficit > max_burst_bytes:
                        # Long stall: send a bounded burst and re-anchor the clock
                        # rather than flooding the socket.
                        skipped = deficit - max_burst_bytes
                        self._mic_bytes_sent += skipped
                        logger.debug(f"[ElevenLabsWS] Mic clock re-anchored ({skipped / BYTES_PER_SAMPLE / self.sample_rate:.2f}s)")
                        deficit = max_burst_bytes
                    frames = max(1, deficit // frame_bytes) if deficit >= frame_bytes else 0
                    if frames:
                        silence = base64.b64encode(b"\x00" * frame_bytes * frames).decode()
                        try:
                            if self._ws:
                                await self._ws.send(json.dumps({"user_audio_chunk": silence}))
                                self._count_mic_bytes(frame_bytes * frames)
                        except Exception:
                            break
                delay = next_tick - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    next_tick = time.monotonic()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ElevenLabsWS] Background silence loop error: {e}")
        logger.info("[ElevenLabsWS] Background silence stream stopped")

    # ------------------------------------------------------------------
    # Receiving messages
    # ------------------------------------------------------------------

    async def _receive_loop(self):
        """Process incoming WebSocket messages from ElevenLabs.

        IMPORTANT: No callback in ``_handle_message`` may block this loop.
        Long-running work (LLM, TTS) is dispatched via ``asyncio.create_task``.
        """
        try:
            while not self._should_stop.is_set() and self._ws:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosedOK:
                    logger.info("[ElevenLabsWS] WebSocket closed normally")
                    break
                except websockets.exceptions.ConnectionClosed as e:
                    logger.info(f"[ElevenLabsWS] WebSocket closed: {e}")
                    break

                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                try:
                    await self._handle_message(message)
                except Exception as e:
                    # One bad event must not end the call.
                    logger.error(
                        f"[ElevenLabsWS] Error handling {message.get('type')!r} event: {e}",
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(f"[ElevenLabsWS] Receive loop error: {e}", exc_info=True)
        finally:
            self.is_connected = False
            self.is_bridging = False
            if self.on_call_ended:
                try:
                    await self.on_call_ended()
                except Exception:
                    pass

    async def _handle_message(self, message: dict):
        msg_type = message.get("type", "")

        # ----------------------------------------------------------
        # audio — agent is actively speaking
        # ----------------------------------------------------------
        if msg_type == "audio":
            event = message.get("audio_event", {})
            event_id = int(event.get("event_id", 0))
            if event_id <= self._last_interrupt_id:
                return

            audio_b64 = event.get("audio_base_64", "")
            if not audio_b64:
                return

            audio_bytes = base64.b64decode(audio_b64)

            if self.recording_enabled:
                self._recording_buffer.append(audio_bytes)

            now = time.monotonic()
            if self._turn_audio_bytes == 0:
                self._turn_rx_started = now
            self._turn_rx_last = now
            self._turn_audio_bytes += len(audio_bytes)

            # Talking state, silence detection and downstream delivery all
            # happen at playout time (see _playout_loop), not arrival time.
            self._playout_queue.put_nowait(audio_bytes)

        # ----------------------------------------------------------
        # agent_response — full text of what the agent said
        # ----------------------------------------------------------
        elif msg_type == "agent_response":
            event = message.get("agent_response_event", {})
            text = event.get("agent_response", "").strip()
            if text:
                logger.info(f"[ElevenLabsWS] Agent response text: {text[:120]}...")
                # Accumulate multi-part responses within one turn.
                if text not in self._pending_agent_text:
                    self._pending_agent_text = f"{self._pending_agent_text} {text}".strip()

        # ----------------------------------------------------------
        # user_transcript — our test agent's speech echoed back
        # ----------------------------------------------------------
        elif msg_type == "user_transcript":
            event = message.get("user_transcription_event", {})
            transcript = event.get("user_transcript", "").strip()
            if transcript:
                logger.debug(f"[ElevenLabsWS] User transcript: {transcript[:80]}...")

        # ----------------------------------------------------------
        # interruption — user interrupted the agent
        # ----------------------------------------------------------
        elif msg_type == "interruption":
            event = message.get("interruption_event", {})
            self._last_interrupt_id = int(event.get("event_id", 0))
            logger.info("[ElevenLabsWS] Interruption received")
            # Drop audio the agent generated but a listener would never hear.
            self._clear_playout()
            # Agent was interrupted — consider the turn over immediately
            if self._agent_is_talking:
                self._agent_is_talking = False
                asyncio.create_task(self._deliver_turn_end())

        # ----------------------------------------------------------
        # ping — must pong to keep connection alive
        # ----------------------------------------------------------
        elif msg_type == "ping":
            event = message.get("ping_event", {})
            pong = {"type": "pong", "event_id": event.get("event_id")}
            if self._ws:
                await self._ws.send(json.dumps(pong))

        elif msg_type == "conversation_initiation_metadata":
            pass  # handled during connect

        # ----------------------------------------------------------
        # agent_response_correction — ElevenLabs corrects the text
        # after an interruption or re-generation
        # ----------------------------------------------------------
        elif msg_type == "agent_response_correction":
            event = message.get("agent_response_correction_event", {})
            corrected = event.get("corrected_agent_response", "").strip()
            original = event.get("original_agent_response", "").strip()
            if corrected:
                logger.info(
                    f"[ElevenLabsWS] Agent response corrected: "
                    f"'{original[:60]}...' -> '{corrected[:60]}...'"
                )
                self._pending_agent_text = corrected
            elif original:
                # Correction to empty = agent retracted its response
                logger.info(f"[ElevenLabsWS] Agent response retracted: '{original[:60]}...'")
                self._pending_agent_text = ""

        elif msg_type == "client_tool_call":
            tool_call = message.get("client_tool_call", {})
            tool_call_id = tool_call.get("tool_call_id")
            if tool_call_id and self._ws:
                result = {
                    "type": "client_tool_result",
                    "tool_call_id": tool_call_id,
                    "result": "Tool not available in evaluation mode",
                    "is_error": False,
                }
                await self._ws.send(json.dumps(result))

        else:
            logger.debug(f"[ElevenLabsWS] Unhandled message type: {msg_type}")

    # ------------------------------------------------------------------
    # Real-time playout pacing
    # ------------------------------------------------------------------

    @property
    def agent_is_talking(self) -> bool:
        """True from the agent's first played frame until end-of-turn silence."""
        return self._agent_is_talking or self._playout_pending()

    def _playout_pending(self) -> bool:
        return not self._playout_queue.empty() or bool(self._playout_buf)

    def _clear_playout(self):
        """Discard queued, unplayed agent audio (e.g. after an interruption)."""
        dropped = len(self._playout_buf)
        self._playout_buf.clear()
        while not self._playout_queue.empty():
            dropped += len(self._playout_queue.get_nowait())
        self._playout_generation += 1
        if dropped:
            logger.info(
                f"[ElevenLabsWS] Dropped {dropped / (self.sample_rate * BYTES_PER_SAMPLE):.2f}s "
                "of unplayed agent audio"
            )

    async def _playout_loop(self):
        """Release queued agent audio in fixed frames at real-time speed.

        ElevenLabs delivers TTS audio faster than real time. A listener only
        hears the end of the utterance once it has played out, so turn-taking,
        VAD and STT must all observe the paced stream.
        """
        frame_bytes = (self.sample_rate * PLAYOUT_FRAME_MS // 1000) * BYTES_PER_SAMPLE
        frame_secs = PLAYOUT_FRAME_MS / 1000
        due = 0.0
        try:
            while not self._should_stop.is_set():
                if len(self._playout_buf) < frame_bytes:
                    if self._playout_buf and self._playout_queue.empty():
                        # Tail of an utterance: pad to a full frame.
                        frame = bytes(self._playout_buf).ljust(frame_bytes, b"\x00")
                        self._playout_buf.clear()
                    else:
                        self._playout_buf.extend(await self._playout_queue.get())
                        continue
                else:
                    frame = bytes(self._playout_buf[:frame_bytes])
                    del self._playout_buf[:frame_bytes]

                generation = self._playout_generation
                now = time.monotonic()
                due = max(due, now)
                if due > now:
                    await asyncio.sleep(due - now)
                due += frame_secs
                if generation != self._playout_generation:
                    continue  # interrupted while waiting
                await self._play_frame(frame)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ElevenLabsWS] Playout loop error: {e}", exc_info=True)

    async def _play_frame(self, frame: bytes):
        self._last_audio_ts = time.monotonic()

        # Mark agent as talking (fire callback only on rising edge)
        if not self._agent_is_talking:
            self._agent_is_talking = True
            logger.info("[ElevenLabsWS] Agent started speaking (first played frame)")
            if self.on_agent_start_talking:
                asyncio.create_task(self.on_agent_start_talking())

        self._ensure_silence_detector()

        if self.on_audio_received:
            try:
                await self.on_audio_received(frame)
            except Exception as e:
                logger.error(f"[ElevenLabsWS] on_audio_received error: {e}", exc_info=True)

    def _log_turn_stats(self):
        if not self._turn_audio_bytes:
            return
        audio_secs = self._turn_audio_bytes / (self.sample_rate * BYTES_PER_SAMPLE)
        rx_secs = self._turn_rx_last - self._turn_rx_started
        logger.info(
            f"[ElevenLabsWS] Turn audio: {audio_secs:.1f}s received over {rx_secs:.1f}s wall"
        )
        self._turn_audio_bytes = 0

    # ------------------------------------------------------------------
    # Silence detection (replaces missing start/stop-talking events)
    # ------------------------------------------------------------------

    def _ensure_silence_detector(self):
        """Start or restart the silence-detection background task."""
        if self._silence_task is None or self._silence_task.done():
            self._silence_task = asyncio.create_task(self._silence_detector())

    async def _silence_detector(self):
        """Background task that fires provider stop after inbound audio silence.

        Transcript delivery is owned by ProductionTurnGate (VAD on inbound PCM).
        This task only notifies ``on_agent_stop_talking`` for the provider-stop
        fallback path.
        """
        try:
            while self.is_connected and self._agent_is_talking:
                await asyncio.sleep(0.15)  # check frequently
                if self._last_audio_ts == 0 or self._playout_pending():
                    continue
                elapsed = time.monotonic() - self._last_audio_ts
                if elapsed >= SILENCE_THRESHOLD_S:
                    logger.info(
                        f"[ElevenLabsWS] Silence detected ({elapsed:.2f}s) — agent stopped speaking"
                    )
                    self._agent_is_talking = False
                    await self._deliver_turn_end()
                    return
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ElevenLabsWS] Silence detector error: {e}", exc_info=True)

    async def _deliver_turn_end(self):
        """Deliver held agent text, then signal provider stop for the turn gate."""
        text = self._pending_agent_text.strip()
        self._pending_agent_text = ""
        self._log_turn_stats()
        if self.on_transcript_received and (text or self.deliver_empty_turns):
            logger.info(
                f"[ElevenLabsWS] Delivering agent transcript after silence "
                f"({len(text)} chars): {text[:100]}..."
            )
            await self.on_transcript_received(text)
        if self.on_agent_stop_talking:
            await self.on_agent_stop_talking()

    def _deliver_pending_transcript(self):
        """Legacy helper — transcripts are held via on_transcript_received."""
        text = self._pending_agent_text.strip()
        self._pending_agent_text = ""
        if text and self.on_transcript_received:
            logger.info(
                f"[ElevenLabsWS] Delivering held transcript ({len(text)} chars): {text[:100]}..."
            )
            asyncio.create_task(self.on_transcript_received(text))
        elif not text:
            logger.debug("[ElevenLabsWS] No pending transcript to deliver")

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def start_recording(self, output_path: Optional[str] = None):
        if not output_path:
            fd, self.audio_recording_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
        else:
            self.audio_recording_path = output_path

        self._recording_buffer = []
        self.recording_enabled = True
        logger.info(f"[ElevenLabsWS] Started recording to {self.audio_recording_path}")

    async def stop_recording(self) -> Optional[str]:
        self.recording_enabled = False

        if not self._recording_buffer or not self.audio_recording_path:
            logger.warning("[ElevenLabsWS] No recording data to save")
            return None

        try:
            import wave

            all_audio = b"".join(self._recording_buffer)
            with wave.open(self.audio_recording_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(all_audio)

            logger.info(
                f"[ElevenLabsWS] Saved recording: {self.audio_recording_path} "
                f"({len(all_audio)} bytes)"
            )
            self._recording_buffer = []
            return self.audio_recording_path
        except Exception as e:
            logger.error(f"[ElevenLabsWS] Error saving recording: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Disconnect
    # ------------------------------------------------------------------

    async def disconnect(self):
        try:
            logger.info("[ElevenLabsWS] Disconnecting")
            self.is_bridging = False
            self.is_connected = False
            self._should_stop.set()

            if self._silence_task and not self._silence_task.done():
                self._silence_task.cancel()
            if self._bg_silence_task and not self._bg_silence_task.done():
                self._bg_silence_task.cancel()
            if self._pacer_task and not self._pacer_task.done():
                self._pacer_task.cancel()

            if self._ws:
                await self._ws.close()
                self._ws = None

            logger.info("[ElevenLabsWS] Disconnected")
        except Exception as e:
            logger.error(f"[ElevenLabsWS] Error during disconnect: {e}", exc_info=True)

    async def wait_for_disconnect(self, timeout: Optional[float] = None) -> bool:
        start = asyncio.get_event_loop().time()
        while self.is_connected:
            await asyncio.sleep(1)
            if timeout and (asyncio.get_event_loop().time() - start) > timeout:
                return False
        return True
