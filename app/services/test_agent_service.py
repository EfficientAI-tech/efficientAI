"""
Test Agent Service - Orchestrates conversations between test AI agent and voice AI agent.
"""

import time
import tempfile
import os
import uuid
import warnings
import subprocess
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timezone
import librosa
import soundfile as sf

from app.models.database import (
    TestAgentConversation, TestAgentConversationStatus,
    Agent, Persona, Scenario, VoiceBundle
)
from app.services.transcription_service import transcription_service
from app.services.llm_service import llm_service
from app.services.tts_service import tts_service
from app.services.s3_service import s3_service
from sqlalchemy.orm import Session


class TestAgentService:
    """Service for managing test agent conversations."""

    def __init__(self):
        """Initialize test agent service."""
        pass

    def _build_system_prompt(
        self,
        agent: Agent,
        persona: Persona,
        scenario: Scenario,
        db: Session
    ) -> str:
        """Build system prompt from agent, persona, and scenario."""
        prompt_parts = []   
        
        # Agent information
        prompt_parts.append(f"You are a test agent interacting with: {agent.name}")
        if agent.description:
            prompt_parts.append(f"Agent description: {agent.description}")
        prompt_parts.append(f"Agent phone number: {agent.phone_number}")
        prompt_parts.append(f"Agent language: {agent.language.value}")
        
        # Persona information
        prompt_parts.append(f"\nYou are role-playing as: {persona.name}")
        prompt_parts.append(f"Persona language: {persona.language.value}")
        prompt_parts.append(f"Persona accent: {persona.accent.value}")
        prompt_parts.append(f"Persona gender: {persona.gender.value}")
        if persona.background_noise:
            prompt_parts.append(f"Background noise: {persona.background_noise.value}")
        
        # Scenario information
        prompt_parts.append(f"\nScenario: {scenario.name}")
        if scenario.description:
            prompt_parts.append(f"Scenario description: {scenario.description}")
        if scenario.required_info:
            prompt_parts.append(f"Required information to collect: {scenario.required_info}")
        
        # Instructions
        prompt_parts.append("\nInstructions:")
        prompt_parts.append("- Respond naturally and in character as the persona")
        prompt_parts.append("- Follow the scenario objectives")
        prompt_parts.append("- Keep responses concise and conversational")
        prompt_parts.append("- Do not break character")
        
        return "\n".join(prompt_parts)

    def _convert_webm_to_wav(self, webm_bytes: bytes) -> bytes:
        """Convert WebM audio bytes to WAV format using ffmpeg or pydub."""
        webm_path = None
        wav_path = None
        try:
            # Save WebM to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as webm_file:
                webm_file.write(webm_bytes)
                webm_path = webm_file.name
            
            # Create WAV output path
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as wav_file:
                wav_path = wav_file.name
            
            # Try ffmpeg directly first (most reliable)
            try:
                result = subprocess.run(
                    ['ffmpeg', '-i', webm_path, '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', '-y', wav_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0 and os.path.exists(wav_path):
                    with open(wav_path, 'rb') as f:
                        wav_bytes = f.read()
                    return wav_bytes
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                # ffmpeg not available or failed, try pydub
                pass
            
            # Try using pydub (also requires ffmpeg but handles it better)
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(webm_path, format="webm")
                audio.export(wav_path, format="wav", parameters=["-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1"])
                
                if os.path.exists(wav_path):
                    with open(wav_path, 'rb') as f:
                        wav_bytes = f.read()
                    return wav_bytes
            except ImportError:
                # pydub not available
                pass
            except Exception:
                # pydub failed
                pass
            
            # Fallback to librosa (requires ffmpeg via audioread)
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=FutureWarning)
                warnings.filterwarnings('ignore', category=UserWarning, message='PySoundFile failed')
                
                try:
                    y, sr = librosa.load(webm_path, sr=16000, mono=True)
                except Exception as e:
                    raise RuntimeError(
                        f"Could not convert WebM to WAV. Please install ffmpeg:\n"
                        f"  Ubuntu/Debian: sudo apt-get install ffmpeg\n"
                        f"  macOS: brew install ffmpeg\n"
                        f"  Windows: Download from https://ffmpeg.org/download.html\n"
                        f"Error: {str(e)}"
                    )
            
            # Save as WAV using soundfile
            sf.write(wav_path, y, sr, format='WAV', subtype='PCM_16')
            
            # Read WAV bytes
            with open(wav_path, 'rb') as f:
                wav_bytes = f.read()
            
            return wav_bytes
        except Exception as e:
            raise RuntimeError(f"Failed to convert WebM to WAV: {str(e)}")
        finally:
            # Clean up temp files
            for path in [webm_path, wav_path]:
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except Exception:
                        pass

    def create_conversation(
        self,
        agent_id: UUID,
        persona_id: UUID,
        scenario_id: UUID,
        voice_bundle_id: UUID,
        organization_id: UUID,
        db: Session,
        conversation_metadata: Optional[Dict[str, Any]] = None
    ) -> TestAgentConversation:
        """Create a new test agent conversation."""
        # Verify all entities exist
        agent = db.query(Agent).filter(
            Agent.id == agent_id,
            Agent.organization_id == organization_id
        ).first()
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        
        persona = db.query(Persona).filter(
            Persona.id == persona_id,
            Persona.organization_id == organization_id
        ).first()
        if not persona:
            raise ValueError(f"Persona {persona_id} not found")
        
        scenario = db.query(Scenario).filter(
            Scenario.id == scenario_id,
            Scenario.organization_id == organization_id
        ).first()
        if not scenario:
            raise ValueError(f"Scenario {scenario_id} not found")
        
        voice_bundle = db.query(VoiceBundle).filter(
            VoiceBundle.id == voice_bundle_id,
            VoiceBundle.organization_id == organization_id,
            VoiceBundle.is_active == True
        ).first()
        if not voice_bundle:
            raise ValueError(f"VoiceBundle {voice_bundle_id} not found or inactive")
        
        # Create conversation
        conversation = TestAgentConversation(
            organization_id=organization_id,
            agent_id=agent_id,
            persona_id=persona_id,
            scenario_id=scenario_id,
            voice_bundle_id=voice_bundle_id,
            status=TestAgentConversationStatus.INITIALIZING,
            live_transcription=[],
            conversation_metadata=conversation_metadata or {}
        )
        
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        
        return conversation

    def process_audio_chunk(
        self,
        conversation_id: UUID,
        audio_chunk: bytes,
        organization_id: UUID,
        db: Session,
        chunk_timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Process an audio chunk from the voice AI agent.
        
        This method:
        1. Saves audio chunk temporarily
        2. Transcribes using STT from voice bundle
        3. Generates response using LLM with system prompt
        4. Converts response to speech using TTS
        5. Updates conversation with new turn
        6. Returns response audio and transcription
        
        Args:
            conversation_id: Conversation ID
            audio_chunk: Audio bytes from voice AI agent
            organization_id: Organization ID
            db: Database session
            chunk_timestamp: Timestamp of this chunk (seconds from start)
            
        Returns:
            Dictionary with response audio bytes, transcription, and metadata
        """
        # Get conversation
        conversation = db.query(TestAgentConversation).filter(
            TestAgentConversation.id == conversation_id,
            TestAgentConversation.organization_id == organization_id
        ).first()
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")
        
        if conversation.status != TestAgentConversationStatus.ACTIVE:
            raise ValueError(f"Conversation is not active (status: {conversation.status})")
        
        # Get voice bundle and related entities
        voice_bundle = db.query(VoiceBundle).filter(
            VoiceBundle.id == conversation.voice_bundle_id
        ).first()
        if not voice_bundle:
            raise ValueError("Voice bundle not found")
        
        agent = db.query(Agent).filter(Agent.id == conversation.agent_id).first()
        persona = db.query(Persona).filter(Persona.id == conversation.persona_id).first()
        scenario = db.query(Scenario).filter(Scenario.id == conversation.scenario_id).first()
        
        if not all([agent, persona, scenario]):
            raise ValueError("Missing agent, persona, or scenario")
        
        # Calculate timestamp
        if chunk_timestamp is None:
            if conversation.started_at:
                # Ensure both datetimes are timezone-aware
                now = datetime.now(timezone.utc)
                started_at = conversation.started_at
                # If started_at is timezone-naive, assume UTC
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                chunk_timestamp = (now - started_at).total_seconds()
            else:
                chunk_timestamp = 0.0
        
        # Convert WebM audio to WAV (OpenAI requires WAV/MP3)
        try:
            wav_audio_bytes = self._convert_webm_to_wav(audio_chunk)
        except Exception as e:
            return {
                "response_audio": None,
                "transcription": None,
                "error": f"Failed to convert audio format: {str(e)}"
            }
        
        # Save audio chunk temporarily for transcription
        temp_file_path = None
        try:
            # Save converted WAV to temp file for transcription
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                temp_file.write(wav_audio_bytes)
                temp_file_path = temp_file.name
            
            # Upload to S3 temporarily for transcription service (it needs S3 key)
            chunk_file_id = uuid.uuid4()
            chunk_s3_key = s3_service.upload_file(
                file_content=wav_audio_bytes,
                file_id=chunk_file_id,
                file_format="wav"
            )
            
            # Transcribe using STT
            transcription_result = transcription_service.transcribe(
                audio_file_key=chunk_s3_key,
                stt_provider=voice_bundle.stt_provider,
                stt_model=voice_bundle.stt_model,
                organization_id=organization_id,
                db=db,
                language=agent.language.value if agent.language else None,
                enable_speaker_diarization=False
            )
            
            voice_agent_text = transcription_result.get("transcript", "").strip()
            
            if not voice_agent_text:
                return {
                    "response_audio": None,
                    "transcription": None,
                    "error": "No speech detected in audio chunk"
                }
            
            # Add voice agent turn to conversation
            conversation_turns = conversation.live_transcription or []
            conversation_turns.append({
                "speaker": "voice_agent",
                "text": voice_agent_text,
                "timestamp": chunk_timestamp
            })
            
            # Build conversation history for LLM
            messages = []
            
            # System prompt
            system_prompt = self._build_system_prompt(agent, persona, scenario, db)
            messages.append({
                "role": "system",
                "content": system_prompt
            })
            
            # Add conversation history (last 10 turns for context)
            recent_turns = conversation_turns[-10:]
            for turn in recent_turns:
                role = "user" if turn["speaker"] == "voice_agent" else "assistant"
                messages.append({
                    "role": role,
                    "content": turn["text"]
                })
            
            # Generate response using LLM
            llm_result = llm_service.generate_response(
                messages=messages,
                llm_provider=voice_bundle.llm_provider,
                llm_model=voice_bundle.llm_model,
                organization_id=organization_id,
                db=db,
                temperature=voice_bundle.llm_temperature or 0.7,
                max_tokens=voice_bundle.llm_max_tokens,
                config=voice_bundle.llm_config
            )
            
            test_agent_text = llm_result.get("text", "").strip()
            
            if not test_agent_text:
                return {
                    "response_audio": None,
                    "transcription": None,
                    "error": "LLM did not generate a response"
                }
            
            # Convert response to speech using TTS
            response_audio_bytes = tts_service.synthesize(
                text=test_agent_text,
                tts_provider=voice_bundle.tts_provider,
                tts_model=voice_bundle.tts_model,
                organization_id=organization_id,
                db=db,
                voice=voice_bundle.tts_voice,
                config=voice_bundle.tts_config
            )
            
            # Upload response audio to S3 (temporarily, for reference)
            response_file_id = uuid.uuid4()
            response_s3_key = s3_service.upload_file(
                file_content=response_audio_bytes,
                file_id=response_file_id,
                file_format="mp3"
            )
            
            # Add test agent turn to conversation
            conversation_turns.append({
                "speaker": "test_agent",
                "text": test_agent_text,
                "timestamp": chunk_timestamp + transcription_result.get("processing_time", 0) + llm_result.get("processing_time", 0)
            })
            
            # Update conversation
            conversation.live_transcription = conversation_turns
            conversation.full_transcript = "\n".join([
                f"{turn['speaker']}: {turn['text']}" for turn in conversation_turns
            ])
            db.commit()
            
            return {
                "response_audio": response_audio_bytes,
                "transcription": {
                    "voice_agent": voice_agent_text,
                    "test_agent": test_agent_text
                },
                "metadata": {
                    "processing_times": {
                        "stt": transcription_result.get("processing_time", 0),
                        "llm": llm_result.get("processing_time", 0)
                    }
                }
            }
            
        finally:
            # Clean up temp file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass

    def start_conversation(
        self,
        conversation_id: UUID,
        organization_id: UUID,
        db: Session
    ) -> TestAgentConversation:
        """Start a conversation (change status to ACTIVE)."""
        conversation = db.query(TestAgentConversation).filter(
            TestAgentConversation.id == conversation_id,
            TestAgentConversation.organization_id == organization_id
        ).first()
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")
        
        conversation.status = TestAgentConversationStatus.ACTIVE
        conversation.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(conversation)
        
        return conversation

    def end_conversation(
        self,
        conversation_id: UUID,
        organization_id: UUID,
        db: Session,
        final_audio_key: Optional[str] = None
    ) -> TestAgentConversation:
        """End a conversation and save final audio."""
        conversation = db.query(TestAgentConversation).filter(
            TestAgentConversation.id == conversation_id,
            TestAgentConversation.organization_id == organization_id
        ).first()
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")
        
        conversation.status = TestAgentConversationStatus.COMPLETED
        conversation.ended_at = datetime.now(timezone.utc)
        
        if conversation.started_at:
            # Ensure both datetimes are timezone-aware
            ended_at = conversation.ended_at
            started_at = conversation.started_at
            # If started_at is timezone-naive, assume UTC
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            conversation.duration_seconds = (
                ended_at - started_at
            ).total_seconds()
        
        if final_audio_key:
            conversation.conversation_audio_key = final_audio_key
        
        db.commit()
        db.refresh(conversation)
        
        return conversation


# Singleton instance
test_agent_service = TestAgentService()

