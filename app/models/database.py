"""SQLAlchemy database models."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    DDL,
    Enum,
    event,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum
from app.models.enums import (
    EvaluationType, EvaluationStatus, EvaluatorResultStatus, RoleEnum, InvitationStatus,
    LanguageEnum, CallTypeEnum, CallMediumEnum, GenderEnum, AccentEnum, BackgroundNoiseEnum,
    IntegrationPlatform, ModelProvider, VoiceBundleType, TestAgentConversationStatus,
    MetricType, MetricCategory, MetricTrigger, CallRecordingStatus, AlertMetricType, AlertAggregation,
    AlertOperator, AlertNotifyFrequency, AlertStatus, AlertHistoryStatus, CronJobStatus,
    PromptOptimizationStatus, CallImportStatus, CallImportRowStatus,
)

def get_enum_values(enum_class):
    """Helper to get values from enum class for SQLAlchemy."""
    return [e.value for e in enum_class]

from app.database import Base


# Enums moved to enums.py


class Organization(Base):
    """Organization model for multi-tenancy."""

    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    voice_playground_threshold_overrides = Column(JSON, nullable=True)
    # AlignEval-style judge alignment thresholds.
    # Shape: {"min_labels_to_evaluate": int, "min_labels_to_optimize": int}
    # Falls back to system defaults (20 / 50) when null.
    judge_alignment_settings = Column(JSON, nullable=True)
    # Per-org LLM gateway overrides (enabled, gateway_type, base_url, keys).
    llm_gateway_settings = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    api_keys = relationship("APIKey", back_populates="organization")
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")
    workspaces = relationship(
        "Workspace",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    workspace_roles = relationship(
        "WorkspaceRole",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class Workspace(Base):
    """Workspace - in-org isolation boundary for call imports and metrics.

    Every organization has at least one workspace (``is_default = True``,
    seeded by migration 033). Users pick an "active workspace" in the UI;
    list endpoints filter by it so users only see calls/metrics from the
    project they're currently working in. Access is governed by
    ``workspace_members`` and org-scoped ``workspace_roles`` (capability
    bundles); org admins implicitly access all workspaces.
    """

    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_workspaces_org_slug"),
    )

    # ``server_default`` is required so that raw-SQL INSERTs (e.g. the
    # per-org Default seed in migration 033) can omit ``id`` and let the
    # database fill it in. Without it, ``create_all`` produces a column
    # with NOT NULL but no DEFAULT, and the migration crashes with
    # ``null value in column "id"``.
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    # At most one default per org. Enforced on Postgres by the partial
    # unique index attached via the after_create event below; on
    # SQLite (test runs) we rely on the route-level _check_slug_unique
    # check + the Default-workspace conftest fixture instead, because
    # SQLite doesn't support partial indexes the same way.
    is_default = Column(Boolean, nullable=False, default=False, server_default="false")
    # Reusable PDF/report branding metadata scoped to this workspace. Images
    # live in S3. Shape: {"heading": str|null, "images": [{id, s3_key,
    # content_type, filename, size_bytes, updated_at}, ...]}.
    report_branding = Column(JSON, nullable=True)
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization = relationship("Organization", back_populates="workspaces")
    members = relationship(
        "WorkspaceMember",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class WorkspaceRole(Base):
    """Org-scoped workspace role (system or custom) as a capability bundle."""

    __tablename__ = "workspace_roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_workspace_roles_org_name"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    capabilities = Column(JSON, nullable=False, default=list)
    is_system = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization = relationship("Organization", back_populates="workspace_roles")
    members = relationship("WorkspaceMember", back_populates="role")


class WorkspaceMember(Base):
    """User membership in a workspace with an assigned workspace role."""

    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_ws_user"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspace_roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    added_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    role = relationship("WorkspaceRole", back_populates="members")
    added_by = relationship("User", foreign_keys=[added_by_user_id])


# Partial unique index: "at most one default workspace per org". This
# is attached as an after_create event (rather than declared in
# ``__table_args__``) because SQLAlchemy's ``Index(...,
# postgresql_where=...)`` silently degrades to a *full* unique index on
# SQLite - which then forbids any second workspace per org and breaks
# the test suite. ``execute_if(dialect="postgresql")`` makes this DDL
# a no-op on SQLite while still emitting it on Postgres (prod, CI).
event.listen(
    Workspace.__table__,
    "after_create",
    DDL(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_org_default "
        "ON workspaces (organization_id) WHERE is_default"
    ).execute_if(dialect="postgresql"),
)


class User(Base):
    """User model for authentication and profile management."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for users created via invitation
    external_id = Column(String(255), unique=True, nullable=True, index=True)
    auth_provider = Column(String(50), nullable=True)
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    organization_memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user")
    invitations = relationship("Invitation", back_populates="invited_user", foreign_keys="Invitation.invited_user_id")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    """Opaque refresh token for extending local-password sessions."""

    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


class OrganizationMember(Base):
    """Organization membership with role."""

    __tablename__ = "organization_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default=RoleEnum.READER.value)
    
    # User preferences for this organization
    default_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)

    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Unique constraint: one membership per user per organization
    __table_args__ = (
        UniqueConstraint('organization_id', 'user_id', name='uq_org_user'),
    )

    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="organization_memberships")
    default_agent = relationship("Agent", foreign_keys=[default_agent_id])


class Invitation(Base):
    """Invitation model for inviting users to organizations."""

    __tablename__ = "invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    invited_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)  # Null if user doesn't exist yet
    invited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    email = Column(String(255), nullable=False)  # Email of invited user
    role = Column(String, nullable=False, default=RoleEnum.READER.value)
    status = Column(String, nullable=False, default=InvitationStatus.PENDING.value)



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
    # Workspace isolation: every legacy audio evaluation belongs to a
    # workspace within its org. Stamped from the X-Workspace-Id header
    # (falling back to the org's Default workspace).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    audio_id = Column(UUID(as_uuid=True), ForeignKey("audio_files.id"), nullable=False)
    reference_text = Column(String, nullable=True)  # For WER calculation
    evaluation_type = Column(String, nullable=False)
    model_name = Column(String(100), nullable=True)
    status = Column(String, default=EvaluationStatus.PENDING.value, nullable=False)



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
    # Workspace isolation: mirrors the parent Evaluation's workspace.
    # Denormalized for fast filter-by-workspace listings without a join.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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

# Enums moved to enums.py


class Agent(Base):
    """Test Agent - The voice AI agent being evaluated"""
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(String(6), unique=True, nullable=True, index=True)  # 6-digit ID
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every agent belongs to a workspace within its
    # org. Stamped from the X-Workspace-Id header (falling back to the
    # org's Default workspace).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)  # Optional, required only for phone_call
    language = Column(String, nullable=False, default=LanguageEnum.ENGLISH.value)
    description = Column(String)
    provider_prompt = Column(Text, nullable=True)
    provider_prompt_synced_at = Column(DateTime(timezone=True), nullable=True)
    call_type = Column(String, nullable=False, default=CallTypeEnum.OUTBOUND.value)
    call_medium = Column(String, nullable=False, default=CallMediumEnum.PHONE_CALL.value)
    telephony_phone_number_id = Column(
        UUID(as_uuid=True),
        ForeignKey("telephony_phone_numbers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )



    
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
    """Persona - TTS provider-tied voice identity for testing"""
    __tablename__ = "personas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every persona belongs to a workspace within
    # its org. Stamped from the X-Workspace-Id header (falling back to
    # the org's Default workspace).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    gender = Column(String, nullable=False, default=GenderEnum.NEUTRAL.value)
    tts_provider = Column(String(100), nullable=True)
    tts_voice_id = Column(String(255), nullable=True)
    tts_voice_name = Column(String(255), nullable=True)
    is_custom = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String)


class Scenario(Base):
    """Scenario - The conversation scenario/test case"""
    __tablename__ = "scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every scenario belongs to a workspace within
    # its org. Stamped from the X-Workspace-Id header (falling back to
    # the org's Default workspace).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String)
    required_info = Column(JSON)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String)


