"""
Test Agent Processor

In-process test agent that simulates a caller based on persona/scenario.
Uses LLM for generating responses and TTS for speech synthesis.
Receives transcripts from Retell's real-time events (no STT needed).
"""

import asyncio
import io
import os
from typing import Optional, Callable, Awaitable, List, Dict, Any
from dataclasses import dataclass, field
from loguru import logger

# TTS service imports
try:
    from efficientai.services.cartesia.tts import CartesiaTTSService
    from efficientai.services.elevenlabs.tts import ElevenLabsHttpTTSService
    from efficientai.services.openai.llm import OpenAILLMService
    EFFICIENTAI_AVAILABLE = True
except ImportError:
    EFFICIENTAI_AVAILABLE = False
    logger.warning("EfficientAI services not available, using fallback implementations")

TTS_ENV_KEYS = {
    "cartesia": "CARTESIA_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
}

TTS_DEFAULT_VOICES = {
    "cartesia": "a0e99841-438c-4a64-b679-ae501e7d6091",
    "elevenlabs": "JBFqnCBsd6RMkjVDRZzb",
    "openai": "alloy",
}

TTS_DEFAULT_MODELS = {
    "cartesia": "sonic-english",
    "elevenlabs": "eleven_multilingual_v2",
    "openai": "gpt-4o-mini-tts",
}


@dataclass
class TestAgentConfig:
    """Configuration for the test agent."""
    persona_name: str = "Test Caller"
    persona_description: str = "A customer calling for assistance"
    scenario_description: str = "General inquiry call"
    scenario_goal: str = "Have a conversation and evaluate the agent"
    first_message: str = "Hello, I'm calling because I need some help."
    
    # Context about the voice AI agent being tested
    agent_name: str = "Voice AI Agent"
    agent_description: str = "A voice AI assistant"
    
    # LLM config
    llm_model: str = "gpt-4o-mini"
    llm_api_key: Optional[str] = None
    
    # TTS config
    tts_provider: str = "cartesia"
    tts_api_key: Optional[str] = None
    tts_voice_id: Optional[str] = None
    tts_model: Optional[str] = None
    
    # Audio config
    sample_rate: int = 24000
    
    # Behavior config
    max_turns: int = 20
    response_delay_ms: int = 500  # Delay before responding (more natural)


class TestAgentProcessor:
    """
    Processes conversations as a test agent.
    
    Receives transcripts from the voice AI agent and generates
    responses using LLM + TTS based on the configured persona/scenario.
    """
    
    def __init__(self, config: TestAgentConfig):
        """
        Initialize the test agent processor.
        
        Args:
            config: Configuration for the test agent
        """
        self.config = config
        self.conversation_history: List[Dict[str, str]] = []
        self.turn_count = 0
        self.is_processing = False
        self.should_end_call = False
        
        # Turn-taking state
        self.agent_is_talking = False          # Set by bridge when voice AI agent speaks
        self._pending_transcript: Optional[str] = None  # Queued transcript for later processing
        
        # Callbacks
        self.on_audio_generated: Optional[Callable[[bytes], Awaitable[None]]] = None
        self.on_response_text: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_call_should_end: Optional[Callable[[], Awaitable[None]]] = None
        
        # Services (initialized lazily)
        self._llm_service = None
        self._tts_service = None
        
        # Build system prompt
        self._system_prompt = self._build_system_prompt()
        
        logger.info(f"[TestAgent] Initialized with persona: {config.persona_name}, sample_rate={config.sample_rate}Hz")
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for the LLM based on persona/scenario."""
        return f"""You are simulating a caller in a voice conversation. Your role is to test a voice AI agent.

WHO YOU ARE CALLING:
- Agent Name: {self.config.agent_name}
- Agent Role: {self.config.agent_description}

YOUR PERSONA (who you are pretending to be):
- Name: {self.config.persona_name}
- Description: {self.config.persona_description}

SCENARIO:
- Description: {self.config.scenario_description}
- Goal: {self.config.scenario_goal}

INSTRUCTIONS:
1. You are CALLING the voice AI agent described above
2. Stay in character as the persona described
3. Follow the scenario and work toward the goal
4. Speak naturally as if on a phone call
5. Keep responses concise (1-3 sentences) for natural conversation flow
6. Ask relevant questions to test the agent's capabilities
7. Respond appropriately to what the agent says
8. If the conversation naturally concludes or you've achieved the goal, say goodbye
9. Respond ONLY with what you would say - no stage directions or descriptions

