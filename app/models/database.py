"""SQLAlchemy database models."""

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Boolean, JSON, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.database import Base


class EvaluationType(str, enum.Enum):
    """Evaluation type enumeration."""

    ASR = "asr"
    TTS = "tts"
    QUALITY = "quality"


class EvaluationStatus(str, enum.Enum):
    """Evaluation status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluatorResultStatus(str, enum.Enum):
    """Evaluator result status enumeration."""

    QUEUED = "queued"
    CALL_INITIATING = "call_initiating"  # Creating the web call to Retell/Vapi
    CALL_CONNECTING = "call_connecting"  # WebRTC connecting to Voice AI agent
    CALL_IN_PROGRESS = "call_in_progress"  # Call is active
    CALL_ENDED = "call_ended"  # Call finished
    FETCHING_DETAILS = "fetching_details"  # Fetching call details from provider
    TRANSCRIBING = "transcribing"  # Only used for S3-based transcription (legacy)
    EVALUATING = "evaluating"  # Running LLM evaluation on transcript
    COMPLETED = "completed"
    FAILED = "failed"


class RoleEnum(str, enum.Enum):
    """User role enumeration for RBAC."""
    
    READER = "reader"
    WRITER = "writer"
    ADMIN = "admin"


class InvitationStatus(str, enum.Enum):
    """Invitation status enumeration."""
    
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


class Organization(Base):
    """Organization model for multi-tenancy."""

    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    api_keys = relationship("APIKey", back_populates="organization")
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    """User model for authentication and profile management."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for users created via invitation
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    organization_memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user")
    invitations = relationship("Invitation", back_populates="invited_user", foreign_keys="Invitation.invited_user_id")


class OrganizationMember(Base):
    """Organization membership with role."""

    __tablename__ = "organization_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(Enum(RoleEnum), nullable=False, default=RoleEnum.READER)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Unique constraint: one membership per user per organization
    __table_args__ = (
        UniqueConstraint('organization_id', 'user_id', name='uq_org_user'),
    )

    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="organization_memberships")


class Invitation(Base):
    """Invitation model for inviting users to organizations."""

    __tablename__ = "invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    invited_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)  # Null if user doesn't exist yet
    invited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    email = Column(String(255), nullable=False)  # Email of invited user
    role = Column(Enum(RoleEnum), nullable=False, default=RoleEnum.READER)
    status = Column(Enum(InvitationStatus), nullable=False, default=InvitationStatus.PENDING)
    token = Column(String(255), unique=True, nullable=False, index=True)  # Invitation token
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="invitations")
    invited_user = relationship("User", foreign_keys=[invited_user_id], back_populates="invitations")
    invited_by = relationship("User", foreign_keys=[invited_by_id])


class APIKey(Base):
    """API Key model for authentication."""

    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)  # Optional: link to user
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="api_keys")
    user = relationship("User", back_populates="api_keys")


class AudioFile(Base):
    """Audio file model."""

    __tablename__ = "audio_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_size = Column(Integer, nullable=False)  # Size in bytes
    duration = Column(Float, nullable=True)  # Duration in seconds
    sample_rate = Column(Integer, nullable=True)
    channels = Column(Integer, nullable=True)
    format = Column(String(10), nullable=False)  # wav, mp3, flac, etc.
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    evaluations = relationship("Evaluation", back_populates="audio_file")


class Evaluation(Base):
    """Evaluation job model."""

    __tablename__ = "evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    audio_id = Column(UUID(as_uuid=True), ForeignKey("audio_files.id"), nullable=False)
    reference_text = Column(String, nullable=True)  # For WER calculation
    evaluation_type = Column(Enum(EvaluationType), nullable=False)
    model_name = Column(String(100), nullable=True)
    status = Column(Enum(EvaluationStatus), default=EvaluationStatus.PENDING, nullable=False)
    metrics_requested = Column(JSON, nullable=True)  # List of requested metrics
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(String, nullable=True)

    # Relationships
    audio_file = relationship("AudioFile", back_populates="evaluations")
    result = relationship("EvaluationResult", back_populates="evaluation", uselist=False)