# Enums moved to enums.py


class Integration(Base):
    """Integration model for connecting with external voice AI platforms."""
    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    platform = Column(String, nullable=False)



    name = Column(String, nullable=True)  # Optional friendly name
    api_key = Column(String, nullable=False)  # Encrypted Private API key for the platform
    public_key = Column(String, nullable=True)  # Optional Public API key (e.g. for Vapi)
    is_active = Column(Boolean, default=True, nullable=False)
    # Multiple credentials per (org, platform) are allowed. is_default marks
    # the row used when a caller does not explicitly select a credential.
    # A partial unique index in migration 028 enforces at most one default
    # per (org, platform) at the DB level.
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_tested_at = Column(DateTime(timezone=True), nullable=True)  # When API key was last validated


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
    stt_provider = Column(String, nullable=True)  # Provider used



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
    llm_provider = Column(Enum(ModelProvider, native_enum=False), nullable=True)

    llm_model = Column(String(100), nullable=True)
    llm_response = Column(JSON, nullable=True)  # Full LLM response for reference
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AIProvider(Base):
    """AI Provider - Stores API keys for different AI platforms."""
    __tablename__ = "aiproviders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)



    api_key = Column(String, nullable=False)  # Encrypted API key
    name = Column(String, nullable=True)  # Optional friendly name
    is_active = Column(Boolean, default=True, nullable=False)
    # Multiple AIProvider rows per (org, provider) are allowed. is_default
    # marks the row resolved when no explicit credential id is selected.
    # A partial unique index in migration 028 enforces at most one default.
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_tested_at = Column(DateTime(timezone=True), nullable=True)  # When API key was last validated


# Enums moved to enums.py


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
    stt_provider = Column(String, nullable=True)
    # Optional explicit credential row (aiproviders.id or integrations.id).
    # When NULL the credential resolver picks the default row for the
    # provider. No FK is set because the target table varies by provider.
    stt_credential_id = Column(UUID(as_uuid=True), nullable=True)

    stt_model = Column(String, nullable=True)  # e.g., "whisper-1", "google-speech-v2"
    
    # LLM Configuration (references AIProvider via provider name) - required for STT_LLM_TTS, optional for S2S
    llm_provider = Column(String, nullable=True)
    llm_credential_id = Column(UUID(as_uuid=True), nullable=True)

    llm_model = Column(String, nullable=True)  # e.g., "gpt-4", "claude-3-opus"
    llm_temperature = Column(Float, nullable=True, default=0.7)
    llm_max_tokens = Column(Integer, nullable=True)
    llm_config = Column(JSON, nullable=True)  # Additional LLM configuration (extensible)
    
    # TTS Configuration (references AIProvider via provider name) - required for STT_LLM_TTS, optional for S2S
    tts_provider = Column(String, nullable=True)
    tts_credential_id = Column(UUID(as_uuid=True), nullable=True)

    tts_model = Column(String, nullable=True)  # e.g., "tts-1", "neural-voice"
    tts_voice = Column(String, nullable=True)  # Voice selection if applicable
    tts_config = Column(JSON, nullable=True)  # Additional TTS configuration (extensible)
    
    # S2S Configuration - required for S2S type, optional for STT_LLM_TTS
    s2s_provider = Column(String, nullable=True)
    s2s_credential_id = Column(UUID(as_uuid=True), nullable=True)



    s2s_model = Column(String, nullable=True)  # e.g., "gpt-4o-transcribe", speech-to-speech model
    s2s_config = Column(JSON, nullable=True)  # Additional S2S configuration (extensible)
    
    # Additional configuration for extensibility
    extra_metadata = Column(JSON, nullable=True)  # For future extensions (renamed from 'metadata' to avoid SQLAlchemy conflict)
    
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


# Enums moved to enums.py


class TestAgentConversation(Base):
    """Test Agent Conversation - Records conversations between test AI agent and voice AI agent."""
    __tablename__ = "test_agent_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every playground conversation belongs to a
    # workspace within its org. Stamped from the X-Workspace-Id header
    # (falling back to the org's Default workspace).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    
    # Configuration
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    persona_id = Column(UUID(as_uuid=True), ForeignKey("personas.id"), nullable=False)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False)
    voice_bundle_id = Column(UUID(as_uuid=True), ForeignKey("voicebundles.id"), nullable=True)
    
    # Conversation data
    status = Column(String, nullable=False, default=TestAgentConversationStatus.INITIALIZING.value)



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
    """Evaluator - Configuration for testing agents with specific persona and scenario combinations, or custom prompt evaluators."""
    __tablename__ = "evaluators"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluator_id = Column(String(6), unique=True, nullable=False, index=True)  # 6-digit ID
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every evaluator belongs to a workspace within
    # its org. Stamped from the X-Workspace-Id header (falling back to
    # the org's Default workspace).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    
    # Display name (required for custom evaluators, optional for standard)
    name = Column(String, nullable=True)
    
    # Standard evaluator configuration (nullable for custom evaluators)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    persona_id = Column(UUID(as_uuid=True), ForeignKey("personas.id"), nullable=True)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=True)
    
    # Custom evaluator prompt (used instead of agent/persona/scenario)
    custom_prompt = Column(Text, nullable=True)

    # Custom evaluator metric selection. When set, the worker filters the
    # enabled-org metrics down to only these IDs (list of metric UUID strings).
    # Standard evaluators leave this NULL and use all enabled agent metrics.
    metric_ids = Column(JSON, nullable=True)

    # LLM configuration for evaluation (overrides hardcoded defaults)
    llm_provider = Column(String, nullable=True)  # e.g. "openai", "anthropic", "google"
    llm_model = Column(String, nullable=True)  # e.g. "gpt-4.1", "claude-sonnet-4-20250514"
    llm_config = Column(JSON, nullable=True)
    
    # Tags for categorization
    tags = Column(JSON, nullable=True)  # Array of tag strings
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


# Enums moved to enums.py