Your first message should naturally introduce yourself or state your reason for calling.
After {self.config.max_turns} exchanges, wrap up the conversation politely."""

    async def initialize(self):
        """Initialize LLM and TTS services."""
        try:
            # Initialize LLM
            llm_api_key = self.config.llm_api_key or os.getenv("OPENAI_API_KEY")
            if not llm_api_key:
                raise ValueError("OpenAI API key not configured")
            
            if EFFICIENTAI_AVAILABLE:
                self._llm_service = OpenAILLMService(
                    api_key=llm_api_key,
                    model=self.config.llm_model
                )
            else:
                # Fallback to direct OpenAI
                import openai
                self._openai_client = openai.AsyncOpenAI(api_key=llm_api_key)
            
            # Initialize TTS — resolve provider, voice, and model with defaults
            provider = self.config.tts_provider.lower()
            env_key = TTS_ENV_KEYS.get(provider, TTS_ENV_KEYS["cartesia"])
            tts_api_key = self.config.tts_api_key or os.getenv(env_key)
            if not tts_api_key:
                raise ValueError(f"{provider} API key not configured (checked config + env {env_key})")

            if not self.config.tts_voice_id:
                self.config.tts_voice_id = TTS_DEFAULT_VOICES.get(provider, TTS_DEFAULT_VOICES["cartesia"])
            if not self.config.tts_model:
                self.config.tts_model = TTS_DEFAULT_MODELS.get(provider, TTS_DEFAULT_MODELS["cartesia"])

            self.config.tts_api_key = tts_api_key
            
            logger.info("[TestAgent] Services initialized successfully")
            
        except Exception as e:
            logger.error(f"[TestAgent] Failed to initialize services: {e}")
            raise
    
    async def generate_first_message(self) -> Optional[bytes]:
        """
        Generate the first message to start the conversation.
        
        Returns:
            Audio bytes of the first message, or None if failed
        """
        try:
            # Use configured first message or generate one
            first_text = self.config.first_message
            
            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",  # Our test agent's message
                "content": first_text
            })
            
            if self.on_response_text:
                await self.on_response_text(first_text)
            
            # Convert to audio
            audio = await self._text_to_speech(first_text)
            
            if audio and self.on_audio_generated:
                await self.on_audio_generated(audio)
            
            self.turn_count += 1
            logger.info(f"[TestAgent] Generated first message: {first_text[:50]}...")
            
            return audio
            
        except Exception as e:
            logger.error(f"[TestAgent] Error generating first message: {e}")
            return None
    
    async def process_agent_transcript(self, transcript: str) -> Optional[bytes]:
        """
        Process a transcript from the voice AI agent and generate a response.
        
        Turn-taking guards:
        - If the voice AI agent is still talking, queue the transcript for later.
        - If we're already generating a response, queue the transcript instead of dropping it.
        - After finishing, check for a queued transcript and process it.
        
        Args:
            transcript: The text of what the agent said
            
        Returns:
            Audio bytes of the response, or None if no response needed
        """
        if not transcript or not transcript.strip():
            return None
        
        if self.agent_is_talking:
            logger.debug(f"[TestAgent] Agent still talking, queuing transcript: {transcript[:60]}...")
            self._pending_transcript = transcript
            return None
        
        if self.is_processing:
            logger.debug(f"[TestAgent] Already processing, queuing transcript: {transcript[:60]}...")
            self._pending_transcript = transcript
            return None
        
        return await self._do_process_transcript(transcript)
    
    async def _do_process_transcript(self, transcript: str) -> Optional[bytes]:
        """
        Internal method to actually process a transcript and generate a response.
        After processing, checks for any pending (queued) transcript and processes it.
        """
        self.is_processing = True
        
        try:
            logger.info(f"[TestAgent] Processing agent transcript: {transcript[:100]}...")
            
            # Add agent's message to history
            self.conversation_history.append({
                "role": "user",  # The agent we're testing
                "content": transcript
            })
            
            self.turn_count += 1
            
            # Check if we should end the call
            if self.turn_count >= self.config.max_turns:
                logger.info(f"[TestAgent] Max turns ({self.config.max_turns}) reached, ending call")
                response_text = "Thank you so much for your help. I think I have everything I need. Goodbye!"
                self.should_end_call = True
            else:
                # Generate response using LLM
                response_text = await self._generate_llm_response()
            
            if not response_text:
                logger.warning("[TestAgent] No response generated")
                return None
            
            # Add our response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": response_text
            })
            
            if self.on_response_text:
                await self.on_response_text(response_text)
            
            # Add natural delay before responding
            if self.config.response_delay_ms > 0:
                await asyncio.sleep(self.config.response_delay_ms / 1000)
            
            # Convert to audio
            audio = await self._text_to_speech(response_text)
            
            if audio and self.on_audio_generated:
                await self.on_audio_generated(audio)
            
            # Check for call ending
            if self.should_end_call and self.on_call_should_end:
                await asyncio.sleep(2)  # Wait for audio to be sent
                await self.on_call_should_end()
            
            logger.info(f"[TestAgent] Generated response (turn {self.turn_count}): {response_text[:50]}...")
            
            return audio
            
        except Exception as e:
            logger.error(f"[TestAgent] Error processing transcript: {e}", exc_info=True)
            return None
        finally:
            self.is_processing = False
            
            # Check for a queued transcript that arrived while we were processing
            pending = self._pending_transcript
            self._pending_transcript = None
            if pending and not self.agent_is_talking and not self.should_end_call:
                logger.info(f"[TestAgent] Processing queued transcript: {pending[:60]}...")
                # Fire-and-forget so we don't block the caller
                asyncio.create_task(self._do_process_transcript(pending))
    
    async def _generate_llm_response(self) -> Optional[str]:
        """Generate a response using the LLM."""
        try:
            messages = [
                {"role": "system", "content": self._system_prompt}
            ] + self.conversation_history
            
            if EFFICIENTAI_AVAILABLE and self._llm_service:
                # Use EfficientAI LLM service
                # Note: This is a simplified version - actual implementation
                # would need to handle the frame-based processing
                pass
            
            # Use direct OpenAI API
            import openai
            client = getattr(self, '_openai_client', None)
            if not client:
                api_key = self.config.llm_api_key or os.getenv("OPENAI_API_KEY")
                client = openai.AsyncOpenAI(api_key=api_key)
            
            response = await client.chat.completions.create(
                model=self.config.llm_model,
                messages=messages,
                max_tokens=150,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"[TestAgent] LLM error: {e}")
            return None
    
    async def _text_to_speech(self, text: str) -> Optional[bytes]:
        """Convert text to speech audio using the configured TTS provider."""
        provider = self.config.tts_provider.lower()
        try:
            if provider == "elevenlabs":
                return await self._tts_elevenlabs(text)
            elif provider == "openai":
                return await self._tts_openai(text)
            else:
                return await self._tts_cartesia(text)
        except Exception as e:
            logger.error(f"[TestAgent] TTS ({provider}) error: {e}")
            return None

    async def _tts_cartesia(self, text: str) -> Optional[bytes]:
        """Synthesize speech via Cartesia."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "X-API-Key": self.config.tts_api_key,
                    "Cartesia-Version": "2024-06-10",
                    "Content-Type": "application/json",
                },
                json={
                    "model_id": self.config.tts_model or "sonic-english",
                    "transcript": text,
                    "voice": {"mode": "id", "id": self.config.tts_voice_id},
                    "output_format": {
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": self.config.sample_rate,
                    },
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                return response.content
            logger.error(f"[TestAgent] Cartesia TTS error: {response.status_code} - {response.text}")
            return None

    async def _tts_elevenlabs(self, text: str) -> Optional[bytes]:
        """Synthesize speech via ElevenLabs and return raw PCM s16le bytes."""
        import httpx

        voice_id = self.config.tts_voice_id
        model_id = self.config.tts_model or "eleven_multilingual_v2"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self.config.tts_api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"[TestAgent] ElevenLabs TTS error: {response.status_code} - {response.text}")
                return None

            # ElevenLabs returns MP3 — convert to raw PCM s16le for the WebRTC bridge
            try:
                from pydub import AudioSegment

                audio_seg = AudioSegment.from_mp3(io.BytesIO(response.content))
                audio_seg = audio_seg.set_frame_rate(self.config.sample_rate).set_channels(1).set_sample_width(2)
                return audio_seg.raw_data
            except ImportError:
                logger.error("[TestAgent] pydub not installed — cannot convert ElevenLabs MP3 to PCM")
                return None

    async def _tts_openai(self, text: str) -> Optional[bytes]:
        """Synthesize speech via OpenAI TTS and return raw PCM s16le bytes."""
        import httpx

        model = self.config.tts_model or "gpt-4o-mini-tts"
        voice = self.config.tts_voice_id or "alloy"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {self.config.tts_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": text,
                    "voice": voice,
                    "response_format": "pcm",
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"[TestAgent] OpenAI TTS error: {response.status_code} - {response.text}")
                return None

            # OpenAI returns raw PCM s16le at 24kHz — usable directly
            return response.content

    async def stream_audio_chunks(
        self, 
        audio_bytes: bytes, 
        chunk_callback: Callable[[bytes], Awaitable[None]],
        chunk_duration_ms: int = 20
    ):
        """
        Stream audio in chunks suitable for real-time transmission.
        
        Args:
            audio_bytes: Full audio buffer (PCM 16-bit)
            chunk_callback: Async callback for each chunk
            chunk_duration_ms: Duration of each chunk in milliseconds
        """
        # Calculate bytes per chunk (16-bit = 2 bytes per sample)
        bytes_per_sample = 2
        samples_per_chunk = (self.config.sample_rate * chunk_duration_ms) // 1000
        bytes_per_chunk = samples_per_chunk * bytes_per_sample
        
        # Stream chunks with appropriate timing
        offset = 0
        while offset < len(audio_bytes):
            chunk = audio_bytes[offset:offset + bytes_per_chunk]
            if chunk:
                await chunk_callback(chunk)
                # Sleep to maintain real-time playback rate
                await asyncio.sleep(chunk_duration_ms / 1000)
            offset += bytes_per_chunk
    
    def get_conversation_transcript(self) -> str:
        """Get the full conversation transcript."""
        lines = []
        for msg in self.conversation_history:
            role = "Agent" if msg["role"] == "user" else "Caller"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)
    
    async def cleanup(self):
        """Clean up resources."""
        logger.info("[TestAgent] Cleaning up")
        # Any cleanup needed for services
        pass