class EvaluationResult(Base):
    """Evaluation result model."""

    __tablename__ = "evaluation_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(UUID(as_uuid=True), ForeignKey("evaluations.id"), nullable=False, unique=True)
    transcript = Column(String, nullable=True)
    metrics = Column(JSON, nullable=False)  # {"wer": 0.05, "latency_ms": 1250, ...}
    raw_output = Column(JSON, nullable=True)  # Full model output
    processing_time = Column(Float, nullable=True)  # Processing time in seconds
    model_used = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    evaluation = relationship("Evaluation", back_populates="result")


# ============================================
# VAIOPS MODELS - Voice AI Ops
# ============================================

class LanguageEnum(str, enum.Enum):
    """Supported languages"""
    ENGLISH = "en"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"
    CHINESE = "zh"
    JAPANESE = "ja"
    HINDI = "hi"
    ARABIC = "ar"


class CallTypeEnum(str, enum.Enum):
    """Call direction"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallMediumEnum(str, enum.Enum):
    """Call medium"""
    PHONE_CALL = "phone_call"
    WEB_CALL = "web_call"


class GenderEnum(str, enum.Enum):
    """Gender options for personas"""
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


class AccentEnum(str, enum.Enum):
    """Accent options"""
    AMERICAN = "american"
    BRITISH = "british"
    AUSTRALIAN = "australian"
    INDIAN = "indian"
    CHINESE = "chinese"
    SPANISH = "spanish"
    FRENCH = "french"
    GERMAN = "german"
    NEUTRAL = "neutral"


class BackgroundNoiseEnum(str, enum.Enum):
    """Background noise options"""
    NONE = "none"
    OFFICE = "office"
    STREET = "street"
    CAFE = "cafe"
    HOME = "home"
    CALL_CENTER = "call_center"


class Agent(Base):
    """Test Agent - The voice AI agent being evaluated"""
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(String(6), unique=True, nullable=True, index=True)  # 6-digit ID
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)  # Optional, required only for phone_call
    language = Column(Enum(LanguageEnum), nullable=False, default=LanguageEnum.ENGLISH)
    description = Column(String)
    call_type = Column(Enum(CallTypeEnum), nullable=False, default=CallTypeEnum.OUTBOUND)
    call_medium = Column(Enum(CallMediumEnum), nullable=False, default=CallMediumEnum.PHONE_CALL)
    
    # Voice configuration - either voice_bundle_id OR ai_provider_id OR voice_ai_integration_id (mutually exclusive)
    voice_bundle_id = Column(UUID(as_uuid=True), ForeignKey("voicebundles.id"), nullable=True, index=True)
    ai_provider_id = Column(UUID(as_uuid=True), ForeignKey("aiproviders.id"), nullable=True, index=True)
    
    # Voice AI agent integration (Retell, Vapi, etc.)
    voice_ai_integration_id = Column(UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=True, index=True)
    voice_ai_agent_id = Column(String, nullable=True)  # Agent ID from the external provider (Retell/Vapi)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String)


class Persona(Base):
    """Persona - The simulated caller/user for testing"""
    __tablename__ = "personas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    language = Column(Enum(LanguageEnum), nullable=False, default=LanguageEnum.ENGLISH)
    accent = Column(Enum(AccentEnum), nullable=False, default=AccentEnum.AMERICAN)
    gender = Column(Enum(GenderEnum), nullable=False, default=GenderEnum.NEUTRAL)
    background_noise = Column(Enum(BackgroundNoiseEnum), nullable=False, default=BackgroundNoiseEnum.NONE)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String)


class Scenario(Base):
    """Scenario - The conversation scenario/test case"""
    __tablename__ = "scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String)
    required_info = Column(JSON)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String)


class IntegrationPlatform(str, enum.Enum):
    """Integration platform enumeration."""
    
    RETELL = "retell"
    VAPI = "vapi"
    CARTESIA = "cartesia"
    ELEVENLABS = "elevenlabs"
    DEEPGRAM = "deepgram"


class Integration(Base):
    """Integration model for connecting with external voice AI platforms."""
    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    platform = Column(Enum(IntegrationPlatform), nullable=False)
    name = Column(String, nullable=True)  # Optional friendly name
    api_key = Column(String, nullable=False)  # Encrypted API key for the platform
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_tested_at = Column(DateTime(timezone=True), nullable=True)  # When API key was last validated


class ModelProvider(str, enum.Enum):
    """Model provider enumeration for extensibility."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    AZURE = "azure"
    AWS = "aws"
    CUSTOM = "custom"
    CARTESIA = "cartesia"
    DEEPGRAM = "deepgram"


