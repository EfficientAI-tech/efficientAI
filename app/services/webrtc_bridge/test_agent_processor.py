"""
Test Agent Processor

In-process test agent that simulates a caller based on persona/scenario.
Uses LLM for generating responses and TTS for speech synthesis.
Receives transcripts from Retell's real-time events (no STT needed).
"""

import asyncio
import io
import os
import re
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, List, Dict, Any, Union
from uuid import UUID
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

DEFAULT_MAX_TOKENS = 400
# Reasoning models (e.g. Fireworks DeepSeek/GLM) can spend 150+ tokens thinking
# and return no text at all, which leaves the test agent silent for the turn.
REASONING_MODEL_MIN_MAX_TOKENS = 1024
RETRY_MAX_TOKENS_CAP = 2048

# Streaming replies: speak sentence by sentence so the first audio goes out
# after the first sentence, not after the whole LLM reply and TTS clip.
# Run-on text with no sentence end is cut at a comma/space past this length.
MAX_SEGMENT_CHARS = 220
# Abandon a turn whose LLM has produced no text by then (provider stall); the
# worker thread can't be killed, but the turn and the turn gate are released.
LLM_FIRST_TEXT_TIMEOUT_S = 8.0

_CANCELLED = object()


async def _get_unless_cancelled(queue: asyncio.Queue, cancel_event: Optional[asyncio.Event]):
    """``queue.get()`` that returns ``_CANCELLED`` as soon as ``cancel_event`` is set."""
    if cancel_event is None:
        return await queue.get()
    if cancel_event.is_set():
        return _CANCELLED
    getter = asyncio.ensure_future(queue.get())
    stopper = asyncio.ensure_future(cancel_event.wait())
    try:
        done, _ = await asyncio.wait({getter, stopper}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopper.cancel()
    if getter in done:
        return getter.result()
    getter.cancel()
    return _CANCELLED
# Families that reason by default but are often missing from LiteLLM's model map
# (new Fireworks/OpenRouter releases such as deepseek-v4p1-flash).
_REASONING_MODEL_NAME_RE = re.compile(
    r"deepseek-(?:r\d|v[4-9])|glm-[4-9]|qwen3|kimi-k2|gpt-oss|thinking|(?:^|/)o[1-9]\b|gpt-5",
    re.IGNORECASE,
)

TTS_ENV_KEYS = {
    "cartesia": "CARTESIA_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
    "sarvam": "SARVAM_API_KEY",
    "murf": "MURF_API_KEY",
    "smallest": "SMALLEST_API_KEY",
    "voicemaker": "VOICEMAKER_API_KEY",
}

TTS_DEFAULT_VOICES = {
    "cartesia": "a0e99841-438c-4a64-b679-ae501e7d6091",
    "elevenlabs": "JBFqnCBsd6RMkjVDRZzb",
    "openai": "alloy",
    "sarvam": "ritu",
    "murf": "en-US-natalie",
    "smallest": "daniel",
    "voicemaker": "ai3-Jony",
}

TTS_DEFAULT_MODELS = {
    "cartesia": "sonic-english",
    "elevenlabs": "eleven_multilingual_v2",
    "openai": "gpt-4o-mini-tts",
    "sarvam": "bulbul:v3",
    "murf": "GEN2",
    "smallest": "lightning-v3.1",
    "voicemaker": "neural",
}


@dataclass
class TestAgentConfig:
    """Configuration for the test agent."""
    persona_name: str = "Test Caller"
    persona_description: str = "A customer calling for assistance"
    scenario_description: str = "General inquiry call"
    scenario_goal: str = "Have a conversation and evaluate the agent"
    first_message: str = "Hello, I'm calling because I need some help."
    caller_speaks_first: bool = True
    
    # Context about the voice AI agent being tested
    agent_name: str = "Voice AI Agent"
    agent_description: str = "A voice AI assistant"
    test_agent_simulation_prompt: Optional[str] = None
    caller_system_prompt: Optional[str] = None
    
    # LLM config (from the persona's voice bundle; OpenAI gpt-4o-mini when unset)
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_credential_id: Optional[Any] = None
    llm_config: Optional[Dict[str, Any]] = None
    llm_api_key: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_max_tokens: Optional[int] = None
    
    # TTS config
    tts_provider: str = "cartesia"
    tts_api_key: Optional[str] = None
    tts_elevenlabs_api_base_url: Optional[str] = None
    tts_voice_id: Optional[str] = None
    tts_model: Optional[str] = None
    tts_config: Optional[Dict[str, Any]] = None
    
    # Audio config
    sample_rate: int = 24000
    
    # Behavior config
    max_turns: int = 20
    response_delay_ms: int = 500  # Delay before responding (more natural)
    allow_interruptions: bool = False

    organization_id: Optional[Union[UUID, str]] = None
    workspace_id: Optional[Union[UUID, str]] = None
    agent_id: Optional[Union[UUID, str]] = None
    evaluator_id: Optional[Union[UUID, str]] = None
    persona_id: Optional[Union[UUID, str]] = None
    scenario_id: Optional[Union[UUID, str]] = None
    evaluator_result_id: Optional[Union[UUID, str]] = None
    conversation_id: Optional[Union[UUID, str]] = None
    db: Any = None


def _litellm_supports_reasoning(litellm: Any, model: str) -> bool:
    try:
        return bool(litellm.supports_reasoning(model=model))
    except Exception:
        return False


def _split_ready_segments(buffer: str):
    """Yield (segment, remaining_buffer) for each speakable segment in ``buffer``.

    Uses the same sentence detection as the pipecat TTS text aggregator
    (``match_endofsentence``), so streamed replies split like the telephony
    pipeline. A boundary is only accepted once more text follows it, so a
    streamed "3." or "Dr." can still resolve to "3.5" / "Dr. Shah"; the
    remainder is flushed when the stream ends. Run-on text is cut at the last
    comma or space before MAX_SEGMENT_CHARS.
    """
    from efficientai.utils.string import match_endofsentence

    while True:
        cut = match_endofsentence(buffer)
        if not cut or cut >= len(buffer):
            cut = 0
            if len(buffer) > MAX_SEGMENT_CHARS:
                window = buffer[:MAX_SEGMENT_CHARS]
                cut = max(window.rfind(", "), window.rfind(" ")) + 1
        if cut <= 0:
            return
        segment, buffer = buffer[:cut], buffer[cut:]
        yield segment, buffer


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
        if self.config.caller_system_prompt:
            return self.config.caller_system_prompt
        simulation = self.config.test_agent_simulation_prompt or (
            f"Agent under test: {self.config.agent_name}\n\n"
            f"Agent system prompt:\n{self.config.agent_description}\n\n"
            f"Active test scenario:\n"
            f"Description: {self.config.scenario_description}\n"
            f"Goal: {self.config.scenario_goal}"
        )
        return f"""You are simulating a caller in a voice conversation. Your role is to test a voice AI agent.

TEST AGENT SIMULATION PROMPT
{simulation}

PERSONA
- Name: {self.config.persona_name}
- Description: {self.config.persona_description}

INSTRUCTIONS:
1. You are CALLING the voice AI agent described in the test agent simulation prompt
2. Stay in character as the persona described
3. Follow the scenario and work toward the goal
4. Speak naturally as if on a phone call
5. Keep responses concise (1-3 sentences) for natural conversation flow
6. Ask relevant questions to test the agent's capabilities
7. Respond appropriately to what the agent says
8. If the conversation naturally concludes or you've achieved the goal, say goodbye
9. Respond ONLY with what you would say - no stage directions or descriptions

You are calling: {self.config.agent_name}
After {self.config.max_turns} exchanges, wrap up the conversation politely."""

    async def initialize(self):
        """Initialize LLM and TTS services."""
        try:
            # Initialize LLM
            # With db/org context, llm_service resolves the bundle's provider key at
            # call time (any provider). Only the direct-OpenAI fallback needs a key here.
            uses_llm_service = bool(self.config.db and self.config.organization_id)
            llm_api_key = self.config.llm_api_key or os.getenv("OPENAI_API_KEY")
            if not llm_api_key and not uses_llm_service:
                raise ValueError("OpenAI API key not configured")
            if not llm_api_key:
                logger.info(
                    f"[TestAgent] LLM {self.config.llm_provider}/{self.config.llm_model} "
                    "via llm_service (key resolved per call)"
                )
            
            if llm_api_key and EFFICIENTAI_AVAILABLE:
                self._llm_service = OpenAILLMService(
                    api_key=llm_api_key,
                    model=self.config.llm_model
                )
            elif llm_api_key:
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
            Audio bytes of the first message, or None if failed or caller waits
        """
        if not self.config.caller_speaks_first:
            logger.info("[TestAgent] Caller configured to wait for production agent greeting")
            return None

        try:
            first_text = (self.config.first_message or "").strip()
            if not first_text:
                return None
            
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
        
        if self.agent_is_talking and not self.config.allow_interruptions:
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

        except asyncio.CancelledError:
            logger.warning(f"[TestAgent] Turn {self.turn_count} cancelled before response was spoken")
            raise
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
    
    def _build_simulation_context(self):
        from app.services.usage.context import usage_context_for_test_agent_simulation

        if not self.config.organization_id:
            return None
        return usage_context_for_test_agent_simulation(
            organization_id=UUID(str(self.config.organization_id)),
            workspace_id=(
                UUID(str(self.config.workspace_id))
                if self.config.workspace_id
                else None
            ),
            agent_id=UUID(str(self.config.agent_id)) if self.config.agent_id else None,
            evaluator_id=(
                UUID(str(self.config.evaluator_id)) if self.config.evaluator_id else None
            ),
            persona_id=UUID(str(self.config.persona_id)) if self.config.persona_id else None,
            scenario_id=UUID(str(self.config.scenario_id)) if self.config.scenario_id else None,
            evaluator_result_id=(
                UUID(str(self.config.evaluator_result_id))
                if self.config.evaluator_result_id
                else None
            ),
            conversation_id=(
                UUID(str(self.config.conversation_id))
                if self.config.conversation_id
                else None
            ),
        )

    def _is_reasoning_model(self) -> bool:
        cached = getattr(self, "_reasoning_model", None)
        if cached is not None:
            return cached
        try:
            import litellm

            from app.services.ai.llm_service import _LITELLM_PROVIDER_PREFIX

            provider = (self.config.llm_provider or "openai").lower()
            prefix = _LITELLM_PROVIDER_PREFIX.get(provider, provider)
            model = self.config.llm_model or ""
            candidates = [model, f"{prefix}/{model}"]
            if prefix == "fireworks_ai" and "/" not in model:
                # LiteLLM's model map keys Fireworks models by their full path.
                candidates.append(f"{prefix}/accounts/fireworks/models/{model}")
            self._reasoning_model = any(
                _litellm_supports_reasoning(litellm, name) for name in candidates
            )
        except Exception:
            self._reasoning_model = False
        if not self._reasoning_model:
            self._reasoning_model = bool(_REASONING_MODEL_NAME_RE.search(self.config.llm_model or ""))
        return self._reasoning_model

    def _effective_max_tokens(self) -> int:
        """Reply token budget; reasoning models spend part of it before any text."""
        configured = self.config.llm_max_tokens
        if self._is_reasoning_model():
            return max(configured or 0, REASONING_MODEL_MIN_MAX_TOKENS)
        return configured if configured is not None else DEFAULT_MAX_TOKENS

    def _overrides_reasoning(self) -> bool:
        config = self.config.llm_config or {}
        return (
            self._is_reasoning_model()
            and "reasoning_effort" not in config
            and "thinking" not in config
        )

    def _effective_llm_config(self, *, allow_reasoning_override: bool = True) -> Optional[Dict[str, Any]]:
        """Bundle LLM config, with reasoning turned down for live turns unless set."""
        config = dict(self.config.llm_config or {})
        if allow_reasoning_override and self._overrides_reasoning():
            config["reasoning_effort"] = "low"
        return config or None

    def _sync_llm_call(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        allow_reasoning_override: bool = True,
        on_text_delta: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        from app.services.ai.llm_service import llm_service
        from app.services.usage.context import llm_usage_context

        ctx = self._build_simulation_context()
        credential_id = self.config.llm_credential_id
        kwargs: Dict[str, Any] = dict(
            messages=messages,
            llm_provider=self._llm_provider_enum(),
            llm_model=self.config.llm_model,
            organization_id=UUID(str(self.config.organization_id)),
            db=self.config.db,
            temperature=(
                self.config.llm_temperature
                if self.config.llm_temperature is not None
                else 0.7
            ),
            max_tokens=max_tokens or self._effective_max_tokens(),
            llm_config=self._effective_llm_config(allow_reasoning_override=allow_reasoning_override),
            credential_id=UUID(str(credential_id)) if credential_id else None,
        )
        if on_text_delta is not None:
            kwargs["on_text_delta"] = on_text_delta
        if ctx is not None:
            with llm_usage_context(ctx):
                return llm_service.generate_response(**kwargs)
        return llm_service.generate_response(**kwargs)

    def _llm_provider_enum(self):
        from app.models.database import ModelProvider

        try:
            return ModelProvider((self.config.llm_provider or "openai").lower())
        except ValueError:
            logger.warning(
                f"[TestAgent] Unknown LLM provider '{self.config.llm_provider}', using OpenAI"
            )
            return ModelProvider.OPENAI

    async def _generate_via_llm_service(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """One llm_service call, retried once if it errors on the reasoning
        override or returns no text (budget spent on reasoning)."""
        allow_override = True
        try:
            result = await asyncio.to_thread(self._sync_llm_call, messages)
        except Exception as e:
            if not self._overrides_reasoning():
                raise
            logger.warning(f"[TestAgent] LLM call failed with reasoning_effort override, retrying without: {e}")
            allow_override = False
            result = await asyncio.to_thread(
                self._sync_llm_call, messages, allow_reasoning_override=False
            )

        text = (result.get("text") or "").strip()
        if text:
            return text

        retry_tokens = min(self._effective_max_tokens() * 2, RETRY_MAX_TOKENS_CAP)
        logger.warning(
            f"[TestAgent] LLM returned no text (finish_reason={result.get('finish_reason')}); "
            f"retrying once with max_tokens={retry_tokens}"
        )
        result = await asyncio.to_thread(
            self._sync_llm_call,
            messages,
            max_tokens=retry_tokens,
            allow_reasoning_override=allow_override,
        )
        return (result.get("text") or "").strip() or None

    async def _generate_llm_response(self) -> Optional[str]:
        """Generate a response using the LLM."""
        try:
            messages = [
                {"role": "system", "content": self._system_prompt}
            ] + self.conversation_history

            if self.config.db and self.config.organization_id:
                return await self._generate_via_llm_service(messages)

            if (self.config.llm_provider or "openai").lower() != "openai":
                logger.warning(
                    f"[TestAgent] No db/org context for {self.config.llm_provider} LLM; "
                    "falling back to direct OpenAI client"
                )

            import openai
            client = getattr(self, "_openai_client", None)
            if not client:
                api_key = self.config.llm_api_key or os.getenv("OPENAI_API_KEY")
                client = openai.AsyncOpenAI(api_key=api_key)

            is_openai = (self.config.llm_provider or "openai").lower() == "openai"
            response = await client.chat.completions.create(
                model=self.config.llm_model if is_openai else "gpt-4o-mini",
                messages=messages,
                max_tokens=(
                    self.config.llm_max_tokens
                    if self.config.llm_max_tokens is not None
                    else DEFAULT_MAX_TOKENS
                ),
                temperature=(
                    self.config.llm_temperature
                    if self.config.llm_temperature is not None
                    else 0.7
                ),
            )

            self._record_llm_usage(response=response)

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"[TestAgent] LLM error: {e}")
            return None
    
    async def _text_to_speech(self, text: str) -> Optional[bytes]:
        """Convert text to speech audio using the configured TTS provider."""
        provider = self.config.tts_provider.lower()
        try:
            if provider == "elevenlabs":
                audio = await self._tts_elevenlabs(text)
            elif provider == "openai":
                audio = await self._tts_openai(text)
            elif provider == "sarvam":
                audio = await self._tts_sarvam(text)
            elif provider == "voicemaker":
                audio = await self._tts_voicemaker(text)
            elif provider == "smallest":
                audio = await self._tts_smallest(text)
            elif provider == "murf":
                audio = await self._tts_murf(text)
            else:
                audio = await self._tts_cartesia(text)

            if audio:
                self._record_tts_usage(text=text)
            return audio
        except Exception as e:
            logger.error(f"[TestAgent] TTS ({provider}) error: {e}")
            return None

    def _tts_settings(self) -> Dict[str, Any]:
        return dict(self.config.tts_config or {})

    def _record_tts_usage(self, *, text: str) -> None:
        ctx = self._build_simulation_context()
        if ctx is None:
            return
        try:
            from app.services.usage.context import llm_usage_context
            from app.services.usage.llm_usage import record_tts_usage

            model = self.config.tts_model or TTS_DEFAULT_MODELS.get(
                self.config.tts_provider.lower(), "unknown"
            )
            with llm_usage_context(ctx):
                record_tts_usage(
                    model,
                    characters=len(text or ""),
                    organization_id=ctx.organization_id,
                )
        except Exception as exc:
            logger.debug("test agent tts usage record skipped: {}", exc)

    def _record_llm_usage(self, *, response: Any) -> None:
        ctx = self._build_simulation_context()
        if ctx is None:
            return
        try:
            from app.services.usage.context import llm_usage_context
            from app.services.usage.llm_usage import record_llm_usage
            from app.services.usage.normalize import UsageSnapshot, normalize_llm_usage

            snapshot = normalize_llm_usage(raw_response=response)
            model = self.config.llm_model or "unknown"
            with llm_usage_context(ctx):
                record_llm_usage(
                    model,
                    snapshot,
                    organization_id=ctx.organization_id,
                )
        except Exception as exc:
            logger.debug("test agent llm usage record skipped: {}", exc)

    async def _tts_cartesia(self, text: str) -> Optional[bytes]:
        """Synthesize speech via Cartesia."""
        import httpx

        settings = self._tts_settings()
        payload: Dict[str, Any] = {
            "model_id": self.config.tts_model or "sonic-english",
            "transcript": text,
            "voice": {"mode": "id", "id": self.config.tts_voice_id},
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": self.config.sample_rate,
            },
        }
        if settings.get("speed"):
            payload["speed"] = settings["speed"]
        gen = settings.get("generation_config")
        if gen:
            payload["generation_config"] = gen
        elif any(k in settings for k in ("generation_config_speed", "generation_config_volume", "generation_config_emotion")):
            payload["generation_config"] = {
                k.replace("generation_config_", ""): settings[k]
                for k in ("generation_config_speed", "generation_config_volume", "generation_config_emotion")
                if k in settings
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "X-API-Key": self.config.tts_api_key,
                    "Cartesia-Version": "2024-06-10",
                    "Content-Type": "application/json",
                },
                json=payload,
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

        # Request raw PCM directly from ElevenLabs (avoids ffmpeg/pydub dependency)
        pcm_format = f"pcm_{self.config.sample_rate}"
        settings = self._tts_settings()
        voice_settings: Dict[str, Any] = {
            "stability": settings.get("stability", 0.5),
            "similarity_boost": settings.get("similarity_boost", 0.75),
        }
        for key in ("style", "use_speaker_boost", "speed"):
            if settings.get(key) is not None:
                voice_settings[key] = settings[key]

        request_json: Dict[str, Any] = {
            "text": text,
            "model_id": model_id,
            "voice_settings": voice_settings,
        }
        if settings.get("apply_text_normalization") is not None:
            request_json["apply_text_normalization"] = settings["apply_text_normalization"]

        from app.services.voice_providers.elevenlabs_api_url import elevenlabs_http_origin

        origin = elevenlabs_http_origin(self.config.tts_elevenlabs_api_base_url)
        async with httpx.AsyncClient() as client:
            url = f"{origin.rstrip('/')}/v1/text-to-speech/{voice_id}?output_format={pcm_format}"
            if settings.get("optimize_streaming_latency") is not None:
                url += f"&optimize_streaming_latency={int(settings['optimize_streaming_latency'])}"
            response = await client.post(
                url,
                headers={
                    "xi-api-key": self.config.tts_api_key,
                    "Content-Type": "application/json",
                },
                json=request_json,
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"[TestAgent] ElevenLabs TTS error: {response.status_code} - {response.text}")
                return None

            return response.content

    async def _tts_openai(self, text: str) -> Optional[bytes]:
        """Synthesize speech via OpenAI TTS and return raw PCM s16le bytes."""
        import httpx

        model = self.config.tts_model or "gpt-4o-mini-tts"
        voice = self.config.tts_voice_id or "alloy"
        settings = self._tts_settings()
        payload: Dict[str, Any] = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "pcm",
        }
        if settings.get("speed") is not None:
            payload["speed"] = settings["speed"]
        if settings.get("instructions"):
            payload["instructions"] = settings["instructions"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {self.config.tts_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"[TestAgent] OpenAI TTS error: {response.status_code} - {response.text}")
                return None

            # OpenAI always returns raw PCM s16le at 24kHz.
            # Resample to the target sample_rate when it differs (e.g. 16kHz for ElevenLabs).
            OPENAI_PCM_RATE = 24000
            if self.config.sample_rate != OPENAI_PCM_RATE:
                try:
                    from pydub import AudioSegment
                    seg = AudioSegment(
                        data=response.content,
                        sample_width=2,
                        frame_rate=OPENAI_PCM_RATE,
                        channels=1,
                    )
                    seg = seg.set_frame_rate(self.config.sample_rate)
                    logger.debug(
                        f"[TestAgent] Resampled OpenAI TTS: {OPENAI_PCM_RATE}→{self.config.sample_rate}Hz "
                        f"({len(response.content)}→{len(seg.raw_data)} bytes)"
                    )
                    return seg.raw_data
                except ImportError:
                    logger.warning("[TestAgent] pydub not installed — sending 24kHz audio without resampling")

            return response.content

    async def _tts_sarvam(self, text: str) -> Optional[bytes]:
        """Synthesize speech via Sarvam HTTP API and return raw PCM s16le bytes."""
        from efficientai.services.sarvam.http_tts import synthesize_sarvam_bytes

        voice = self.config.tts_voice_id or TTS_DEFAULT_VOICES["sarvam"]
        model = self.config.tts_model or TTS_DEFAULT_MODELS["sarvam"]
        settings = self._tts_settings()
        config: Dict[str, Any] = {"sample_rate": self.config.sample_rate}
        for key in ("pitch", "pace", "loudness", "temperature", "enable_preprocessing"):
            if settings.get(key) is not None:
                config[key] = settings[key]

        audio_wav, _ = await asyncio.to_thread(
            synthesize_sarvam_bytes,
            text=text,
            model=model,
            api_key=self.config.tts_api_key,
            voice=voice,
            config=config,
        )

        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(io.BytesIO(audio_wav), format="wav")
            seg = seg.set_frame_rate(self.config.sample_rate).set_channels(1).set_sample_width(2)
            return seg.raw_data
        except ImportError:
            import wave
            with wave.open(io.BytesIO(audio_wav), "rb") as wf:
                frames = wf.readframes(wf.getnframes())
                if wf.getframerate() != self.config.sample_rate:
                    logger.warning(
                        f"[TestAgent] Sarvam WAV at {wf.getframerate()}Hz but target is "
                        f"{self.config.sample_rate}Hz — install pydub for resampling"
                    )
                return frames

    async def _tts_voicemaker(self, text: str) -> Optional[bytes]:
        """Synthesize speech via VoiceMaker HTTP API and return raw PCM s16le bytes."""
        from efficientai.services.voicemaker.http_tts import synthesize_voicemaker_bytes

        voice = self.config.tts_voice_id or TTS_DEFAULT_VOICES["voicemaker"]
        model = self.config.tts_model or TTS_DEFAULT_MODELS["voicemaker"]
        settings = self._tts_settings()
        config: Dict[str, Any] = {"sample_rate_hz": settings.get("sample_rate_hz", self.config.sample_rate)}
        if settings.get("output_format"):
            config["output_format"] = settings["output_format"]

        audio_mp3, _ = await asyncio.to_thread(
            synthesize_voicemaker_bytes,
            text=text,
            model=model,
            api_key=self.config.tts_api_key,
            voice=voice,
            config=config,
        )

        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(io.BytesIO(audio_mp3), format="mp3")
            seg = seg.set_frame_rate(self.config.sample_rate).set_channels(1).set_sample_width(2)
            return seg.raw_data
        except ImportError:
            logger.error("[TestAgent] pydub required to decode VoiceMaker MP3 audio")
            return None

    async def _tts_smallest(self, text: str) -> Optional[bytes]:
        """Synthesize speech via Smallest HTTP API."""
        from efficientai.services.smallest.http_tts import synthesize_smallest_bytes

        voice = self.config.tts_voice_id or TTS_DEFAULT_VOICES["smallest"]
        model = self.config.tts_model or TTS_DEFAULT_MODELS["smallest"]
        settings = self._tts_settings()
        config: Dict[str, Any] = {"sample_rate": self.config.sample_rate}
        if settings.get("speed") is not None:
            config["speed"] = settings["speed"]
        if settings.get("language"):
            config["language"] = settings["language"]

        audio_bytes, _ = await asyncio.to_thread(
            synthesize_smallest_bytes,
            text=text,
            model=model,
            api_key=self.config.tts_api_key,
            voice=voice,
            config=config,
        )
        return audio_bytes

    async def _tts_murf(self, text: str) -> Optional[bytes]:
        """Synthesize speech via Murf HTTP API."""
        from efficientai.services.murf.tts import synthesize_murf_stream_bytes

        voice = self.config.tts_voice_id or TTS_DEFAULT_VOICES["murf"]
        model = self.config.tts_model or TTS_DEFAULT_MODELS["murf"]
        settings = self._tts_settings()
        config: Dict[str, Any] = {"sample_rate": self.config.sample_rate}
        for key in ("speed", "rate", "pitch", "style"):
            if settings.get(key) is not None:
                config[key] = settings[key]

        audio_bytes, _ = await asyncio.to_thread(
            synthesize_murf_stream_bytes,
            text=text,
            model=model,
            api_key=self.config.tts_api_key,
            voice=voice,
            config=config,
        )
        return audio_bytes

    async def process_agent_transcript_streaming(
        self,
        transcript: str,
        speak: Callable[[bytes], Awaitable[int]],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Optional[str]:
        """Reply to ``transcript``, speaking each sentence as soon as it is ready.

        The LLM is streamed; each complete sentence is synthesized while the
        previous one plays. ``speak`` sends one segment and returns the bytes
        actually sent. Setting ``cancel_event`` (barge-in) stops generation and
        playback, and history is trimmed to what was spoken.

        Returns the reply text, or None if nothing was generated.
        """
        if not transcript or not transcript.strip():
            return None
        if self.is_processing:
            logger.warning(f"[TestAgent] Already processing; dropping transcript: {transcript[:60]}...")
            return None

        self.is_processing = True
        loop = asyncio.get_running_loop()
        turn_started = loop.time()
        text_q: asyncio.Queue = asyncio.Queue()
        segment_q: asyncio.Queue = asyncio.Queue(maxsize=2)
        generated: List[str] = []
        spoken_chars = 0
        interrupted = False
        tasks: List[asyncio.Task] = []

        def cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        try:
            logger.info(f"[TestAgent] Processing agent transcript (streaming): {transcript[:100]}...")
            self.conversation_history.append({"role": "user", "content": transcript})
            self.turn_count += 1

            if self.turn_count >= self.config.max_turns:
                logger.info(f"[TestAgent] Max turns ({self.config.max_turns}) reached, ending call")
                self.should_end_call = True
                text_q.put_nowait("Thank you so much for your help. I think I have everything I need. Goodbye!")
                text_q.put_nowait(None)
            else:
                tasks.append(asyncio.create_task(self._stream_llm_text(text_q), name="test-agent-llm"))
            tasks.append(
                asyncio.create_task(
                    self._synthesize_segments(text_q, segment_q, generated, cancelled),
                    name="test-agent-tts",
                )
            )

            first = True
            while not interrupted:
                item = await _get_unless_cancelled(segment_q, cancel_event)
                if item is _CANCELLED:
                    interrupted = True
                    break
                if item is None:
                    break
                segment_text, chunk_q = item
                received = sent_total = 0
                while True:
                    chunk = await _get_unless_cancelled(chunk_q, cancel_event)
                    if chunk is _CANCELLED:
                        interrupted = True
                        break
                    if chunk is None:
                        break
                    received += len(chunk)
                    if cancelled():
                        interrupted = True
                        break
                    if first:
                        first = False
                        if self.config.response_delay_ms > 0:
                            await asyncio.sleep(self.config.response_delay_ms / 1000)
                        logger.info(
                            f"[TestAgent] First audio after {loop.time() - turn_started:.2f}s "
                            f"(turn {self.turn_count}): {segment_text[:50]}..."
                        )
                    sent = await speak(chunk) or 0
                    sent_total += sent
                    if cancelled() and sent < len(chunk):
                        interrupted = True
                        break
                if interrupted:
                    # Rough share of this sentence that was heard (its full
                    # length may not have arrived yet).
                    spoken_chars += int(len(segment_text) * sent_total / max(1, received))
                    break
                spoken_chars += len(segment_text) + 1
        except asyncio.CancelledError:
            logger.warning(f"[TestAgent] Turn {self.turn_count} cancelled before response was spoken")
            raise
        except Exception as e:
            logger.error(f"[TestAgent] Error in streaming reply: {e}", exc_info=True)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            streamer = self._live_tts_streamer()
            if streamer is not None:
                if interrupted or cancelled():
                    await streamer.interrupt()
                else:
                    await streamer.finish_utterance()
            self.is_processing = False

        response_text = " ".join(generated).strip()
        if not response_text:
            logger.warning("[TestAgent] No response generated")
            return None

        self.conversation_history.append({"role": "assistant", "content": response_text})
        if interrupted or cancelled():
            fraction = min(1.0, spoken_chars / max(1, len(response_text)))
            logger.info(
                f"[TestAgent] Barged in after {fraction:.0%} of reply (turn {self.turn_count})"
            )
            self.mark_last_response_interrupted(fraction)
        if self.on_response_text:
            await self.on_response_text(response_text)
        logger.info(f"[TestAgent] Generated response (turn {self.turn_count}): {response_text[:50]}...")

        if self.should_end_call and self.on_call_should_end and not interrupted:
            await asyncio.sleep(2)
            await self.on_call_should_end()
        return response_text

    async def _stream_llm_text(self, text_q: asyncio.Queue) -> None:
        """Push LLM text deltas into ``text_q``, then None. Falls back to the
        non-streaming call (with its retries) when the stream yields no text."""
        loop = asyncio.get_running_loop()
        emitted = False
        requested_at = loop.time()
        first_text = asyncio.Event()

        def on_delta(delta: str) -> None:
            nonlocal emitted
            if not emitted:
                loop.call_soon_threadsafe(first_text.set)
                # Thread-safe: only reads the loop clock.
                logger.info(
                    f"[TestAgent] LLM first text after {loop.time() - requested_at:.2f}s "
                    f"({self.config.llm_provider}/{self.config.llm_model})"
                )
            emitted = True
            loop.call_soon_threadsafe(text_q.put_nowait, delta)

        messages = [{"role": "system", "content": self._system_prompt}] + self.conversation_history
        try:
            if self.config.db and self.config.organization_id:
                streamed_text = ""
                try:
                    call = asyncio.ensure_future(
                        asyncio.to_thread(self._sync_llm_call, messages, on_text_delta=on_delta)
                    )
                    waiter = asyncio.ensure_future(first_text.wait())
                    done, _ = await asyncio.wait(
                        {call, waiter}, timeout=LLM_FIRST_TEXT_TIMEOUT_S, return_when=asyncio.FIRST_COMPLETED
                    )
                    waiter.cancel()
                    if not done:
                        logger.warning(
                            f"[TestAgent] LLM produced no text within {LLM_FIRST_TEXT_TIMEOUT_S:.0f}s "
                            f"({self.config.llm_provider}/{self.config.llm_model}); skipping turn"
                        )
                        return
                    result = await call
                    streamed_text = (result.get("text") or "").strip()
                except Exception as e:
                    if emitted:
                        logger.warning(f"[TestAgent] LLM stream ended early: {e}")
                    else:
                        logger.warning(f"[TestAgent] LLM stream failed, retrying without streaming: {e}")
                if not emitted:
                    # Paths that can't stream (e.g. OpenRouter Jev) still return
                    # text; only re-call the LLM when there is genuinely none.
                    text = streamed_text or await self._generate_via_llm_service(messages)
                    if text:
                        text_q.put_nowait(text)
            else:
                text = await self._generate_llm_response()
                if text:
                    text_q.put_nowait(text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[TestAgent] LLM error: {e}")
        finally:
            # Deltas scheduled from the worker thread land before this sentinel.
            loop.call_soon(text_q.put_nowait, None)

    async def _synthesize_segments(
        self,
        text_q: asyncio.Queue,
        segment_q: asyncio.Queue,
        generated: List[str],
        cancelled: Callable[[], bool],
    ) -> None:
        """Split streamed text into sentences and synthesize each in order.

        Each segment is queued with its own chunk queue as soon as synthesis
        starts, so playback begins with the first streamed chunk while this
        worker keeps the provider busy with the next sentence.
        """
        buffer = ""

        async def emit(segment: str) -> None:
            segment = segment.strip()
            if not segment or cancelled():
                return
            generated.append(segment)
            chunk_q: asyncio.Queue = asyncio.Queue()
            await segment_q.put((segment, chunk_q))
            try:
                await self._synthesize_into(segment, chunk_q, cancelled)
            finally:
                chunk_q.put_nowait(None)

        try:
            while True:
                delta = await text_q.get()
                if delta is None:
                    break
                buffer += delta
                for segment, buffer in _split_ready_segments(buffer):
                    await emit(segment)
            await emit(buffer)
        except asyncio.CancelledError:
            # Barge-in cleanup: the player has stopped reading, so never block
            # on the bounded queue here (a blocked put would hang the turn).
            raise
        except Exception as e:
            logger.error(f"[TestAgent] Segment synthesis failed: {e}", exc_info=True)
        # Not in ``finally``: after cancellation this put could wait forever on a
        # full queue that nobody drains. Here the player is still reading (or we
        # get cancelled while waiting, which is fine).
        await segment_q.put(None)

    def _live_tts_streamer(self):
        streamer = getattr(self, "tts_streamer", None)
        return streamer if streamer is not None and streamer.healthy else None

    async def _synthesize_into(
        self,
        segment: str,
        chunk_q: asyncio.Queue,
        cancelled: Callable[[], bool],
    ) -> None:
        """Stream ``segment`` audio into ``chunk_q`` via the provider's streaming
        TTS; fall back to one-shot TTS if streaming is unavailable or fails
        before producing audio."""
        streamer = self._live_tts_streamer()
        if streamer is not None:
            produced = False
            try:
                async for chunk in streamer.synthesize(segment):
                    if cancelled():
                        return
                    produced = True
                    chunk_q.put_nowait(chunk)
                if produced:
                    self._record_tts_usage(text=segment)
                    return
            except RuntimeError as e:
                if produced:
                    return
                logger.warning(f"[TestAgent] Streaming TTS failed, using one-shot TTS for segment: {e}")
        audio = await self._text_to_speech(segment)
        if audio:
            chunk_q.put_nowait(audio)
        else:
            logger.warning(f"[TestAgent] TTS returned no audio for segment: {segment[:50]}...")

    async def stream_audio_chunks(
        self, 
        audio_bytes: bytes, 
        chunk_callback: Callable[[bytes], Awaitable[None]],
        chunk_duration_ms: int = 20,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> int:
        """
        Stream audio in chunks suitable for real-time transmission.
        
        Args:
            audio_bytes: Full audio buffer (PCM 16-bit)
            chunk_callback: Async callback for each chunk
            chunk_duration_ms: Duration of each chunk in milliseconds
            cancel_event: When set, stop early (the production agent barged in)

        Returns:
            Number of audio bytes actually sent.
        """
        # Calculate bytes per chunk (16-bit = 2 bytes per sample)
        bytes_per_sample = 2
        samples_per_chunk = (self.config.sample_rate * chunk_duration_ms) // 1000
        bytes_per_chunk = samples_per_chunk * bytes_per_sample
        
        # Pace against the clock (not sleep-per-chunk) so the stream keeps up
        # with real time; per-chunk sleeps overshoot and accumulate drift.
        loop = asyncio.get_running_loop()
        next_send = loop.time()
        offset = 0
        while offset < len(audio_bytes):
            if cancel_event is not None and cancel_event.is_set():
                break
            chunk = audio_bytes[offset:offset + bytes_per_chunk]
            if chunk:
                await chunk_callback(chunk)
                next_send += len(chunk) / bytes_per_sample / self.config.sample_rate
                delay = next_send - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
            offset += bytes_per_chunk
        return min(offset, len(audio_bytes))

    def mark_last_response_interrupted(self, fraction_spoken: float) -> None:
        """Trim our last reply in history to roughly what was actually spoken."""
        for entry in reversed(self.conversation_history):
            if entry.get("role") != "assistant":
                continue
            words = (entry.get("content") or "").split()
            keep = max(0, min(len(words), int(round(len(words) * fraction_spoken))))
            spoken = " ".join(words[:keep])
            entry["content"] = f"{spoken} — [interrupted]" if spoken else "[interrupted before speaking]"
            break

    def record_stt_usage(self, *, model: str, audio_seconds: float) -> None:
        ctx = self._build_simulation_context()
        if ctx is None:
            return
        try:
            from app.services.usage.context import llm_usage_context
            from app.services.usage.llm_usage import record_stt_usage

            with llm_usage_context(ctx):
                record_stt_usage(
                    model,
                    audio_seconds=audio_seconds,
                    organization_id=ctx.organization_id,
                )
        except Exception as exc:
            logger.debug("test agent stt usage record skipped: {}", exc)

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