class Metric(Base):
    """Metric - Configuration for evaluation metrics.

    Supports a 2-level hierarchy via ``parent_metric_id``: a "category"
    parent metric (e.g. "Call Outcome") owns N child sub-metric labels
    (e.g. "happy_completion", "angry_hangup"). ``selection_mode`` is set
    only on parents and controls how the LLM scores children together
    (``single_choice`` = pick exactly one; ``multi_label`` = independent
    yes/no with logical consistency). Children are always boolean.
    """
    __tablename__ = "metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: two-shape column.
    #
    #   * ``workspace_id = <uuid>`` — workspace-scoped metric. Only
    #     visible inside that workspace (the default behavior; existing
    #     rows all look like this).
    #   * ``workspace_id IS NULL`` — org-shared metric. Surfaces in
    #     every workspace's listing under this org so users don't have
    #     to recreate the same metric per workspace.
    #
    # Children always inherit their parent's ``workspace_id`` (including
    # NULL) so a category metric's whole subtree shares one scope; the
    # add-child / promote-discovered endpoints enforce this.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Basic information
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # Free-form illustrative example used to sharpen the LLM judge's
    # rubric. Today this is consumed by child sub-labels of a
    # categorization parent metric so each label can carry "what does
    # this look like in a transcript?" text alongside the rubric in
    # ``description``. The column lives on every Metric row for
    # forward-compat: a standalone metric could later surface its own
    # example without another migration.
    example = Column(Text, nullable=True)

    # Configuration
    metric_type = Column(String, nullable=False, default=MetricType.RATING.value)
    metric_category = Column(
        String(30),
        nullable=False,
        default=MetricCategory.QUALITY.value,
        server_default=MetricCategory.QUALITY.value,
    )
    trigger = Column(String, nullable=False, default=MetricTrigger.ALWAYS.value)
    metric_origin = Column(String(30), nullable=False, default="default")
    supported_surfaces = Column(JSON, nullable=False, default=list)  # ["agent", "voice_playground", "blind_test"]
    enabled_surfaces = Column(JSON, nullable=False, default=list)  # subset of supported_surfaces
    custom_data_type = Column(String(30), nullable=True)  # "boolean" | "enum" | "number_range"
    custom_config = Column(JSON, nullable=True)  # enum options / number range config
    tags = Column(JSON, nullable=True)  # ["tone", "latency", ...]

    # Hierarchy: NULL = standalone or parent. When set, this row is a
    # child sub-metric of the referenced parent. ON DELETE CASCADE so
    # deleting a category removes its children atomically.
    parent_metric_id = Column(
        UUID(as_uuid=True),
        ForeignKey("metrics.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Set only on parent rows (``parent_metric_id IS NULL``). Either
    # ``single_choice`` or ``multi_label``. NULL = legacy / non-hierarchical
    # metric (no children).
    selection_mode = Column(String(20), nullable=True)

    # When true on a parent metric (any selection_mode), the LLM is
    # invited during call-import evaluation to emit additional
    # candidate sub-labels beyond the user-defined children. The
    # candidates surface in a "Discovered labels" panel where the user
    # manually promotes them into real child Metric rows. For
    # ``single_choice`` parents the discovered entries are
    # supplemental — the chosen child is still picked from the
    # predefined children so the exactly-one-true invariant holds.
    # The validator rejects this flag on standalone / child metrics.
    allow_discovery = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # When True, this metric is a "transcript-compare judge": the
    # call-import evaluator feeds BOTH the production transcript
    # (``call_import_rows.transcript``, CSV-supplied) and the diarised
    # transcript (``call_import_rows.diarised_transcript``, worker-
    # produced by the STT/diarisation pipeline) to the LLM as a
    # labeled pair instead of feeding one transcript. The parent
    # evaluation's ``CallImportEvaluation.transcript_source`` is
    # ignored for these metrics — they always read both columns.
    # Rows where either transcript is missing are skipped per-metric
    # with ``skipped="comparison_missing_transcript"`` so the rest of
    # the row's metrics still produce scores. The Pydantic validator
    # rejects ``compare_transcripts`` combined with ``parent_metric_id``
    # or ``selection_mode`` (i.e. it can't simultaneously be part of
    # a parent/child hierarchy). The call-import worker also
    # auto-promotes a metric to comparison mode when its description
    # references the production / diarised transcripts in well-known
    # phrases (see ``_metric_text_references_production`` in
    # ``app.workers.tasks.evaluate_call_import_row``).
    compare_transcripts = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    parent = relationship(
        "Metric",
        remote_side=[id],
        backref="children",
    )

    # When true, the LLM-judge is asked to also return a short free-form
    # rationale alongside the value (stored under ``metric_scores[id].rationale``).
    # Adds a second "<Name> - LLM Rationale" column in the call-import CSV export.
    capture_rationale = Column(Boolean, nullable=False, default=False)

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
    # Workspace isolation: every evaluator result belongs to a workspace
    # within its org. Stamped from the active workspace at creation time
    # (either the X-Workspace-Id header or the org's Default workspace).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    
    # References
    evaluator_id = Column(UUID(as_uuid=True), ForeignKey("evaluators.id"), nullable=True, index=True)  # Optional - can be None for test calls without persona/scenario
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)  # Nullable for custom evaluators
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


# Enums moved to enums.py


class CallRecordingSource(str, enum.Enum):
    """Source of the call recording data."""
    
    PLAYGROUND = "playground"
    WEBHOOK = "webhook"


class CallRecording(Base):
    """Call Recording model for tracking voice provider calls."""
    __tablename__ = "call_recordings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every recording belongs to a workspace within
    # its org. For playground-origin rows this is stamped from the active
    # workspace at creation time; for webhook-origin rows the worker
    # looks up the recording's agent and inherits its workspace_id.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    call_short_id = Column(String(6), unique=True, nullable=False, index=True)  # 6-digit ID
    status = Column(Enum(CallRecordingStatus), nullable=False, default=CallRecordingStatus.PENDING, index=True)
    call_event = Column(String, nullable=True, index=True)  # Latest webhook event (e.g., call_started, call_ended)
    source = Column(Enum(CallRecordingSource), nullable=False, default=CallRecordingSource.PLAYGROUND, index=True)
    call_data = Column(JSON, nullable=True)  # JSON blob for provider response
    provider_call_id = Column(String, nullable=True, index=True)  # Provider's call_id (e.g., Retell call_id)
    provider_platform = Column(String, nullable=True)  # e.g., "retell", "vapi"
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)  # Reference to our agent
    
    # Link to EvaluatorResult for metric evaluations
    evaluator_result_id = Column(UUID(as_uuid=True), ForeignKey("evaluator_results.id"), nullable=True, index=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Alert(Base):
    """Alert model for configuring monitoring alerts."""
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    
    # Basic information
    name = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    
    # Metric condition configuration
    metric_type = Column(String, nullable=False, default=AlertMetricType.NUMBER_OF_CALLS.value)
    aggregation = Column(String, nullable=False, default=AlertAggregation.SUM.value)
    operator = Column(String, nullable=False, default=AlertOperator.GREATER_THAN.value)
    threshold_value = Column(Float, nullable=False)
    time_window_minutes = Column(Integer, nullable=False, default=60)  # Time window for aggregation
    
    # Agent selection (JSON array of agent UUIDs, null means all agents)
    agent_ids = Column(JSON, nullable=True)
    
    # Notification configuration
    notify_frequency = Column(String, nullable=False, default=AlertNotifyFrequency.IMMEDIATE.value)
    notify_emails = Column(JSON, nullable=True)  # Array of email addresses
    notify_webhooks = Column(JSON, nullable=True)  # Array of webhook URLs (Slack, etc.)
    
    # Status
    status = Column(String, nullable=False, default=AlertStatus.ACTIVE.value)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)
    
    # Relationships
    alert_history = relationship("AlertHistory", back_populates="alert", cascade="all, delete-orphan")


class AlertHistory(Base):
    """Alert history model for tracking triggered alerts."""
    __tablename__ = "alert_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    alert_id = Column(UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=False, index=True)
    
    # Trigger information
    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    triggered_value = Column(Float, nullable=False)  # The actual value that triggered the alert
    threshold_value = Column(Float, nullable=False)  # The threshold at time of trigger
    
    # Status tracking
    status = Column(String, nullable=False, default=AlertHistoryStatus.TRIGGERED.value)
    
    # Notification tracking
    notified_at = Column(DateTime(timezone=True), nullable=True)
    notification_details = Column(JSON, nullable=True)  # Details of sent notifications
    
    # Resolution
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String, nullable=True)
    resolution_notes = Column(String, nullable=True)
    
    # Additional context
    context_data = Column(JSON, nullable=True)  # Additional data about the trigger
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    alert = relationship("Alert", back_populates="alert_history")


class CronJob(Base):
    """Cron job model for scheduling automated evaluator runs."""
    __tablename__ = "cron_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    
    # Basic information
    name = Column(String(255), nullable=False)
    cron_expression = Column(String(100), nullable=False)  # e.g., "0 9 * * 1-5"
    timezone = Column(String(100), nullable=False, default="UTC")
    
    # Run configuration
    max_runs = Column(Integer, nullable=False, default=10)
    current_runs = Column(Integer, nullable=False, default=0)
    
    # Evaluators to trigger (JSON array of evaluator UUIDs)
    evaluator_ids = Column(JSON, nullable=False)
    
    # Status
    status = Column(String, nullable=False, default=CronJobStatus.ACTIVE.value)
    
    # Run tracking
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)


class TTSComparisonStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"


class TTSSampleStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class TTSReportJobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TTSComparison(Base):
    """TTS Comparison session for A/B testing voice providers."""
    __tablename__ = "tts_comparisons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every voice playground comparison belongs to
    # a workspace within its org. Children (samples, report jobs, blind
    # test shares) inherit this workspace_id.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    simulation_id = Column(String(6), unique=True, index=True, nullable=True)

    name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default=TTSComparisonStatus.PENDING.value)

    # 'benchmark' = traditional TTS A/B benchmark (provider-generated audio).
    # 'blind_test_only' = standalone blind test built from existing recordings
    # / uploads / past TTS samples; no TTS generation happens.
    mode = Column(String(32), nullable=False, default="benchmark")

    provider_a = Column(String(100), nullable=True)
    model_a = Column(String(100), nullable=True)
    voices_a = Column(JSON, nullable=True)

    provider_b = Column(String(100), nullable=True)
    model_b = Column(String(100), nullable=True)
    voices_b = Column(JSON, nullable=True)

    sample_texts = Column(JSON, nullable=False)
    num_runs = Column(Integer, nullable=False, default=1)

    blind_test_results = Column(JSON, nullable=True)
    evaluation_summary = Column(JSON, nullable=True)

    eval_stt_provider = Column(String(100), nullable=True)
    eval_stt_model = Column(String(100), nullable=True)

    celery_task_id = Column(String, nullable=True, index=True)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)

    samples = relationship("TTSSample", back_populates="comparison", cascade="all, delete-orphan")


class TTSSample(Base):
    """Individual TTS audio sample within a comparison."""
    __tablename__ = "tts_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_id = Column(UUID(as_uuid=True), ForeignKey("tts_comparisons.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: mirrors the parent TTSComparison's workspace.
    # Denormalized for fast filter-by-workspace listings without a join.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    provider = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    voice_id = Column(String(255), nullable=True)
    voice_name = Column(String(255), nullable=True)
    side = Column(String(1), nullable=True)  # "A" or "B"
    sample_index = Column(Integer, nullable=False)
    run_index = Column(Integer, nullable=False, default=0)

    # 'tts' (default, audio is synthesized by a provider), 'recording' (audio
    # is reused from a CallImportRow recording), or 'upload' (audio was
    # uploaded by the user). Non-tts samples are marked completed up-front
    # by the API and skipped by the generation worker.
    source_type = Column(String(32), nullable=False, default="tts")
    # When source_type == 'recording', references CallImportRow.id (no FK
    # constraint to keep cascading deletes simple if a call import is later
    # removed; the audio_s3_key is what's actually used).
    source_ref_id = Column(UUID(as_uuid=True), nullable=True)

    text = Column(String, nullable=False)
    audio_s3_key = Column(String(512), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    ttfb_ms = Column(Float, nullable=True)

    evaluation_metrics = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False, default=TTSSampleStatus.PENDING.value)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    comparison = relationship("TTSComparison", back_populates="samples")


class TTSReportJob(Base):
    """Asynchronous PDF report generation jobs for Voice Playground."""
    __tablename__ = "tts_report_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: mirrors the parent TTSComparison's workspace.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    comparison_id = Column(UUID(as_uuid=True), ForeignKey("tts_comparisons.id", ondelete="CASCADE"), nullable=False, index=True)

    status = Column(String(50), nullable=False, default=TTSReportJobStatus.PENDING.value)
    format = Column(String(20), nullable=False, default="pdf")
    filename = Column(String(255), nullable=True)
    s3_key = Column(String(512), nullable=True)
    error_message = Column(String, nullable=True)
    celery_task_id = Column(String, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)

    comparison = relationship("TTSComparison")


class TTSBlindTestShareStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class TTSBlindTestShare(Base):
    """A publicly sharable blind test for a TTSComparison.

    The share_token is the capability: anyone holding it can open the public
    form and submit a response. Each comparison has at most one share row.
    """
    __tablename__ = "tts_blind_test_shares"
    __table_args__ = (
        UniqueConstraint("comparison_id", name="uq_blind_test_shares_comparison"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tts_comparisons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: mirrors the parent TTSComparison's workspace.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    share_token = Column(String(64), unique=True, nullable=False, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Internal notes visible only to the share creator (e.g. which voice
    # corresponds to which side, source notes for standalone blind tests).
    # Never exposed via the public blind test payload.
    creator_notes = Column(Text, nullable=True)

    # JSON list: [{ "key": str, "label": str, "type": "rating"|"comment", "scale": int? }]
    custom_metrics = Column(JSON, nullable=False)

    status = Column(String(20), nullable=False, default=TTSBlindTestShareStatus.OPEN.value)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, nullable=True)

    comparison = relationship("TTSComparison")
    responses = relationship(
        "TTSBlindTestResponse",
        back_populates="share",
        cascade="all, delete-orphan",
    )


class TTSBlindTestResponse(Base):
    """A single rater's submission against a TTSBlindTestShare."""
    __tablename__ = "tts_blind_test_responses"
    __table_args__ = (
        UniqueConstraint("share_id", "rater_email", name="uq_blind_test_response_share_email"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    share_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tts_blind_test_shares.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Workspace isolation: mirrors the parent TTSBlindTestShare's workspace.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    rater_name = Column(String(255), nullable=False)
    rater_email = Column(String(320), nullable=False, index=True)

    # JSON list keyed by sample_index. Server stores in TRUE A/B orientation
    # (already de-flipped from whatever the rater's UI showed):
    # [{
    #   "sample_index": int,
    #   "preferred": "A" | "B",
    #   "ratings_a": { metric_key: number },
    #   "ratings_b": { metric_key: number },
    #   "comment": str?
    # }]
    responses = Column(JSON, nullable=False)

    ip = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)

    submitted_at = Column(DateTime(timezone=True), server_default=func.now())

    share = relationship("TTSBlindTestShare", back_populates="responses")


class PromptPartial(Base):
    """Prompt Partial - Reusable prompt templates with version history."""
    __tablename__ = "prompt_partials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every prompt partial belongs to a workspace
    # within its org. Versions inherit this workspace_id.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    tags = Column(JSON, nullable=True)
    current_version = Column(Integer, nullable=False, default=1)
    # Cached LLM-generated flowchart for imported production agent prompts.
    # Shape: AgentFlowGraph JSON (nodes[], edges[]).
    agent_flowchart = Column(JSON, nullable=True)
    agent_flowchart_status = Column(String(20), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)

    versions = relationship("PromptPartialVersion", back_populates="prompt_partial", cascade="all, delete-orphan", order_by="PromptPartialVersion.version.desc()")


class PromptPartialVersion(Base):
    """Version history for a prompt partial."""
    __tablename__ = "prompt_partial_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_partial_id = Column(UUID(as_uuid=True), ForeignKey("prompt_partials.id", ondelete="CASCADE"), nullable=False, index=True)
    # Workspace isolation: mirrors the parent PromptPartial's workspace.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    change_summary = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String, nullable=True)

    prompt_partial = relationship("PromptPartial", back_populates="versions")

    __table_args__ = (
        UniqueConstraint('prompt_partial_id', 'version', name='uq_prompt_partial_version'),
    )


class CustomTTSVoice(Base):
    """Organization-scoped custom TTS voice metadata."""
    __tablename__ = "custom_tts_voices"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "voice_id", name="uq_custom_tts_voice_org_provider_voice_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    provider = Column(String(100), nullable=False, index=True)
    voice_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    gender = Column(String(50), nullable=True)
    accent = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class PromptOptimizationRun(Base):
    """A single GEPA prompt optimization run for an agent."""
    __tablename__ = "prompt_optimization_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every optimization run belongs to a workspace
    # within its org. Candidates inherit this workspace_id.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)
    evaluator_id = Column(UUID(as_uuid=True), ForeignKey("evaluators.id"), nullable=True)
    voice_bundle_id = Column(UUID(as_uuid=True), ForeignKey("voicebundles.id"), nullable=True)

    seed_prompt = Column(Text, nullable=False)
    best_prompt = Column(Text, nullable=True)
    best_score = Column(Float, nullable=True)

    status = Column(String(20), nullable=False, default=PromptOptimizationStatus.PENDING.value)
    config = Column(JSON, nullable=True)
    reflection_trace = Column(JSON, nullable=True)
    metric_history = Column(JSON, nullable=True)

    num_iterations = Column(Integer, nullable=True)
    num_metric_calls = Column(Integer, nullable=True)

    celery_task_id = Column(String, nullable=True, index=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)

    candidates = relationship("PromptOptimizationCandidate", back_populates="optimization_run", cascade="all, delete-orphan")


class PromptOptimizationCandidate(Base):
    """A candidate prompt generated during an optimization run."""
    __tablename__ = "prompt_optimization_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    optimization_run_id = Column(UUID(as_uuid=True), ForeignKey("prompt_optimization_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    # Workspace isolation: mirrors the parent PromptOptimizationRun's workspace.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    prompt_text = Column(Text, nullable=False)
    score = Column(Float, nullable=True)
    metric_breakdown = Column(JSON, nullable=True)
    reflection_summary = Column(Text, nullable=True)

    parent_candidate_id = Column(UUID(as_uuid=True), ForeignKey("prompt_optimization_candidates.id"), nullable=True)

    is_accepted = Column(Boolean, nullable=False, default=False)
    pushed_to_provider_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    optimization_run = relationship("PromptOptimizationRun", back_populates="candidates")


class TelephonyIntegration(Base):
    """Per-organization telephony provider credentials and configuration.

    Multiple rows per (organization_id, provider) are allowed so that an
    organization can keep several Plivo / Exotel accounts side-by-side.
    A partial unique index in migration 028 enforces at most one row with
    is_default = TRUE per (org, provider); resolution falls back to that
    default row when the caller does not pin a specific credential.
    """

    __tablename__ = "telephony_integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False, default="plivo")
    name = Column(String(255), nullable=True)  # Optional friendly name to disambiguate multiple credentials

    auth_id = Column(String(255), nullable=False)
    auth_token = Column(String(512), nullable=False)

    verify_app_uuid = Column(String(255), nullable=True)
    voice_app_id = Column(String(255), nullable=True)
    sip_domain = Column(String(255), nullable=True)
    masking_config = Column(JSON, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TelephonyPhoneNumber(Base):
    """Inventory of telephony phone numbers owned by an organization."""

    __tablename__ = "telephony_phone_numbers"
    __table_args__ = (
        UniqueConstraint("organization_id", "phone_number", name="uq_telephony_number_org_phone"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    telephony_integration_id = Column(
        UUID(as_uuid=True), ForeignKey("telephony_integrations.id"), nullable=False, index=True
    )

    phone_number = Column(String(20), nullable=False, index=True)
    country_iso2 = Column(String(2), nullable=True)
    region = Column(String(100), nullable=True)
    number_type = Column(String(20), nullable=True)
    capabilities = Column(JSON, nullable=True)
    provider_app_id = Column(String(255), nullable=True)

    is_masking_pool = Column(Boolean, default=False, nullable=False)
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "agents.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_telephony_phone_numbers_agent_id",
        ),
        nullable=True,
        index=True,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TelephonyVerifySession(Base):
    """Tracks voice OTP verification sessions via telephony provider."""

    __tablename__ = "telephony_verify_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    provider_session_uuid = Column(String(255), nullable=False, unique=True, index=True)
    recipient_number = Column(String(20), nullable=False)
    channel = Column(String(10), nullable=False, default="voice")
    status = Column(String(20), nullable=False, default="pending")
    initiated_by = Column(String(255), nullable=True)
    verify_app_uuid = Column(String(255), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TelephonyMaskedSession(Base):
    """Number-masking session between two parties through a middle number."""

    __tablename__ = "telephony_masked_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    telephony_integration_id = Column(UUID(as_uuid=True), ForeignKey("telephony_integrations.id"), nullable=False)
    masked_number_id = Column(
        UUID(as_uuid=True), ForeignKey("telephony_phone_numbers.id"), nullable=False, index=True
    )
    masked_number = Column(String(20), nullable=False)
    party_a_number = Column(String(20), nullable=False)
    party_b_number = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    session_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CallImportSchema(Base):
    """Reusable Input Parameter schema for the call-uploads flow.

    A schema is workspace-scoped: users define a named bundle of typed
    Input Parameters once (e.g. "Standard Voice QA" with conversation_id +
    recording_url + transcript + agent_name) and then map those parameters
    to CSV/Excel headers each time they upload a new batch.

    Every schema MUST contain exactly one parameter with
    ``type='conversation_id'`` and ``is_required=True`` - that's the
    mandatory identity field every imported row needs. The invariant is
    enforced in app code on create/update (no DB-level CHECK because the
    parent + children are written across two tables in one transaction).
    """

    __tablename__ = "call_import_schemas"
    __table_args__ = (
        # Case-insensitive uniqueness is enforced via the matching partial
        # index on ``LOWER(name)`` in the migration; this constraint here
        # would be case-sensitive and is intentionally omitted to avoid
        # confusing the user.
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    parameters = relationship(
        "CallImportSchemaParameter",
        back_populates="schema",
        cascade="all, delete-orphan",
        order_by="CallImportSchemaParameter.ordering",
    )


class CallImportSchemaParameter(Base):
    """A single typed parameter inside a :class:`CallImportSchema`.

    ``type`` is one of the strings tracked by
    :data:`app.models.enums.CallImportParameterType`. ``conversation_id``
    is reserved for the mandatory identity parameter every schema must
    contain.
    """

    __tablename__ = "call_import_schema_parameters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_import_schemas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    type = Column(String(32), nullable=False)
    description = Column(Text, nullable=True)
    is_required = Column(Boolean, nullable=False, default=False)
    # Stable ordering so the UI renders parameters in the order the
    # schema author defined them (matters when conversation_id is pinned
    # first and the user re-orders the rest).
    ordering = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    schema = relationship("CallImportSchema", back_populates="parameters")


class CallImport(Base):
    """Batch record for a CSV-driven call import job."""

    __tablename__ = "call_imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    # Workspace isolation: every imported batch belongs to a workspace
    # within its org. The /upload endpoint stamps it from the active
    # workspace header (or the org's Default if absent).
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Telephony provider key (e.g. ``'exotel'``, ``'plivo'``). In the
    # legacy one-shot ``POST /upload`` endpoint this is supplied with the
    # file; in the three-stage flow (UPLOAD -> MAP -> IMPORT) the value
    # isn't known until the IMPORT stage, so the column is nullable for
    # ``uploaded`` / ``mapped`` batches.
    provider = Column(String(50), nullable=True, default="exotel")
    # Pin a specific telephony credential for this batch so the worker
    # downloads recordings using *that* row instead of the org default.
    # NULL preserves legacy behavior (resolve by provider + default).
    telephony_integration_id = Column(
        UUID(as_uuid=True),
        ForeignKey("telephony_integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_filename = Column(String(512), nullable=True)
    # When the source file was a multi-sheet Excel workbook, this records
    # the worksheet the rows came from (one batch per sheet). NULL for CSV
    # uploads since CSV has no sheet concept.
    sheet_name = Column(String(255), nullable=True)

    # --- Source-file staging (UPLOAD stage) ---------------------------
    # The raw CSV / Excel file is stored in S3 between stages so the
    # user can come back later to MAP and IMPORT without re-uploading.
    # ``source_s3_key`` is NULL on legacy batches that were imported via
    # the one-shot endpoint (those batches stay read-only post-import).
    source_s3_key = Column(Text, nullable=True)
    source_format = Column(String(16), nullable=True)
    source_size_bytes = Column(BigInteger, nullable=True)
    source_content_type = Column(String(255), nullable=True)

    # Snapshot of the file's sheets + headers captured at UPLOAD time
    # so the MAP UI doesn't need to re-fetch the source bytes from S3.
    # Shape: ``[{"name": str, "headers": [str, ...], "row_count": int}, ...]``.
    available_sheets = Column(JSON, nullable=True)

    # User's explicit "drop these columns" decision captured at MAP
    # time. Was validation-only and ephemeral in the legacy flow; now
    # persisted so the IMPORT stage can re-parse the file with the same
    # mapping/skip intent.
    skipped_columns = Column(JSON, nullable=False, default=list)

    # Free-text high-level segregation label. Powers the "Dataset" filter
    # at the top of the imports page; multiple imports can share a value.
    dataset = Column(String(255), nullable=True, index=True)

    # Reusable Input Parameter schema this batch was uploaded against.
    # NULL on legacy batches uploaded before the schema-driven flow
    # shipped; those still render via ``column_mapping`` + ``extra_columns``
    # + ``custom_column_mapping`` below.
    schema_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_import_schemas.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # New schema-driven mapping: ``{schema_parameter_name: csv_header}``.
    # Populated for new uploads; empty dict on legacy batches.
    parameter_mapping = Column(JSON, nullable=False, default=dict)

    # Legacy free-form mapping (pre-schema-flow). Kept on the model so
    # batches that were uploaded before the schema feature shipped still
    # render correctly on the detail page; new uploads stop writing here.
    # Keys: external_call_id (required), transcript, recording_url.
    # (DB column ``external_call_id`` is now ``conversation_id``; this
    # JSON key stays as-is for historical batches.)
    # Values: original CSV header strings (preserve user casing for export).
    column_mapping = Column(JSON, nullable=False, default=dict)
    # Ordered list of additional CSV header strings the uploader wants
    # preserved verbatim into the evaluation export CSV.
    extra_columns = Column(JSON, nullable=False, default=list)
    # User-defined ``{custom_field_name: csv_header}`` mappings on top of
    # the three system fields above. Cells from the mapped CSV columns are
    # preserved per row (keyed by the CSV header in ``raw_columns``) and
    # surface in the evaluation export under the uploader-chosen name.
    custom_column_mapping = Column(JSON, nullable=False, default=dict)

    total_rows = Column(Integer, nullable=False, default=0)
    completed_rows = Column(Integer, nullable=False, default=0)
    failed_rows = Column(Integer, nullable=False, default=0)

    status = Column(
        Enum(CallImportStatus, values_callable=get_enum_values),
        nullable=False,
        default=CallImportStatus.PENDING,
        index=True,
    )
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    rows = relationship(
        "CallImportRow",
        back_populates="call_import",
        cascade="all, delete-orphan",
        order_by="CallImportRow.row_index",
    )
    tags = relationship(
        "CallImportTag",
        secondary="call_import_tag_assignments",
        backref="call_imports",
        lazy="selectin",
    )
    evaluations = relationship(
        "CallImportEvaluation",
        back_populates="call_import",
        cascade="all, delete-orphan",
    )


class CallImportRow(Base):
    """A single row within a CallImport batch (one CSV line / one external call)."""

    __tablename__ = "call_import_rows"
    __table_args__ = (
        UniqueConstraint("call_import_id", "row_index", name="uq_call_import_row_index"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)

    row_index = Column(Integer, nullable=False)
    # Was historically named ``external_call_id``; renamed to
    # ``conversation_id`` so the new schema-driven upload flow can refer
    # to it by a single canonical name across the schema definition,
    # exports, and downstream evaluation tables.
    conversation_id = Column(String(255), nullable=False, index=True)
    # Optional at upload time; the worker resolves it via Exotel's Calls API when
    # absent and writes the resolved URL back here so retries are cheap.
    recording_url = Column(Text, nullable=True)
    # Date-only call recording date supplied by the import schema. Used
    # for historical report comparisons without timezone/time ambiguity.
    recording_date = Column(Date, nullable=True, index=True)
    # The "production" transcript: the value supplied via the CSV
    # upload mapping. Never overwritten by the diarisation worker —
    # the worker writes its output into ``diarised_transcript`` so
    # the user keeps both versions side by side.
    transcript = Column(Text, nullable=True)
    # Snapshot of the original CSV row keyed by the user's headers so the
    # evaluation export can reproduce every column the uploader supplied
    # (mapped + extra). NULL on legacy rows imported before this column.
    raw_columns = Column(JSON, nullable=True)

    # Where the value in ``transcript`` came from. ``csv`` = supplied via
    # the upload mapping, ``edited`` = manually changed in the UI. NULL
    # on rows that have never had a production transcript.
    # (Worker-produced transcripts now live in ``diarised_transcript``
    # and are tracked via ``diarised_transcript_*`` metadata below.)
    transcript_source = Column(String(20), nullable=True)
    # Provider/model recorded by the (legacy) post-hoc transcription
    # worker. New worker runs leave these NULL and write into the
    # ``diarised_transcript_*`` columns instead; kept on the model for
    # backwards compatibility with pre-split rows that still carry the
    # original transcription metadata here.
    transcript_provider = Column(String(50), nullable=True)
    transcript_model = Column(String(100), nullable=True)
    # Lifecycle status for the legacy transcription workflow itself,
    # independent of the row's recording-fetch ``status``. ``idle`` =
    # no transcribe task has touched this column. New diarisation runs
    # update ``diarised_transcript_status`` instead.
    transcript_status = Column(
        String(20),
        nullable=False,
        default="idle",
    )
    transcript_error = Column(Text, nullable=True)
    transcribed_at = Column(DateTime(timezone=True), nullable=True)

    # The "diarised" transcript: produced by the post-hoc
    # transcription/diarisation worker. Stored separately so a manual
    # diarisation run never clobbers the production transcript above.
    # Evaluations can be configured to score against either column
    # (see ``CallImportEvaluation.transcript_source``).
    diarised_transcript = Column(Text, nullable=True)
    # Provider/model the diarisation worker used. Surfaced in the UI
    # as "Diarised via deepgram/nova-2" next to the diarised
    # transcript section.
    diarised_transcript_provider = Column(String(50), nullable=True)
    diarised_transcript_model = Column(String(100), nullable=True)
    # Lifecycle status for the diarisation workflow.
    # ``idle`` = no diarisation task has run; ``pending``/``running`` =
    # a Celery task is queued or in flight; ``completed``/``failed`` =
    # terminal. Independent of ``transcript_status`` so the two
    # transcripts can be in different lifecycle states.
    diarised_transcript_status = Column(
        String(20),
        nullable=False,
        default="idle",
        server_default="idle",
    )
    diarised_transcript_error = Column(Text, nullable=True)
    diarised_at = Column(DateTime(timezone=True), nullable=True)

    # Structured speaker turns produced by the diarisation worker —
    # ``[{ "speaker": "agent"|"user"|"speaker_3", "text": "...",
    #      "start": float, "end": float, "raw_speaker": "Speaker 1" }, ...]``
    # The plain-text ``diarised_transcript`` above is a rendered view
    # of this list (``<speaker>: <text>`` per line). When the worker
    # cannot recover structured turns (no pyannote token / single-
    # speaker recording / provider that doesn't surface segments) this
    # column stays NULL and the plain-text path is still populated.
    diarised_segments = Column(JSON, nullable=True)
    # When True the ``agent`` <-> ``user`` mapping inside
    # ``diarised_segments`` is inverted at render / export time. The
    # worker writes the canonical mapping using the "first speaker is
    # the agent" heuristic; reviewers can flip the toggle from the row
    # detail panel without re-running diarisation.
    diarised_speaker_swap = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    # LLM that turned the STT plain-text output into structured
    # ``diarised_segments``. The legacy diarisation worker used
    # pyannote and left these NULL; the current path always runs an
    # LLM with the operator-supplied (or default) ``diarised_prompt``
    # below, and records exactly which model + prompt produced each
    # row so reviewers can reproduce a specific run.
    diarised_llm_provider = Column(String(50), nullable=True)
    diarised_llm_model = Column(String(100), nullable=True)
    diarised_llm_credential_id = Column(UUID(as_uuid=True), nullable=True)
    diarised_prompt = Column(Text, nullable=True)
    # Which diarisation pipeline produced this row's turns.
    #   * ``"stt_llm"`` (default) — two-stage: STT then LLM diariser.
    #     ``diarised_transcript_provider``/``_model`` describe the STT
    #     side; ``diarised_llm_provider``/``_model`` the LLM side.
    #   * ``"llm_only"`` — single-stage: audio fed straight to a
    #     multimodal LLM. ``diarised_transcript_provider`` is stamped
    #     with the sentinel ``"llm_only"``; the real model is on
    #     ``diarised_llm_*``.
    # Persisting it on the row (not just the run) lets the row detail
    # panel render the right "Diarised via …" label even for ad-hoc
    # standalone transcribes (no parent evaluation).
    transcribe_mode = Column(
        String(20),
        nullable=False,
        default="stt_llm",
        server_default="stt_llm",
    )

    status = Column(
        Enum(CallImportRowStatus, values_callable=get_enum_values),
        nullable=False,
        default=CallImportRowStatus.PENDING,
        index=True,
    )

    recording_s3_key = Column(String(1024), nullable=True)
    recording_content_type = Column(String(128), nullable=True)
    recording_size_bytes = Column(Integer, nullable=True)

    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    celery_task_id = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    call_import = relationship("CallImport", back_populates="rows")


class CallImportTag(Base):
    """User-defined tag that can be attached to one or more call imports.

    Tags coexist with the free-text ``CallImport.dataset`` column: dataset
    is the primary high-level segregation, tags are an optional secondary
    classification (an import can have many tags).
    """

    __tablename__ = "call_import_tags"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_call_import_tag_org_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    name = Column(String(255), nullable=False)
    color = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CallImportTagAssignment(Base):
    """Many-to-many join table between CallImport and CallImportTag."""

    __tablename__ = "call_import_tag_assignments"

    call_import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_imports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_import_tags.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CallImportEvaluation(Base):
    """Parent record for an evaluation run over a CallImport batch.

    A user picks a subset of org ``Metric`` rows and triggers an evaluation;
    we fan out one ``CallImportEvaluationRow`` per source row and roll up
    counters as workers finish. Status mirrors ``CallImportStatus`` plus a
    ``RUNNING`` value so the UI can distinguish "queued" from "in flight".
    """

    __tablename__ = "call_import_evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    # Workspace isolation: mirrors the parent CallImport's workspace.
    # Denormalized for fast filter-by-workspace listings without a join.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Optional user-supplied label for this run. Lets the UI surface
    # something more meaningful than the UUID prefix (e.g. "March QA pass").
    name = Column(String(255), nullable=True)

    # JSON list of Metric UUID strings selected for this run. Stored as text
    # in JSON so we don't have to deal with PG arrays of UUIDs / cascade
    # delete policies when metrics are removed; the loader filters for
    # still-existing org metrics at run time.
    selected_metric_ids = Column(JSON, nullable=False, default=list)
    # Hierarchy grouping snapshot: ``{parent_id_str: [child_id_str, ...]}``.
    # Captures which children belong to which parent for THIS run so the UI
    # / aggregator can reconstruct the tree even when the user selected
    # only a subset of children, or after metrics are deleted / renamed.
    # NULL on legacy rows means "no hierarchy" → fall back to flat
    # ``selected_metric_ids`` semantics.
    selected_metric_groups = Column(JSON, nullable=True)
    # User-driven merges of LLM-discovered candidate sub-labels for
    # ``allow_discovery`` parents. Shape:
    # ``{"<parent_metric_id>": {"<from_slug>": "<to_slug>", ...}}``.
    # Populated via ``POST .../discovered-labels/merge``; consulted by
    # the discovered-labels aggregator, the flow graph builder, and the
    # worker so that rows finishing AFTER a merge cannot reintroduce
    # the merged-away slug. Empty dict on fresh rows.
    discovered_label_aliases = Column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    # Per-run opt-in for top-level metric discovery. When True, the LLM
    # is asked to propose brand-new top-level metrics (boolean / rating /
    # category) observed in the transcripts in addition to scoring the
    # ``selected_metric_ids`` for the row. Candidates surface in a
    # "Discovered metrics" panel on the evaluation's Flow tab and can
    # be promoted into real standalone ``Metric`` rows via
    # ``POST /metrics/from-discovered``. Defaults to False so existing
    # evaluation creation payloads keep their previous behaviour.
    discover_new_metrics = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Flat slug-to-slug redirect map for user merges + tombstones of
    # discovered top-level metric candidates. Mirrors
    # ``discovered_label_aliases`` but is NOT nested per parent —
    # top-level metric discovery is not scoped to any parent. Shape::
    #
    #     {"<from_slug>": "<to_slug>", ...}
    #
    # An empty-string value tombstones the slug so workers finishing
    # later can't re-introduce it.
    discovered_metric_aliases = Column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    # Run-level LLM config picked from the Run Evaluation modal. NULL on
    # legacy rows means "use the historical OpenAI/gpt-4o default" — the
    # worker checks for this and falls back accordingly. ``llm_credential_id``
    # pins a specific AIProvider row when the org has multiple credentials
    # for the same provider.
    llm_provider = Column(String(50), nullable=True)
    llm_model = Column(String(100), nullable=True)
    llm_credential_id = Column(
        UUID(as_uuid=True),
        ForeignKey("aiproviders.id", ondelete="SET NULL"),
        nullable=True,
    )
    llm_config = Column(JSON, nullable=True)
    # Optional per-metric LLM override:
    # ``{"<metric_id>": {"provider": "...", "model": "...", "credential_id": "..."}}``.
    # Each entry overrides the run-level default for that metric only;
    # missing keys = use run-level default. Stored as JSON so the UI can
    # round-trip arbitrary {provider, model} pairs without migrations.
    metric_llm_overrides = Column(JSON, nullable=True)

    # When ``auto_transcribe`` was set on the create payload, record the
    # STT provider/model used so the UI can show "Auto-transcribed via
    # deepgram/nova-2" on the evaluation header. ``stt_credential_id`` is
    # untyped (no FK) because STT keys may live in either ``aiproviders``
    # (OpenAI) or ``integrations`` (Deepgram, ElevenLabs) — the
    # transcription service handles the lookup.
    stt_provider = Column(String(50), nullable=True)
    stt_model = Column(String(100), nullable=True)
    stt_credential_id = Column(UUID(as_uuid=True), nullable=True)

    # Run-level LLM diariser config. Used when the create-run /
    # retry-run paths chain a ``transcribe_call_import_row_task``
    # because the row is missing a diarised transcript. Persisted on
    # the run so a retry uses the same diariser the original create
    # call picked (unless the retry payload explicitly overrides).
    diarisation_llm_provider = Column(String(50), nullable=True)
    diarisation_llm_model = Column(String(100), nullable=True)
    diarisation_llm_credential_id = Column(UUID(as_uuid=True), nullable=True)
    diarisation_prompt = Column(Text, nullable=True)
    # Mode the run was *created* with for its auto-transcribe step.
    # Retry chains read this to decide whether to enqueue an STT+LLM
    # transcribe or a single-stage multimodal LLM transcribe — without
    # it we'd have to infer the mode from "stt_provider is NULL", which
    # would silently break legacy rows that simply never configured
    # auto-transcribe. See migration 041 for the column DDL.
    transcribe_mode = Column(
        String(20),
        nullable=False,
        default="stt_llm",
        server_default="stt_llm",
    )

    # Which of the two transcripts on each ``CallImportRow`` this run
    # scored against. ``'production'`` reads ``CallImportRow.transcript``
    # (the CSV-supplied value); ``'diarised'`` reads
    # ``CallImportRow.diarised_transcript`` (the worker output). When
    # the user ticks both checkboxes in the Run Evaluation modal we
    # create two ``CallImportEvaluation`` rows — one per source — so
    # the two scorings can be compared side-by-side. Defaults to
    # ``'production'`` so legacy runs (which always read the single
    # historical ``transcript`` column) keep their semantics.
    transcript_source = Column(
        String(20),
        nullable=False,
        default="production",
        server_default="production",
    )

    # Cached LLM-generated TLDR rendered above the Visualizations charts.
    # Populated lazily by ``POST /evaluations/{eval_id}/insights`` so we
    # never auto-burn LLM tokens on page load. Shape::
    #   {"narrative": str, "patterns": [str, ...],
    #    "generated_at": iso8601, "generated_at_completed_rows": int,
    #    "provider": str, "model": str}
    # NULL on rows that have never been summarised.
    tldr_summary = Column(JSON, nullable=True)

    # Cached LLM-generated user insights for External Audit PDF section 03.
    # Populated by a background Celery job triggered alongside TLDR generation.
    # Shape: EvaluationUserInsightsState JSON (status, insights[], progress, …).
    user_insights = Column(JSON, nullable=True)

    # Cached per-metric failure clustering for internal diagnostics PDF/UI.
    # Shape: EvaluationMetricClustersState JSON (status, groups[], …).
    metric_clusters = Column(JSON, nullable=True)

    # Cached LLM-generated prompt improvement suggestions keyed to an
    # imported agent (PromptPartial tagged __imported_agent__).
    # Shape: EvaluationPromptImprovementsState JSON.
    prompt_improvements = Column(JSON, nullable=True)

    # Cached LLM explanations for week-over-week metric deltas keyed by
    # baseline evaluation id + completed row counts.
    period_delta_explanations = Column(JSON, nullable=True)

    status = Column(String(20), nullable=False, default="pending", index=True)

    total_rows = Column(Integer, nullable=False, default=0)
    completed_rows = Column(Integer, nullable=False, default=0)
    failed_rows = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    celery_group_id = Column(String(255), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    call_import = relationship("CallImport", back_populates="evaluations")
    row_results = relationship(
        "CallImportEvaluationRow",
        back_populates="evaluation",
        cascade="all, delete-orphan",
    )


class CallImportEvaluationRow(Base):
    """Per-source-row scoring output for a CallImportEvaluation parent."""

    __tablename__ = "call_import_evaluation_rows"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "call_import_row_id", name="uq_call_import_evaluation_row"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_import_evaluations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    call_import_row_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_import_rows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(String(20), nullable=False, default="pending", index=True)
    # Same shape as EvaluatorResult.metric_scores: {metric_id_str: {value, type, metric_name, ...}}
    metric_scores = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    celery_task_id = Column(String(255), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evaluation = relationship("CallImportEvaluation", back_populates="row_results")
    source_row = relationship("CallImportRow")


class CallImportEvaluationReportSnapshot(Base):
    """Persisted PDF-report aggregate used for period-over-period deltas."""

    __tablename__ = "call_import_evaluation_report_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_import_evaluations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    call_import_id = Column(
        UUID(as_uuid=True),
        ForeignKey("call_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    period_label = Column(String(64), nullable=True, index=True)
    period_start = Column(Date, nullable=True, index=True)
    period_end = Column(Date, nullable=True, index=True)
    report_config = Column(JSON, nullable=False, default=dict, server_default="{}")
    selected_metric_ids = Column(JSON, nullable=False, default=list, server_default="[]")
    metric_aggregates = Column(JSON, nullable=False, default=list, server_default="[]")
    insight_aggregates = Column(JSON, nullable=False, default=list, server_default="[]")
    narrative = Column(JSON, nullable=True)
    total_calls = Column(Integer, nullable=False, default=0)
    selected_metric_count = Column(Integer, nullable=False, default=0)
    total_metric_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Judge Alignment (AlignEval-style hybrid integration)
#
# Three tables back the "Judge Alignment" surface:
#   - JudgeDataset:     a labeled dataset materialised from one of three sources
#                       (voice transcripts, existing Metric/Evaluator outputs,
#                       or a generic CSV upload). Holds the dataset's source
#                       config + which fields play the role of input/output.
#   - JudgeSample:      one row in a dataset (input/output pair plus an
#                       optional binary pass/fail human label).
#   - JudgeRun:         a single run of an LLM-judge (existing Evaluator) over
#                       a subset of samples, with computed alignment metrics
#                       (precision/recall/F1/Cohen's kappa) and per-sample
#                       predictions. Optionally links to a GEPA optimization
#                       run when the user kicks off prompt tuning from a
#                       dataset.
# ---------------------------------------------------------------------------


class JudgeDataset(Base):
    """Container for binary-labeled samples used to calibrate an LLM-judge."""

    __tablename__ = "judge_datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # Workspace isolation: every judge dataset belongs to a workspace
    # within its org. Samples and runs inherit this workspace_id.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # One of: "transcript", "metric_output", "csv"
    source_type = Column(String(32), nullable=False, index=True)
    # Source-specific config. Examples:
    #   transcript:     {"transcription_ids": [...]} or {"agent_id": "..."}
    #   metric_output:  {"metric_id": "...", "evaluator_id": "..."}
    #   csv:            {"s3_key": "...", "filename": "..."}
    source_config = Column(JSON, nullable=False, default=dict)

    # Field roles - which textual content is "input" vs "output" for the judge.
    # For voice transcripts both default to the transcript text but can be
    # tightened (e.g. agent-only turns vs full conversation).
    input_field = Column(String(64), nullable=False, default="input")
    output_field = Column(String(64), nullable=False, default="output")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)

    samples = relationship(
        "JudgeSample",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="JudgeSample.created_at",
    )
    runs = relationship(
        "JudgeRun",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="JudgeRun.created_at.desc()",
    )


class JudgeSample(Base):
    """One labelable input/output pair within a JudgeDataset."""

    __tablename__ = "judge_samples"
    __table_args__ = (
        UniqueConstraint("dataset_id", "external_id", name="uq_judge_samples_dataset_external"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("judge_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Workspace isolation: mirrors the parent JudgeDataset's workspace.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Stable identifier within the source (e.g. transcription UUID, CSV row id).
    # Used to dedupe re-imports and link back to the originating record.
    external_id = Column(String(128), nullable=True, index=True)

    input_text = Column(Text, nullable=False)
    output_text = Column(Text, nullable=False)

    # Binary human label: "pass" | "fail" | null (unlabeled).
    # Stored as string (rather than enum) so it stays trivially extendable.
    label = Column(String(16), nullable=True, index=True)
    labeled_by = Column(String(255), nullable=True)
    labeled_at = Column(DateTime(timezone=True), nullable=True)

    # Source-specific context (e.g. agent_id, original metric value, csv row).
    extra = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    dataset = relationship("JudgeDataset", back_populates="samples")


class JudgeRun(Base):
    """One execution of an LLM-judge against a JudgeDataset, with alignment metrics."""

    __tablename__ = "judge_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("judge_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # Workspace isolation: mirrors the parent JudgeDataset's workspace.
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Reuses the existing Evaluator row (its custom_prompt + llm_provider + llm_model
    # define the judge under test). Nullable so a run may target an inline prompt
    # in the future without inflating the Evaluator table.
    evaluator_id = Column(
        UUID(as_uuid=True), ForeignKey("evaluators.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Which subset was scored: "all" | "dev" | "test"
    split = Column(String(16), nullable=False, default="all")

    # Snapshot of the model used (so a later Evaluator edit doesn't rewrite history).
    llm_provider = Column(String(64), nullable=True)
    llm_model = Column(String(128), nullable=True)

    # Computed alignment metrics:
    #   {"precision": float, "recall": float, "f1": float, "kappa": float,
    #    "tp": int, "fp": int, "tn": int, "fn": int, "n": int}
    metrics = Column(JSON, nullable=True)

    # Per-sample predictions, keyed by sample_id (UUID string):
    #   {sample_id: {"prediction": "pass"|"fail", "explanation": str, "raw": str}}
    predictions = Column(JSON, nullable=True)

    # Run lifecycle.
    status = Column(String(20), nullable=False, default="pending", index=True)
    error_message = Column(Text, nullable=True)
    celery_task_id = Column(String, nullable=True, index=True)

    # Optional link to a GEPA optimization run kicked off from this dataset.
    gepa_optimization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_optimization_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=True)

    dataset = relationship("JudgeDataset", back_populates="runs")