class ManualTranscription(Base):
    """Manual transcription model for storing transcriptions from S3 audio files."""

    __tablename__ = "manual_transcriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=True)  # User-friendly name for the transcription
    audio_file_key = Column(String(512), nullable=False)  # S3 key or file path
    transcript = Column(String, nullable=False)  # Full transcript text
    speaker_segments = Column(JSON, nullable=True)  # List of segments with speaker labels: [{"speaker": "Speaker 1", "text": "...", "start": 0.0, "end": 5.2}]
    stt_model = Column(String(100), nullable=True)  # STT model used (e.g., "whisper-1", "google-speech-v2")
    stt_provider = Column(Enum(ModelProvider), nullable=True)  # Provider used
    language = Column(String(10), nullable=True)  # Detected or specified language
    processing_time = Column(Float, nullable=True)  # Processing time in seconds
    raw_output = Column(JSON, nullable=True)  # Full model output for reference
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConversationEvaluation(Base):
    """Conversation evaluation model for evaluating manual transcriptions against agent objectives."""
    
    __tablename__ = "conversation_evaluations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    transcription_id = Column(UUID(as_uuid=True), ForeignKey("manual_transcriptions.id"), nullable=False, index=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)
    
    # Evaluation results
    objective_achieved = Column(Boolean, nullable=False)  # Binary: was the conversation objective achieved?
    objective_achieved_reason = Column(String, nullable=True)  # Explanation for the binary result
    additional_metrics = Column(JSON, nullable=True)  # Additional evaluation metrics (e.g., professionalism, clarity, etc.)
    overall_score = Column(Float, nullable=True)  # Overall score (0.0 to 1.0)
    
    # LLM metadata
    llm_provider = Column(Enum(ModelProvider), nullable=True)
    llm_model = Column(String(100), nullable=True)
    llm_response = Column(JSON, nullable=True)  # Full LLM response for reference
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AIProvider(Base):
    """AI Provider - Stores API keys for different AI platforms."""
    __tablename__ = "aiproviders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    provider = Column(Enum(ModelProvider), nullable=False)
    api_key = Column(String, nullable=False)  # Encrypted API key
    name = Column(String, nullable=True)  # Optional friendly name
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_tested_at = Column(DateTime(timezone=True), nullable=True)  # When API key was last validated
    
    # Unique constraint: one active provider per organization
    __table_args__ = (
        UniqueConstraint('organization_id', 'provider', name='unique_org_provider'),
    )


class VoiceBundleType(str, enum.Enum):
    """VoiceBundle type enumeration."""
    STT_LLM_TTS = "stt_llm_tts"  # Traditional STT + LLM + TTS pipeline
    S2S = "s2s"  # Speech-to-Speech model


class VoiceBundle(Base):
    """VoiceBundle - Composable unit combining STT, LLM, and TTS for voice AI testing, or S2S models."""
    __tablename__ = "voicebundles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    
    # Bundle type: either STT+LLM+TTS or S2S
    # Using String instead of Enum to avoid SQLAlchemy enum conversion issues
    # The enum conversion is handled in the Pydantic schemas
    bundle_type = Column(String(50), nullable=False, default=VoiceBundleType.STT_LLM_TTS.value)
    
    # STT Configuration (references AIProvider via provider name) - required for STT_LLM_TTS, optional for S2S
    stt_provider = Column(Enum(ModelProvider), nullable=True)
    stt_model = Column(String, nullable=True)  # e.g., "whisper-1", "google-speech-v2"
    
    # LLM Configuration (references AIProvider via provider name) - required for STT_LLM_TTS, optional for S2S
    llm_provider = Column(Enum(ModelProvider), nullable=True)
    llm_model = Column(String, nullable=True)  # e.g., "gpt-4", "claude-3-opus"
    llm_temperature = Column(Float, nullable=True, default=0.7)
    llm_max_tokens = Column(Integer, nullable=True)
    llm_config = Column(JSON, nullable=True)  # Additional LLM configuration (extensible)
    
    # TTS Configuration (references AIProvider via provider name) - required for STT_LLM_TTS, optional for S2S
    tts_provider = Column(Enum(ModelProvider), nullable=True)
    tts_model = Column(String, nullable=True)  # e.g., "tts-1", "neural-voice"
    tts_voice = Column(String, nullable=True)  # Voice selection if applicable
    tts_config = Column(JSON, nullable=True)  # Additional TTS configuration (extensible)
    
    # S2S Configuration - required for S2S type, optional for STT_LLM_TTS
    s2s_provider = Column(Enum(ModelProvider), nullable=True)
    s2s_model = Column(String, nullable=True)  # e.g., "gpt-4o-transcribe", speech-to-speech model
    s2s_config = Column(JSON, nullable=True)  # Additional S2S configuration (extensible)
    
    # Additional configuration for extensibility
    extra_metadata = Column(JSON, nullable=True)  # For future extensions (renamed from 'metadata' to avoid SQLAlchemy conflict)
    
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


class TestAgentConversationStatus(str, enum.Enum):
    """Test agent conversation status enumeration."""
    
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TestAgentConversation(Base):
    """Test Agent Conversation - Records conversations between test AI agent and voice AI agent."""
    __tablename__ = "test_agent_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    
    # Configuration
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    persona_id = Column(UUID(as_uuid=True), ForeignKey("personas.id"), nullable=False)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False)
    voice_bundle_id = Column(UUID(as_uuid=True), ForeignKey("voicebundles.id"), nullable=False)
    
    # Conversation data
    status = Column(Enum(TestAgentConversationStatus), nullable=False, default=TestAgentConversationStatus.INITIALIZING)
    live_transcription = Column(JSON, nullable=True)  # Array of conversation turns with timestamps
    conversation_audio_key = Column(String, nullable=True)  # S3 key for recorded conversation audio
    full_transcript = Column(String, nullable=True)  # Full conversation transcript
    
    # Metadata
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Additional metadata
    conversation_metadata = Column(JSON, nullable=True)  # Additional conversation metadata
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


class Evaluator(Base):
    """Evaluator - Configuration for testing agents with specific persona and scenario combinations."""
    __tablename__ = "evaluators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluator_id = Column(String(6), unique=True, nullable=False, index=True)  # 6-digit ID
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    
    # Configuration
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    persona_id = Column(UUID(as_uuid=True), ForeignKey("personas.id"), nullable=False)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False)
    
    # Tags for categorization
    tags = Column(JSON, nullable=True)  # Array of tag strings
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


class MetricType(str, enum.Enum):
    """Metric type enumeration."""
    NUMBER = "number"
    BOOLEAN = "boolean"
    RATING = "rating"


class MetricTrigger(str, enum.Enum):
    """Metric trigger enumeration."""
    ALWAYS = "always"
    # Can add more triggers in the future like "on_error", "on_completion", etc.


class Metric(Base):
    """Metric - Configuration for evaluation metrics."""
    __tablename__ = "metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    
    # Basic information
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    
    # Configuration
    metric_type = Column(Enum(MetricType), nullable=False, default=MetricType.RATING)
    trigger = Column(Enum(MetricTrigger), nullable=False, default=MetricTrigger.ALWAYS)
    enabled = Column(Boolean, nullable=False, default=True)
    
    # Metadata
    is_default = Column(Boolean, nullable=False, default=False)  # Pre-defined metrics
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


class EvaluatorResult(Base):
    """EvaluatorResult - Results from running an evaluator with transcription and metric evaluations."""
    __tablename__ = "evaluator_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id = Column(String(6), unique=True, nullable=False, index=True)  # 6-digit ID
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    
    # References
    evaluator_id = Column(UUID(as_uuid=True), ForeignKey("evaluators.id"), nullable=True, index=True)  # Optional - can be None for test calls without persona/scenario
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    persona_id = Column(UUID(as_uuid=True), ForeignKey("personas.id"), nullable=True)  # Optional - can be None for test calls
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=True)  # Optional - can be None for test calls
    
    # Result data
    name = Column(String, nullable=True)  # Scenario name or test call name (optional)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    duration_seconds = Column(Float, nullable=True)  # Call duration
    status = Column(String(20), nullable=False, default=EvaluatorResultStatus.QUEUED.value)
    
    # Audio and transcription
    audio_s3_key = Column(String, nullable=True)  # S3 key for audio file
    transcription = Column(String, nullable=True)  # Full transcription
    speaker_segments = Column(JSON, nullable=True)  # List of segments with speaker labels: [{"speaker": "Speaker 1", "text": "...", "start": 0.0, "end": 5.2}]
    
    # Metric scores - JSON object with metric_id as key and score as value
    # Format: {"metric_id_1": {"value": 85, "type": "rating"}, "metric_id_2": {"value": true, "type": "boolean"}}
    metric_scores = Column(JSON, nullable=True)
    
    # Celery task tracking
    celery_task_id = Column(String, nullable=True, index=True)  # Celery task ID for tracking
    
    # Error information
    error_message = Column(String, nullable=True)
    
    # Call event tracking (similar to CallRecording)
    call_event = Column(String, nullable=True, index=True)  # Latest call event (e.g., call_started, call_ended)
    provider_call_id = Column(String, nullable=True, index=True)  # Provider's call_id (e.g., Retell call_id)
    provider_platform = Column(String, nullable=True)  # e.g., "retell", "vapi"
    call_data = Column(JSON, nullable=True)  # Full call details from provider (like CallRecording)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


class CallRecordingStatus(str, enum.Enum):
    """Call recording status enumeration."""
    
    PENDING = "PENDING"
    UPDATED = "UPDATED"


class CallRecordingSource(str, enum.Enum):
    """Source of the call recording data."""
    
    PLAYGROUND = "playground"
    WEBHOOK = "webhook"


class CallRecording(Base):
    """Call Recording model for tracking voice provider calls."""
    __tablename__ = "call_recordings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    call_short_id = Column(String(6), unique=True, nullable=False, index=True)  # 6-digit ID
    status = Column(Enum(CallRecordingStatus), nullable=False, default=CallRecordingStatus.PENDING, index=True)
    call_event = Column(String, nullable=True, index=True)  # Latest webhook event (e.g., call_started, call_ended)
    source = Column(Enum(CallRecordingSource), nullable=False, default=CallRecordingSource.PLAYGROUND, index=True)
    call_data = Column(JSON, nullable=True)  # JSON blob for provider response
    provider_call_id = Column(String, nullable=True, index=True)  # Provider's call_id (e.g., Retell call_id)
    provider_platform = Column(String, nullable=True)  # e.g., "retell", "vapi"
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)  # Reference to our agent
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())