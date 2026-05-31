"""Pydantic schemas for request/response validation."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, validator
from typing import Optional, List, Dict, Any, Literal
from datetime import date, datetime
from uuid import UUID
from app.models.enums import (
    EvaluationType, EvaluationStatus, EvaluatorResultStatus, RoleEnum, InvitationStatus,
    LanguageEnum, CallTypeEnum, CallMediumEnum, GenderEnum, AccentEnum, BackgroundNoiseEnum,
    IntegrationPlatform, ModelProvider, VoiceBundleType, TestAgentConversationStatus,
    MetricType, MetricCategory, MetricTrigger, CallRecordingStatus, AlertMetricType, AlertAggregation,
    AlertOperator, AlertNotifyFrequency, AlertStatus, AlertHistoryStatus, CronJobStatus,
    CallImportStatus, CallImportRowStatus, CallImportParameterType,
)



# Audio File Schemas
class AudioFileBase(BaseModel):
    """Base audio file schema."""

    filename: str
    format: str


class AudioFileCreate(AudioFileBase):
    """Schema for audio file creation."""

    file_size: int
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


class AudioFileResponse(AudioFileBase):
    """Schema for audio file response."""

    id: UUID
    file_size: int
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Evaluation Schemas
class EvaluationCreate(BaseModel):
    """Schema for creating an evaluation."""

    audio_id: UUID
    reference_text: Optional[str] = None
    evaluation_type: EvaluationType
    model_name: Optional[str] = Field(None, description="Model to use for evaluation")
    metrics: Optional[List[str]] = Field(
        default=["wer", "latency"], description="Metrics to calculate"
    )

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, v):
        """Validate metrics list."""
        allowed_metrics = ["wer", "cer", "latency", "quality_score", "rtf"]
        if v:
            invalid = [m for m in v if m not in allowed_metrics]
            if invalid:
                raise ValueError(f"Invalid metrics: {invalid}")
        return v


class EvaluationResponse(BaseModel):
    """Schema for evaluation response."""

    id: UUID
    audio_id: UUID
    reference_text: Optional[str] = None
    evaluation_type: EvaluationType
    model_name: Optional[str] = None
    status: EvaluationStatus
    metrics_requested: Optional[List[str]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EvaluationStatusResponse(BaseModel):
    """Schema for evaluation status response."""

    id: UUID
    status: EvaluationStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


# Evaluation Result Schemas
class EvaluationResultResponse(BaseModel):
    """Schema for evaluation result response."""

    evaluation_id: UUID
    status: EvaluationStatus
    transcript: Optional[str] = None
    metrics: Dict[str, Any]
    processing_time: Optional[float] = None
    model_used: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MetricsResponse(BaseModel):
    """Schema for metrics breakdown."""

    evaluation_id: UUID
    metrics: Dict[str, Any]
    processing_time: Optional[float] = None


# Comparison Schema
class ComparisonRequest(BaseModel):
    """Schema for comparing multiple evaluations."""

    evaluation_ids: List[UUID] = Field(..., min_length=2, description="At least 2 evaluation IDs to compare")


class ComparisonResponse(BaseModel):
    """Schema for comparison results."""

    evaluations: List[EvaluationResultResponse]
    comparison_metrics: Dict[str, Any]


# API Key Schemas
class APIKeyCreate(BaseModel):
    """Schema for creating API key."""

    name: Optional[str] = None


class APIKeyResponse(BaseModel):
    """Schema for API key response."""

    id: UUID
    key: str
    name: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Generic Response Schemas
class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class ErrorResponse(BaseModel):
    """Error response schema."""

    detail: str

# ============================================
# VAIOPS SCHEMAS - Voice AI Ops
# ============================================

# Enums moved to enums.py


# Agent Schemas
class AgentCreate(BaseModel):
    """Schema for creating a new agent"""
    name: str = Field(..., min_length=1, max_length=255)
    phone_number: Optional[str] = None
    language: LanguageEnum = LanguageEnum.ENGLISH
    description: str = Field(..., min_length=1)
    call_type: CallTypeEnum = CallTypeEnum.OUTBOUND
    call_medium: CallMediumEnum = CallMediumEnum.PHONE_CALL
    telephony_phone_number_id: Optional[UUID] = None
    voice_bundle_id: Optional[UUID] = None
    ai_provider_id: Optional[UUID] = None
    voice_ai_integration_id: UUID = Field(..., description="Voice AI integration is required")
    voice_ai_agent_id: str = Field(..., min_length=1, description="Voice AI agent ID is required")

    @field_validator('description')
    @classmethod
    def description_min_words(cls, v: str) -> str:
        if len(v.split()) < 10:
            raise ValueError('Description must be at least 10 words.')
        return v

    @field_validator('phone_number')
    @classmethod
    def phone_number_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != '':
            import re
            if not re.fullmatch(r'[\d+]+', v):
                raise ValueError('Phone number must contain only digits and the + character.')
        return v

    @model_validator(mode='after')
    def validate_phone_number(self):
        """Ensure phone_number is provided when call_medium is phone_call"""
        if self.call_medium == CallMediumEnum.PHONE_CALL and not self.phone_number:
            raise ValueError('phone_number is required when call_medium is phone_call')
        return self

    model_config = ConfigDict(json_schema_extra={
            "example": {
                "name": "Customer Support Bot",
                "phone_number": "+1234567890",
                "language": "en",
                "description": "A customer support bot that handles inquiries about orders, returns, and general questions",
                "call_type": "outbound",
                "voice_bundle_id": "123e4567-e89b-12d3-a456-426614174000",
                "voice_ai_integration_id": "123e4567-e89b-12d3-a456-426614174001",
                "voice_ai_agent_id": "agent_abc123"
            }
        })


class AgentUpdate(BaseModel):
    """Schema for updating an agent"""
    name: Optional[str] = None
    phone_number: Optional[str] = None
    language: Optional[LanguageEnum] = None
    description: Optional[str] = None
    call_type: Optional[CallTypeEnum] = None
    call_medium: Optional[CallMediumEnum] = None
    telephony_phone_number_id: Optional[UUID] = None
    voice_bundle_id: Optional[UUID] = None
    voice_ai_integration_id: Optional[UUID] = None
    voice_ai_agent_id: Optional[str] = None

    @model_validator(mode='after')
    def validate_voice_config(self):
        """Validate voice configuration - both voice_bundle_id and voice_ai_integration_id can be provided independently"""
        voice_bundle = self.voice_bundle_id
        voice_ai_integration = self.voice_ai_integration_id
        
        # If voice_ai_integration_id is provided, voice_ai_agent_id must also be provided
        if voice_ai_integration and not self.voice_ai_agent_id:
            raise ValueError('voice_ai_agent_id is required when voice_ai_integration_id is provided.')
        
        return self
    
    @model_validator(mode='after')
    def validate_phone_number(self):
        """Ensure phone_number is provided when call_medium is phone_call"""
        # Only validate if call_medium is being set to phone_call
        if self.call_medium == CallMediumEnum.PHONE_CALL and not self.phone_number:
            # If phone_number is not being updated, we need to check existing value
            # This will be handled in the route
            pass
        return self


class AgentResponse(BaseModel):
    """Schema for agent response"""
    id: UUID
    agent_id: Optional[str] = None
    name: str
    phone_number: Optional[str] = None
    language: LanguageEnum
    description: Optional[str]
    call_type: CallTypeEnum
    call_medium: CallMediumEnum
    telephony_phone_number_id: Optional[UUID] = None
    voice_bundle_id: Optional[UUID]
    ai_provider_id: Optional[UUID]
    voice_ai_integration_id: Optional[UUID]
    voice_ai_agent_id: Optional[str]
    provider_prompt: Optional[str] = None
    provider_prompt_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @field_validator('language', mode='before')
    @classmethod
    def convert_language(cls, v):
        """Convert string to LanguageEnum (handles uppercase DB values like ENGLISH -> en)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            # Map old uppercase names to new values
            language_map = {'english': 'en', 'spanish': 'es', 'french': 'fr', 'german': 'de', 
                          'chinese': 'zh', 'japanese': 'ja', 'hindi': 'hi', 'arabic': 'ar'}
            if v_lower in language_map:
                return LanguageEnum(language_map[v_lower])
            try:
                return LanguageEnum(v_lower)
            except ValueError:
                for enum_member in LanguageEnum:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid LanguageEnum value: {v}")
        return v

    @field_validator('call_type', mode='before')
    @classmethod
    def convert_call_type(cls, v):
        """Convert string to CallTypeEnum (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return CallTypeEnum(v_lower)
            except ValueError:
                for enum_member in CallTypeEnum:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid CallTypeEnum value: {v}")
        return v

    @field_validator('call_medium', mode='before')
    @classmethod
    def convert_call_medium(cls, v):
        """Convert string to CallMediumEnum (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return CallMediumEnum(v_lower)
            except ValueError:
                for enum_member in CallMediumEnum:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid CallMediumEnum value: {v}")
        return v

    model_config = ConfigDict(from_attributes=True)


# Persona Schemas
class PersonaCreate(BaseModel):
    """Schema for creating a new persona (TTS provider-tied voice identity)"""
    name: str = Field(..., min_length=1, max_length=255)
    gender: GenderEnum = GenderEnum.NEUTRAL
    tts_provider: Optional[str] = None
    tts_voice_id: Optional[str] = None
    tts_voice_name: Optional[str] = None
    is_custom: bool = False


class PersonaUpdate(BaseModel):
    """Schema for updating a persona"""
    name: Optional[str] = None
    gender: Optional[GenderEnum] = None
    tts_provider: Optional[str] = None
    tts_voice_id: Optional[str] = None
    tts_voice_name: Optional[str] = None
    is_custom: Optional[bool] = None


class PersonaResponse(BaseModel):
    """Schema for persona response"""
    id: UUID
    name: str
    gender: str
    tts_provider: Optional[str] = None
    tts_voice_id: Optional[str] = None
    tts_voice_name: Optional[str] = None
    is_custom: bool = False
    created_at: datetime
    updated_at: datetime

    @field_validator('gender', mode='before')
    @classmethod
    def convert_gender(cls, v):
        if v is None:
            return "neutral"
        if isinstance(v, str):
            return v.lower()
        if hasattr(v, 'value'):
            return v.value
        return v

    model_config = ConfigDict(from_attributes=True)


class PersonaCloneRequest(BaseModel):
    """Schema for cloning a persona"""
    name: Optional[str] = None


# Scenario Schemas
class ScenarioCreate(BaseModel):
    """Schema for creating a new scenario"""
    name: str = Field(..., min_length=1, max_length=255)
    agent_id: Optional[UUID] = None
    description: Optional[str] = None
    required_info: Dict[str, str] = Field(default_factory=dict)


class ScenarioUpdate(BaseModel):
    """Schema for updating a scenario"""
    name: Optional[str] = None
    agent_id: Optional[UUID] = None
    description: Optional[str] = None
    required_info: Optional[Dict[str, str]] = None


class ScenarioResponse(BaseModel):
    """Schema for scenario response"""
    id: UUID
    name: str
    agent_id: Optional[UUID]
    description: Optional[str]
    required_info: Dict[str, str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# IAM & USER SCHEMAS
# ============================================

# User Schemas
class UserCreate(BaseModel):
    """Schema for creating a user."""
    email: str = Field(..., description="User email address")
    name: Optional[str] = None
    password: Optional[str] = None  # Optional for invitation-based signup


class UserUpdate(BaseModel):
    """Schema for updating user profile."""
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response."""
    id: UUID
    email: str
    name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberResponse(BaseModel):
    """Schema for organization member response."""
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: RoleEnum
    joined_at: datetime
    user: UserResponse  # Include user details

    model_config = ConfigDict(from_attributes=True)


# Invitation Schemas
class InvitationCreate(BaseModel):
    """Schema for creating an invitation."""
    email: str = Field(..., description="Email address of the user to invite")
    role: RoleEnum = RoleEnum.READER


class InvitationResponse(BaseModel):
    """Schema for invitation response."""
    id: UUID
    organization_id: UUID
    email: str
    role: RoleEnum
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime
    organization_name: Optional[str] = None  # Include organization name

    @field_validator('role', mode='before')
    @classmethod
    def convert_role(cls, v):
        """Convert string to RoleEnum (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return RoleEnum(v_lower)
            except ValueError:
                for enum_member in RoleEnum:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid RoleEnum value: {v}")
        return v

    @field_validator('status', mode='before')
    @classmethod
    def convert_status(cls, v):
        """Convert string to InvitationStatus (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return InvitationStatus(v_lower)
            except ValueError:
                for enum_member in InvitationStatus:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid InvitationStatus value: {v}")
        return v

    model_config = ConfigDict(from_attributes=True)


class InvitationUpdate(BaseModel):
    """Schema for updating invitation (accept/decline)."""
    token: str


class RoleUpdate(BaseModel):
    """Schema for updating user role in organization."""
    role: RoleEnum


# Profile Schemas
class ProfileResponse(BaseModel):
    """Schema for user profile response."""
    id: UUID
    email: str
    name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    created_at: datetime
    organizations: List[dict] = Field(default_factory=list)  # List of org memberships

    model_config = ConfigDict(from_attributes=True)


# ============================================
# INTEGRATION SCHEMAS
# ============================================

class IntegrationCreate(BaseModel):
    """Schema for creating an integration."""
    platform: IntegrationPlatform
    api_key: str = Field(..., description="Private API key for the platform")
    public_key: Optional[str] = Field(None, description="Optional public API key (e.g. for Vapi)")
    name: Optional[str] = Field(None, description="Optional friendly name for the integration")
    is_default: Optional[bool] = Field(
        None,
        description=(
            "Mark this credential as the default for the (org, platform). "
            "If omitted and no default exists yet, this row becomes the default."
        ),
    )


class IntegrationUpdate(BaseModel):
    """Schema for updating an integration."""
    name: Optional[str] = None
    api_key: Optional[str] = None
    public_key: Optional[str] = None
    is_active: Optional[bool] = None


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    id: UUID
    organization_id: UUID
    platform: IntegrationPlatform
    name: Optional[str]
    public_key: Optional[str] = None
    is_active: bool
    is_default: bool = False
    created_at: datetime
    updated_at: datetime
    last_tested_at: Optional[datetime] = None
    # Note: api_key is NOT included in response for security

    @field_validator('platform', mode='before')
    @classmethod
    def convert_platform(cls, v):
        """Convert string to IntegrationPlatform enum if needed (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            # Try lowercase first (enum value)
            v_lower = v.lower()
            try:
                return IntegrationPlatform(v_lower)
            except ValueError:
                # Try to find by enum name (uppercase)
                for enum_member in IntegrationPlatform:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid IntegrationPlatform value: {v}")
        return v

    model_config = ConfigDict(from_attributes=True)


# ============================================
# DATA SOURCES SCHEMAS
# ============================================

class S3ConnectionTest(BaseModel):
    """Schema for testing S3 connection."""
    bucket_name: str
    region: str = "us-east-1"
    access_key_id: str
    secret_access_key: str
    endpoint_url: Optional[str] = None


class S3ConnectionTestResponse(BaseModel):
    """Schema for S3 connection test response."""
    success: bool
    message: str
    bucket_name: Optional[str] = None


class S3FileInfo(BaseModel):
    """Schema for S3 file information."""
    key: str
    filename: str
    size: int
    last_modified: str


class S3ListFilesResponse(BaseModel):
    """Schema for listing S3 files response."""
    files: List[S3FileInfo]
    total: int
    prefix: Optional[str] = None


class S3FolderInfo(BaseModel):
    """Schema for S3 folder information."""
    name: str
    path: str


class S3BrowseResponse(BaseModel):
    """Schema for browsing S3 folders within an organization."""
    folders: List[S3FolderInfo]
    files: List[S3FileInfo]
    current_path: str
    organization_id: str


class S3UploadResponse(BaseModel):
    """Schema for S3 upload response."""
    key: str
    bucket: str
    file_id: UUID
    message: str


# AIProvider Schemas
class AIProviderCreate(BaseModel):
    """Schema for creating an AI Provider."""
    provider: ModelProvider
    api_key: str = Field(..., min_length=1)
    name: Optional[str] = None
    is_default: Optional[bool] = Field(
        None,
        description=(
            "Mark this credential as the default for the (org, provider). "
            "If omitted and no default exists yet, this row becomes the default."
        ),
    )


class AIProviderUpdate(BaseModel):
    """Schema for updating an AI Provider."""
    api_key: Optional[str] = Field(None, min_length=1)
    name: Optional[str] = None
    is_active: Optional[bool] = None


class AIProviderResponse(BaseModel):
    """Schema for AI Provider response."""
    id: UUID
    provider: ModelProvider
    api_key: Optional[str] = None  # Will be None in response for security
    name: Optional[str]
    is_active: bool
    is_default: bool = False
    created_at: datetime
    updated_at: datetime
    last_tested_at: Optional[datetime]

    @field_validator('provider', mode='before')
    @classmethod
    def convert_provider(cls, v):
        """Convert string to ModelProvider (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return ModelProvider(v_lower)
            except ValueError:
                for enum_member in ModelProvider:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid ModelProvider value: {v}")
        return v
    
    model_config = ConfigDict(from_attributes=True)


# VoiceBundle Schemas
class VoiceBundleCreate(BaseModel):
    """Schema for creating a VoiceBundle."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    
    # Bundle type: either STT+LLM+TTS or S2S
    bundle_type: VoiceBundleType = Field(default=VoiceBundleType.STT_LLM_TTS)
    
    # STT Configuration - required for STT_LLM_TTS, optional for S2S
    stt_provider: Optional[ModelProvider] = None
    stt_model: Optional[str] = Field(None, min_length=1)
    stt_credential_id: Optional[UUID] = Field(
        None,
        description=(
            "Optional explicit AIProvider/Integration row id to use for STT. "
            "When omitted the resolver picks the default credential for stt_provider."
        ),
    )
    
    # LLM Configuration - required for STT_LLM_TTS, optional for S2S
    llm_provider: Optional[ModelProvider] = None
    llm_model: Optional[str] = Field(None, min_length=1)
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    llm_max_tokens: Optional[int] = Field(None, gt=0)
    llm_config: Optional[Dict[str, Any]] = None
    llm_credential_id: Optional[UUID] = None
    
    # TTS Configuration - required for STT_LLM_TTS, optional for S2S
    tts_provider: Optional[ModelProvider] = None
    tts_model: Optional[str] = Field(None, min_length=1)
    tts_voice: Optional[str] = None
    tts_config: Optional[Dict[str, Any]] = None
    tts_credential_id: Optional[UUID] = None
    
    # S2S Configuration - required for S2S, optional for STT_LLM_TTS
    s2s_provider: Optional[ModelProvider] = None
    s2s_model: Optional[str] = Field(None, min_length=1)
    s2s_config: Optional[Dict[str, Any]] = None
    s2s_credential_id: Optional[UUID] = None
    
    # Additional metadata
    extra_metadata: Optional[Dict[str, Any]] = None
    
    @model_validator(mode='after')
    def validate_bundle_configuration(self):
        """Validate that required fields are provided based on bundle_type."""
        if self.bundle_type == VoiceBundleType.STT_LLM_TTS:
            if not self.stt_provider or not self.stt_model:
                raise ValueError('STT provider and model are required for STT_LLM_TTS bundle type')
            if not self.llm_provider or not self.llm_model:
                raise ValueError('LLM provider and model are required for STT_LLM_TTS bundle type')
            if not self.tts_provider or not self.tts_model:
                raise ValueError('TTS provider and model are required for STT_LLM_TTS bundle type')
        elif self.bundle_type == VoiceBundleType.S2S:
            if not self.s2s_provider or not self.s2s_model:
                raise ValueError('S2S provider and model are required for S2S bundle type')
        return self


class VoiceBundleUpdate(BaseModel):
    """Schema for updating a VoiceBundle."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    
    # Bundle type
    bundle_type: Optional[VoiceBundleType] = None
    
    # STT Configuration
    stt_provider: Optional[ModelProvider] = None
    stt_model: Optional[str] = Field(None, min_length=1)
    stt_credential_id: Optional[UUID] = None
    
    # LLM Configuration
    llm_provider: Optional[ModelProvider] = None
    llm_model: Optional[str] = Field(None, min_length=1)
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    llm_max_tokens: Optional[int] = Field(None, gt=0)
    llm_config: Optional[Dict[str, Any]] = None
    llm_credential_id: Optional[UUID] = None
    
    # TTS Configuration
    tts_provider: Optional[ModelProvider] = None
    tts_model: Optional[str] = Field(None, min_length=1)
    tts_voice: Optional[str] = None
    tts_config: Optional[Dict[str, Any]] = None
    tts_credential_id: Optional[UUID] = None
    
    # S2S Configuration
    s2s_provider: Optional[ModelProvider] = None
    s2s_model: Optional[str] = Field(None, min_length=1)
    s2s_config: Optional[Dict[str, Any]] = None
    s2s_credential_id: Optional[UUID] = None
    
    # Additional metadata
    extra_metadata: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class VoiceBundleResponse(BaseModel):
    """Schema for VoiceBundle response."""
    id: UUID
    name: str
    description: Optional[str]
    
    # Bundle type - can be string from DB or enum, validator handles conversion
    bundle_type: VoiceBundleType
    
    @field_validator('bundle_type', mode='before')
    @classmethod
    def convert_bundle_type(cls, v):
        """Convert string to VoiceBundleType enum if needed."""
        if isinstance(v, str):
            try:
                return VoiceBundleType(v)
            except ValueError:
                # Try to find by value
                for enum_member in VoiceBundleType:
                    if enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid bundle_type value: {v}")
        return v
    
    @field_validator('stt_provider', 'llm_provider', 'tts_provider', 's2s_provider', mode='before')
    @classmethod
    def convert_model_provider(cls, v):
        """Convert string to ModelProvider enum if needed (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            # Try lowercase first (enum value)
            v_lower = v.lower()
            try:
                return ModelProvider(v_lower)
            except ValueError:
                # Try to find by enum name (uppercase)
                for enum_member in ModelProvider:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid ModelProvider value: {v}")
        return v
    
    # STT Configuration
    stt_provider: Optional[ModelProvider]
    stt_model: Optional[str]
    stt_credential_id: Optional[UUID] = None
    
    # LLM Configuration
    llm_provider: Optional[ModelProvider]
    llm_model: Optional[str]
    llm_temperature: Optional[float]
    llm_max_tokens: Optional[int]
    llm_config: Optional[Dict[str, Any]]
    llm_credential_id: Optional[UUID] = None
    
    # TTS Configuration
    tts_provider: Optional[ModelProvider]
    tts_model: Optional[str]
    tts_voice: Optional[str]
    tts_config: Optional[Dict[str, Any]]
    tts_credential_id: Optional[UUID] = None
    
    # S2S Configuration
    s2s_provider: Optional[ModelProvider]
    s2s_model: Optional[str]
    s2s_config: Optional[Dict[str, Any]]
    s2s_credential_id: Optional[UUID] = None
    
    # Additional metadata
    extra_metadata: Optional[Dict[str, Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)


# Test Agent Conversation Schemas
class TestAgentConversationCreate(BaseModel):
    """Schema for creating a new test agent conversation."""
    agent_id: UUID
    persona_id: UUID
    scenario_id: UUID
    voice_bundle_id: UUID
    conversation_metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(json_schema_extra={
            "example": {
                "agent_id": "123e4567-e89b-12d3-a456-426614174000",
                "persona_id": "123e4567-e89b-12d3-a456-426614174001",
                "scenario_id": "123e4567-e89b-12d3-a456-426614174002",
                "voice_bundle_id": "123e4567-e89b-12d3-a456-426614174003"
            }
        })


class TestAgentConversationUpdate(BaseModel):
    """Schema for updating a test agent conversation."""
    status: Optional[str] = None
    live_transcription: Optional[List[Dict[str, Any]]] = None
    full_transcript: Optional[str] = None
    conversation_metadata: Optional[Dict[str, Any]] = None


class TestAgentConversationResponse(BaseModel):
    """Schema for test agent conversation response."""
    id: UUID
    organization_id: UUID
    agent_id: UUID
    persona_id: UUID
    scenario_id: UUID
    voice_bundle_id: UUID
    status: str
    live_transcription: Optional[List[Dict[str, Any]]]
    conversation_audio_key: Optional[str]
    full_transcript: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: Optional[float]
    conversation_metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)


class ConversationTurn(BaseModel):
    """Schema for a single conversation turn."""
    speaker: str  # "test_agent" or "voice_agent"
    text: str
    timestamp: float  # Time in seconds from start
    audio_segment_key: Optional[str] = None  # S3 key for this segment's audio


# Conversation Evaluation Schemas
class ConversationEvaluationCreate(BaseModel):
    """Schema for creating a conversation evaluation."""
    transcription_id: UUID
    agent_id: UUID
    llm_provider: Optional[ModelProvider] = ModelProvider.OPENAI
    llm_model: Optional[str] = "gpt-4o"
    
    model_config = ConfigDict(json_schema_extra={
            "example": {
                "transcription_id": "123e4567-e89b-12d3-a456-426614174000",
                "agent_id": "123e4567-e89b-12d3-a456-426614174001",
                "llm_provider": "openai",
                "llm_model": "gpt-4o"
            }
        })


class ConversationEvaluationResponse(BaseModel):
    """Schema for conversation evaluation response."""
    id: UUID
    organization_id: UUID
    transcription_id: UUID
    agent_id: UUID
    objective_achieved: bool
    objective_achieved_reason: Optional[str]
    additional_metrics: Optional[Dict[str, Any]]
    overall_score: Optional[float]
    llm_provider: Optional[ModelProvider]
    llm_model: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# Evaluator Schemas
class EvaluatorCreate(BaseModel):
    """Schema for creating an evaluator. Either provide agent_id+persona_id+scenario_id (standard) or metric_ids/custom_prompt (custom)."""
    name: Optional[str] = None
    agent_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    scenario_id: Optional[UUID] = None
    custom_prompt: Optional[str] = None
    metric_ids: Optional[List[UUID]] = None
    llm_provider: Optional[ModelProvider] = None
    llm_model: Optional[str] = None
    tags: Optional[List[str]] = None


class EvaluatorUpdate(BaseModel):
    """Schema for updating an evaluator."""
    name: Optional[str] = None
    agent_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    scenario_id: Optional[UUID] = None
    custom_prompt: Optional[str] = None
    metric_ids: Optional[List[UUID]] = None
    llm_provider: Optional[ModelProvider] = None
    llm_model: Optional[str] = None
    tags: Optional[List[str]] = None


class EvaluatorResponse(BaseModel):
    """Schema for evaluator response."""
    id: UUID
    evaluator_id: str
    organization_id: UUID
    name: Optional[str] = None
    agent_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    scenario_id: Optional[UUID] = None
    custom_prompt: Optional[str] = None
    metric_ids: Optional[List[UUID]] = None
    llm_provider: Optional[ModelProvider] = None
    llm_model: Optional[str] = None
    tags: Optional[List[str]]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    @field_validator('llm_provider', mode='before')
    @classmethod
    def convert_llm_provider(cls, v):
        """Convert string to ModelProvider (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return ModelProvider(v_lower)
            except ValueError:
                for enum_member in ModelProvider:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid ModelProvider value: {v}")
        return v
    
    model_config = ConfigDict(from_attributes=True)


class EvaluatorBulkCreate(BaseModel):
    """Schema for creating multiple evaluators at once."""
    name: Optional[str] = None
    agent_id: UUID
    scenario_id: UUID
    persona_ids: List[UUID]
    tags: Optional[List[str]] = None


class RunEvaluatorsRequest(BaseModel):
    """Schema for running evaluators."""
    evaluator_ids: List[UUID] = Field(..., description="List of evaluator IDs to run")


class RunEvaluatorsResponse(BaseModel):
    """Schema for run evaluators response."""
    task_ids: List[str] = Field(..., description="List of Celery task IDs for tracking")
    evaluator_results: List["EvaluatorResultResponse"] = Field(default_factory=list, description="List of created evaluator results")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "agent_id": "123e4567-e89b-12d3-a456-426614174000",
                "scenario_id": "123e4567-e89b-12d3-a456-426614174002",
                "persona_ids": [
                    "123e4567-e89b-12d3-a456-426614174001",
                    "123e4567-e89b-12d3-a456-426614174003"
                ],
                "tags": ["test", "production"]
            }
        },
    )


# Metric Schemas
SelectionMode = Literal["single_choice", "multi_label"]


MetricScope = Literal["workspace", "organization"]


class MetricCreate(BaseModel):
    """Schema for creating a metric.

    Hierarchy:
    - ``parent_metric_id`` set => this is a child sub-metric. ``metric_type``
      is forced to ``boolean`` server-side; ``selection_mode`` must be None.
    - ``selection_mode`` set => this is a parent category metric.
      ``parent_metric_id`` must be None (max depth = 2).

    Scope:
    - ``scope="workspace"`` (default) stamps the metric with the active
      ``X-Workspace-Id`` so it only shows up inside that workspace.
    - ``scope="organization"`` stamps ``workspace_id=NULL`` so the metric
      is visible in every workspace of the org. Children always inherit
      their parent's scope; setting ``scope`` on a child request body is
      ignored server-side.
    """
    name: str
    description: Optional[str] = None
    # Optional illustrative example surfaced alongside ``description``
    # in the LLM judge's rubric. Today this is mainly populated on
    # child sub-labels (one example per categorization label) but
    # standalone metrics may carry it too without a schema change.
    example: Optional[str] = Field(default=None, max_length=4000)
    metric_type: MetricType = MetricType.RATING
    metric_category: MetricCategory = MetricCategory.QUALITY
    trigger: MetricTrigger = MetricTrigger.ALWAYS
    enabled: bool = True
    metric_origin: str = "custom"
    supported_surfaces: List[str] = ["agent"]
    enabled_surfaces: Optional[List[str]] = None
    custom_data_type: Optional[str] = None
    custom_config: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    capture_rationale: Optional[bool] = False
    parent_metric_id: Optional[UUID] = None
    selection_mode: Optional[SelectionMode] = None
    # Only meaningful on multi_label parents; ignored everywhere else.
    # When true, the LLM is invited during call-import evaluation to emit
    # additional candidate sub-labels beyond the user-defined children.
    allow_discovery: bool = False
    # When true, this metric is a "transcript-compare judge": at
    # call-import evaluation time the worker feeds BOTH the production
    # transcript (``call_import_rows.transcript``, CSV-supplied) and
    # the diarised transcript (``call_import_rows.diarised_transcript``,
    # worker-produced) to the LLM as a labeled pair. The parent
    # evaluation's ``transcript_source`` is ignored for these metrics.
    # Mutually exclusive with ``parent_metric_id`` / ``selection_mode``
    # — comparison metrics stay standalone so the LLM grouping logic
    # doesn't have to second-guess which prompt template to use within
    # a hierarchy. (Parent-level keyword auto-detection in the worker
    # still routes a categorisation parent through the comparison
    # prompt without setting this flag.)
    compare_transcripts: bool = False
    # When ``"organization"``, the metric is stored with
    # ``workspace_id=NULL`` so it surfaces in every workspace of the
    # caller's org. Default ``"workspace"`` preserves the historical
    # behavior of stamping the metric with the active ``X-Workspace-Id``.
    # Ignored when ``parent_metric_id`` is set (children inherit the
    # parent's scope unconditionally).
    scope: MetricScope = "workspace"

    @model_validator(mode='after')
    def validate_compare_transcripts_exclusions(self):
        """Reject body combinations that don't make sense for a
        transcript-compare judge.

        The Metric ORM column accepts the value; the validator just
        prevents the user from accidentally requesting an incoherent
        metric shape (e.g. "compare two transcripts but also live
        inside a categorisation hierarchy" — different prompt
        templates).
        """
        if not self.compare_transcripts:
            return self
        if self.parent_metric_id is not None:
            raise ValueError(
                "Transcript-compare metrics must be standalone: "
                "they cannot be a child sub-metric in this version."
            )
        if self.selection_mode is not None:
            raise ValueError(
                "Transcript-compare metrics must be standalone: "
                "they cannot own children (selection_mode must be "
                "unset) in this version."
            )
        return self

    model_config = ConfigDict(json_schema_extra={
            "example": {
                "name": "Professionalism",
                "description": "Measures the professional tone and behavior",
                "metric_type": "rating",
                "trigger": "always",
                "enabled": True
            }
        })


class MetricChildDraft(BaseModel):
    """One child sub-metric in a parent + children atomic create body."""

    name: str = Field(..., max_length=120)
    description: Optional[str] = Field(default=None, max_length=4000)
    # Optional illustrative example for this label. Surfaced alongside
    # ``description`` in the LLM judge's rubric so each label can carry
    # both its definition AND a "what does this look like?" example.
    example: Optional[str] = Field(default=None, max_length=4000)
    enabled: bool = True
    capture_rationale: Optional[bool] = True
    tags: Optional[List[str]] = None


class MetricCreateWithChildren(BaseModel):
    """One-shot create body: a parent metric + N children, atomically.

    Children are persisted as full ``Metric`` rows with
    ``parent_metric_id`` set to the new parent. ``metric_type`` on every
    child is forced to ``boolean`` server-side regardless of what's
    passed in the parent body.
    """

    name: str = Field(..., max_length=120)
    description: Optional[str] = Field(default=None, max_length=4000)
    selection_mode: SelectionMode
    metric_category: MetricCategory = MetricCategory.QUALITY
    enabled: bool = True
    supported_surfaces: List[str] = Field(default_factory=lambda: ["agent"])
    enabled_surfaces: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    # When true on a multi_label parent, allow the LLM to emit candidate
    # labels beyond the listed children at evaluation time. Validator
    # rejects allow_discovery=True on single_choice parents.
    allow_discovery: bool = False
    # Parent-level "Enable LLM Rationale" toggle. When true the LLM
    # judge emits a single rationale string at the parent level
    # (children never carry rationales in hierarchical mode), which the
    # table renders as the "<Parent> - LLM Rationale" column.
    capture_rationale: bool = False
    children: List[MetricChildDraft] = Field(
        default_factory=list,
        description="Child sub-metric labels under this parent.",
    )
    # See ``MetricCreate.scope``. Same semantics: ``"organization"``
    # creates the parent + all children with ``workspace_id=NULL`` so
    # the whole category subtree is shared across every workspace in
    # the org.
    scope: MetricScope = "workspace"


class MetricUpdate(BaseModel):
    """Schema for updating a metric."""
    name: Optional[str] = None
    description: Optional[str] = None
    # ``None`` here means "leave unchanged"; pass an empty string to
    # clear a previously stored example.
    example: Optional[str] = Field(default=None, max_length=4000)
    metric_type: Optional[MetricType] = None
    trigger: Optional[MetricTrigger] = None
    enabled: Optional[bool] = None
    metric_origin: Optional[str] = None
    supported_surfaces: Optional[List[str]] = None
    enabled_surfaces: Optional[List[str]] = None
    custom_data_type: Optional[str] = None
    custom_config: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    metric_category: Optional[MetricCategory] = None
    capture_rationale: Optional[bool] = None
    selection_mode: Optional[SelectionMode] = None
    allow_discovery: Optional[bool] = None
    # See ``MetricCreate.compare_transcripts``. ``None`` here means
    # "leave unchanged". The route layer enforces mutual exclusion
    # against the row's existing ``parent_metric_id`` /
    # ``selection_mode`` when this is set to True, because the patch
    # body alone doesn't have enough context to validate cross-state.
    compare_transcripts: Optional[bool] = None

    @model_validator(mode='after')
    def validate_compare_transcripts_exclusions(self):
        """Reject patch bodies that flip compare_transcripts on while
        ALSO trying to set a conflicting field in the same request.

        Cross-state validation against the persisted row (e.g. "the
        existing metric already has a parent") is done in the
        update route since the schema doesn't have the row in hand.
        """
        if self.compare_transcripts is not True:
            return self
        if self.selection_mode is not None:
            raise ValueError(
                "Transcript-compare metrics must be standalone: "
                "selection_mode must be cleared before enabling "
                "compare_transcripts."
            )
        return self


class MetricResponse(BaseModel):
    """Schema for metric response.

    ``children`` is populated for parent metrics (those with
    ``selection_mode`` set) and is otherwise an empty list. The list is
    built once at serialization time so callers get a single tree
    structure without follow-up requests.
    """
    id: UUID
    organization_id: UUID
    # ``None`` when the metric is org-shared (``scope == "organization"``).
    # See the ORM ``Metric.workspace_id`` docstring.
    workspace_id: Optional[UUID] = None
    # Computed convenience field so the UI doesn't have to do
    # ``workspace_id == null`` checks everywhere. Always one of
    # ``"workspace"`` or ``"organization"``.
    scope: MetricScope = "workspace"
    name: str
    description: Optional[str]
    # Optional illustrative example. Populated mainly on categorization
    # child labels but surfaced for every metric so the UI can render
    # it uniformly without branching on parent/child shape.
    example: Optional[str] = None
    metric_type: MetricType
    metric_category: MetricCategory = MetricCategory.QUALITY
    trigger: MetricTrigger
    enabled: bool
    is_default: bool
    metric_origin: str
    supported_surfaces: List[str]
    enabled_surfaces: List[str]
    custom_data_type: Optional[str]
    custom_config: Optional[Dict[str, Any]]
    tags: Optional[List[str]]
    capture_rationale: bool = False
    parent_metric_id: Optional[UUID] = None
    selection_mode: Optional[SelectionMode] = None
    allow_discovery: bool = False
    # See ``MetricCreate.compare_transcripts``. Surfaced so the UI can
    # render a "Compare transcripts" badge in the metric picker and
    # know to skip the run's transcript_source toggle for this metric.
    compare_transcripts: bool = False
    children: List["MetricResponse"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    @field_validator('metric_type', mode='before')
    @classmethod
    def convert_metric_type(cls, v):
        """Convert string to MetricType (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return MetricType(v_lower)
            except ValueError:
                for enum_member in MetricType:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid MetricType value: {v}")
        return v

    @field_validator('trigger', mode='before')
    @classmethod
    def convert_trigger(cls, v):
        """Convert string to MetricTrigger (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return MetricTrigger(v_lower)
            except ValueError:
                for enum_member in MetricTrigger:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid MetricTrigger value: {v}")
        return v

    @validator('supported_surfaces', 'enabled_surfaces', pre=True)
    def normalize_surfaces(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, (list, tuple)):
            return [str(item).lower() for item in v if item]
        return []

    @validator('metric_origin', pre=True)
    def normalize_metric_origin(cls, v):
        if v is None:
            return "custom"
        return str(v).lower()

    model_config = ConfigDict(from_attributes=True)


MetricResponse.model_rebuild()


# Evaluator Result Schemas
class EvaluatorResultCreate(BaseModel):
    """Schema for creating an evaluator result."""
    evaluator_id: UUID
    agent_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    scenario_id: Optional[UUID] = None
    name: Optional[str] = None
    duration_seconds: Optional[float] = None
    audio_s3_key: Optional[str] = None


class EvaluatorResultCreateManual(BaseModel):
    """Schema for manually creating an evaluator result from existing audio file."""
    evaluator_id: UUID
    audio_s3_key: str
    duration_seconds: Optional[float] = None


class EvaluatorResultUpdate(BaseModel):
    """Schema for updating an evaluator result."""
    status: Optional[EvaluatorResultStatus] = None
    transcription: Optional[str] = None
    metric_scores: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None


class EvaluatorResultResponse(BaseModel):
    """Schema for evaluator result response."""
    id: UUID
    result_id: str
    organization_id: UUID
    evaluator_id: Optional[UUID] = None  # Optional for playground test results
    agent_id: Optional[UUID] = None  # Nullable for custom evaluators
    persona_id: Optional[UUID] = None  # Optional for playground test results
    scenario_id: Optional[UUID] = None  # Optional for playground test results
    name: Optional[str] = None  # Optional for playground test results
    timestamp: datetime
    duration_seconds: Optional[float]
    status: EvaluatorResultStatus
    audio_s3_key: Optional[str]
    transcription: Optional[str]
    speaker_segments: Optional[List[Dict[str, Any]]] = None  # [{"speaker": "Speaker 1", "text": "...", "start": 0.0, "end": 5.2}]
    metric_scores: Optional[Dict[str, Any]]
    celery_task_id: Optional[str]
    error_message: Optional[str]
    
    # Call tracking fields (for voice AI integrations)
    call_event: Optional[str] = None
    provider_call_id: Optional[str] = None
    provider_platform: Optional[str] = None
    call_data: Optional[Dict[str, Any]] = None  # Full call details from provider
    
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    
    # Related entities (optional, populated when requested)
    agent: Optional[AgentResponse] = None
    persona: Optional[PersonaResponse] = None
    scenario: Optional[ScenarioResponse] = None
    evaluator: Optional[EvaluatorResponse] = None

    @field_validator('status', mode='before')
    @classmethod
    def convert_status(cls, v):
        """Convert string to EvaluatorResultStatus (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return EvaluatorResultStatus(v_lower)
            except ValueError:
                for enum_member in EvaluatorResultStatus:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid EvaluatorResultStatus value: {v}")
        return v
    
    model_config = ConfigDict(from_attributes=True)


# ============================================
# ALERTING SCHEMAS
# ============================================

class AlertCreate(BaseModel):
    """Schema for creating an alert."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    
    # Metric condition
    metric_type: AlertMetricType = AlertMetricType.NUMBER_OF_CALLS
    aggregation: AlertAggregation = AlertAggregation.SUM
    operator: AlertOperator = AlertOperator.GREATER_THAN
    threshold_value: float = Field(..., description="Threshold value for the alert")
    time_window_minutes: int = Field(default=60, ge=1, description="Time window in minutes for aggregation")
    
    # Agent selection (null means all agents)
    agent_ids: Optional[List[UUID]] = None
    
    # Notification settings
    notify_frequency: AlertNotifyFrequency = AlertNotifyFrequency.IMMEDIATE
    notify_emails: Optional[List[str]] = Field(default=None, description="List of email addresses to notify")
    notify_webhooks: Optional[List[str]] = Field(default=None, description="List of webhook URLs (Slack, etc.)")
    
    model_config = ConfigDict(json_schema_extra={
            "example": {
                "name": "High Call Volume Alert",
                "description": "Alert when call volume exceeds threshold",
                "metric_type": "number_of_calls",
                "aggregation": "sum",
                "operator": ">",
                "threshold_value": 100,
                "time_window_minutes": 60,
                "agent_ids": None,
                "notify_frequency": "immediate",
                "notify_emails": ["admin@example.com"],
                "notify_webhooks": ["https://hooks.slack.com/services/xxx"]
            }
        })


class AlertUpdate(BaseModel):
    """Schema for updating an alert."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    
    # Metric condition
    metric_type: Optional[AlertMetricType] = None
    aggregation: Optional[AlertAggregation] = None
    operator: Optional[AlertOperator] = None
    threshold_value: Optional[float] = None
    time_window_minutes: Optional[int] = Field(default=None, ge=1)
    
    # Agent selection
    agent_ids: Optional[List[UUID]] = None
    
    # Notification settings
    notify_frequency: Optional[AlertNotifyFrequency] = None
    notify_emails: Optional[List[str]] = None
    notify_webhooks: Optional[List[str]] = None
    
    # Status
    status: Optional[AlertStatus] = None


class AlertResponse(BaseModel):
    """Schema for alert response."""
    id: UUID
    organization_id: UUID
    name: str
    description: Optional[str]
    
    # Metric condition
    metric_type: AlertMetricType
    aggregation: AlertAggregation
    operator: AlertOperator
    threshold_value: float
    time_window_minutes: int
    
    # Agent selection
    agent_ids: Optional[List[UUID]]
    
    # Notification settings
    notify_frequency: AlertNotifyFrequency
    notify_emails: Optional[List[str]]
    notify_webhooks: Optional[List[str]]
    
    # Status
    status: AlertStatus
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    @field_validator('metric_type', mode='before')
    @classmethod
    def convert_metric_type(cls, v):
        """Convert string to AlertMetricType."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return AlertMetricType(v_lower)
            except ValueError:
                for enum_member in AlertMetricType:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid AlertMetricType value: {v}")
        return v

    @field_validator('aggregation', mode='before')
    @classmethod
    def convert_aggregation(cls, v):
        """Convert string to AlertAggregation."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return AlertAggregation(v_lower)
            except ValueError:
                for enum_member in AlertAggregation:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid AlertAggregation value: {v}")
        return v

    @field_validator('operator', mode='before')
    @classmethod
    def convert_operator(cls, v):
        """Convert string to AlertOperator."""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return AlertOperator(v)
            except ValueError:
                for enum_member in AlertOperator:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid AlertOperator value: {v}")
        return v

    @field_validator('notify_frequency', mode='before')
    @classmethod
    def convert_notify_frequency(cls, v):
        """Convert string to AlertNotifyFrequency."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return AlertNotifyFrequency(v_lower)
            except ValueError:
                for enum_member in AlertNotifyFrequency:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid AlertNotifyFrequency value: {v}")
        return v

    @field_validator('status', mode='before')
    @classmethod
    def convert_status(cls, v):
        """Convert string to AlertStatus."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return AlertStatus(v_lower)
            except ValueError:
                for enum_member in AlertStatus:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid AlertStatus value: {v}")
        return v
    
    model_config = ConfigDict(from_attributes=True)


class AlertHistoryResponse(BaseModel):
    """Schema for alert history response."""
    id: UUID
    organization_id: UUID
    alert_id: UUID
    
    # Trigger information
    triggered_at: datetime
    triggered_value: float
    threshold_value: float
    
    # Status
    status: AlertHistoryStatus
    
    # Notification tracking
    notified_at: Optional[datetime]
    notification_details: Optional[Dict[str, Any]]
    
    # Resolution
    acknowledged_at: Optional[datetime]
    acknowledged_by: Optional[str]
    resolved_at: Optional[datetime]
    resolved_by: Optional[str]
    resolution_notes: Optional[str]
    
    # Additional context
    context_data: Optional[Dict[str, Any]]
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    
    # Related alert info (optional)
    alert: Optional[AlertResponse] = None

    @field_validator('status', mode='before')
    @classmethod
    def convert_status(cls, v):
        """Convert string to AlertHistoryStatus."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return AlertHistoryStatus(v_lower)
            except ValueError:
                for enum_member in AlertHistoryStatus:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid AlertHistoryStatus value: {v}")
        return v
    
    model_config = ConfigDict(from_attributes=True)


class AlertHistoryUpdate(BaseModel):
    """Schema for updating alert history (acknowledge/resolve)."""
    status: Optional[AlertHistoryStatus] = None
    acknowledged_by: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None


# ============================================
# CRON JOB SCHEMAS
# ============================================

class CronJobCreate(BaseModel):
    """Schema for creating a cron job."""
    name: str = Field(..., min_length=1, max_length=255)
    cron_expression: str = Field(..., min_length=1, max_length=100, description="Cron expression (e.g., '0 9 * * 1-5')")
    timezone: str = Field(default="UTC", max_length=100, description="Timezone for the cron schedule")
    max_runs: int = Field(default=10, ge=1, le=1000, description="Maximum number of times to run")
    evaluator_ids: List[UUID] = Field(..., min_length=1, description="List of evaluator IDs to trigger")
    
    model_config = ConfigDict(json_schema_extra={
            "example": {
                "name": "Daily Evaluation Run",
                "cron_expression": "0 9 * * 1-5",
                "timezone": "America/New_York",
                "max_runs": 100,
                "evaluator_ids": ["123e4567-e89b-12d3-a456-426614174000"]
            }
        })


class CronJobUpdate(BaseModel):
    """Schema for updating a cron job."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    cron_expression: Optional[str] = Field(None, min_length=1, max_length=100)
    timezone: Optional[str] = Field(None, max_length=100)
    max_runs: Optional[int] = Field(None, ge=1, le=1000)
    evaluator_ids: Optional[List[UUID]] = None
    status: Optional[CronJobStatus] = None


class CronJobResponse(BaseModel):
    """Schema for cron job response."""
    id: UUID
    organization_id: UUID
    name: str
    cron_expression: str
    timezone: str
    max_runs: int
    current_runs: int
    evaluator_ids: List[UUID]
    status: CronJobStatus
    next_run_at: Optional[datetime]
    last_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    @field_validator('status', mode='before')
    @classmethod
    def convert_status(cls, v):
        """Convert string to CronJobStatus."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return CronJobStatus(v_lower)
            except ValueError:
                for enum_member in CronJobStatus:
                    if enum_member.value.lower() == v_lower:
                        return enum_member
                raise ValueError(f"Invalid status: {v}")
        return v

    @field_validator('evaluator_ids', mode='before')
    @classmethod
    def convert_evaluator_ids(cls, v):
        """Convert evaluator_ids from JSON to list of UUIDs."""
        if v is None:
            return []
        if isinstance(v, list):
            return [UUID(str(id)) if not isinstance(id, UUID) else id for id in v]
        return v

    model_config = ConfigDict(from_attributes=True)


# ============================================
# PROMPT PARTIAL SCHEMAS
# ============================================

class PromptPartialCreate(BaseModel):
    """Schema for creating a prompt partial."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    content: str = Field(..., min_length=1)
    tags: Optional[List[str]] = None


class PromptPartialUpdate(BaseModel):
    """Schema for updating a prompt partial."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    content: Optional[str] = Field(None, min_length=1)
    tags: Optional[List[str]] = None
    change_summary: Optional[str] = None


class PromptPartialVersionResponse(BaseModel):
    """Schema for prompt partial version response."""
    id: UUID
    prompt_partial_id: UUID
    version: int
    content: str
    change_summary: Optional[str]
    created_at: datetime
    created_by: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class PromptPartialResponse(BaseModel):
    """Schema for prompt partial response."""
    id: UUID
    organization_id: UUID
    name: str
    description: Optional[str]
    content: str
    tags: Optional[List[str]]
    current_version: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class PromptPartialDetailResponse(PromptPartialResponse):
    """Schema for prompt partial detail with versions."""
    versions: List[PromptPartialVersionResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ============================================
# TELEPHONY SCHEMAS (provider-agnostic)
# ============================================


class TelephonyIntegrationCreate(BaseModel):
    """Schema for creating a telephony provider integration."""

    provider: str = "plivo"
    name: Optional[str] = None
    auth_id: str
    auth_token: str
    verify_app_uuid: Optional[str] = None
    voice_app_id: Optional[str] = None
    sip_domain: Optional[str] = None
    masking_config: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = Field(
        None,
        description=(
            "Mark this credential as the default for the (org, provider). "
            "If omitted and no default exists yet, this row becomes the default."
        ),
    )


class TelephonyIntegrationUpdate(BaseModel):
    """Schema for partial updates to a telephony provider integration."""

    id: Optional[UUID] = None
    provider: Optional[str] = None
    name: Optional[str] = None
    auth_id: Optional[str] = None
    auth_token: Optional[str] = None
    verify_app_uuid: Optional[str] = None
    voice_app_id: Optional[str] = None
    sip_domain: Optional[str] = None
    masking_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class TelephonyIntegrationResponse(BaseModel):
    """Safe response model for telephony integration without secrets."""

    id: UUID
    organization_id: UUID
    provider: str
    name: Optional[str] = None
    verify_app_uuid: Optional[str]
    voice_app_id: Optional[str]
    sip_domain: Optional[str]
    masking_config: Optional[Dict[str, Any]]
    is_active: bool
    is_default: bool = False
    last_tested_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TelephonyPhoneNumberResponse(BaseModel):
    """Telephony phone number inventory response schema."""

    id: UUID
    phone_number: str
    country_iso2: Optional[str]
    region: Optional[str]
    number_type: Optional[str]
    capabilities: Optional[Dict[str, Any]]
    is_masking_pool: bool
    agent_id: Optional[UUID]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TelephonyVerifyStartRequest(BaseModel):
    """Request schema for starting voice OTP verification."""

    phone_number: str
    provider: str = "plivo"


class TelephonyVerifyStartResponse(BaseModel):
    """Response schema for started voice OTP verification."""

    session_id: UUID
    provider_session_uuid: str
    status: str
    message: str


class TelephonyVerifyCheckRequest(BaseModel):
    """Request schema for checking a submitted OTP code."""

    session_id: UUID
    otp_code: str
    provider: str = "plivo"


class TelephonyVerifyCheckResponse(BaseModel):
    """Response schema for OTP check status."""

    verified: bool
    status: str
    message: str


class TelephonyMaskingSessionCreate(BaseModel):
    """Request schema for creating a number masking session."""

    party_a_number: str
    party_b_number: str
    provider: str = "plivo"
    expires_in_minutes: Optional[int] = 60
    metadata: Optional[Dict[str, Any]] = None
    provider: str = "plivo"


class TelephonyMaskingSessionResponse(BaseModel):
    """Response schema for masking sessions."""

    id: UUID
    masked_number: str
    party_a_number: str
    party_b_number: str
    status: str
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class TelephonyOutboundCallRequest(BaseModel):
    """Request schema for outbound call initiation."""

    from_number: str
    to_number: str
    answer_url: Optional[str] = None
    agent_id: Optional[UUID] = None


class TelephonyOutboundCallResponse(BaseModel):
    """Response schema for outbound call initiation."""

    provider_request_uuid: str
    call_status: str
    from_number: str
    to_number: str
    message: str


# --- Call Import Schemas ---

class CallImportRowResponse(BaseModel):
    """Single row within a call-import batch."""

    id: UUID
    row_index: int
    # Renamed from ``external_call_id`` (DB column renamed in migration
    # ``034_call_import_schemas``). Same data, same uniqueness rules.
    conversation_id: str
    recording_url: Optional[str] = None
    recording_date: Optional[date] = None
    # Production transcript: the value supplied via the CSV upload.
    transcript: Optional[str] = None
    transcript_source: Optional[str] = None
    transcript_provider: Optional[str] = None
    transcript_model: Optional[str] = None
    transcript_status: Optional[str] = None
    transcript_error: Optional[str] = None
    transcribed_at: Optional[datetime] = None
    # Diarised transcript: produced by the post-hoc diarisation
    # worker. Independent of ``transcript`` so manual diarisation
    # never overwrites the CSV-supplied production value.
    diarised_transcript: Optional[str] = None
    diarised_transcript_provider: Optional[str] = None
    diarised_transcript_model: Optional[str] = None
    diarised_transcript_status: Optional[str] = None
    diarised_transcript_error: Optional[str] = None
    diarised_at: Optional[datetime] = None
    # LLM that turned the STT plain-text output into structured
    # ``diarised_segments``. Surfaced in the row detail panel so
    # reviewers can see "Diarised by openai/gpt-4o-mini" next to
    # the swap toggle. NULL on rows diarised by the legacy pyannote
    # worker (which has been removed).
    diarised_llm_provider: Optional[str] = None
    diarised_llm_model: Optional[str] = None
    # The exact prompt the LLM diariser ran with. Persisted so a
    # reviewer can copy it back into the modal and reproduce the
    # turn layout against a different STT pass.
    diarised_prompt: Optional[str] = None
    # Structured speaker turns produced by the diarisation worker. Each
    # entry is `{ "speaker": "agent"|"user"|"speaker_N", "text": str,
    # "start": float, "end": float, "raw_speaker": "Speaker 1" }`. The
    # plain ``diarised_transcript`` field above is a `<speaker>: <text>`
    # rendering of this list with ``diarised_speaker_swap`` applied.
    diarised_segments: Optional[List[Dict[str, Any]]] = None
    # When True the agent <-> user mapping in ``diarised_segments`` is
    # inverted at render / export time. The worker writes the canonical
    # mapping using the "first speaker is the agent" heuristic; the swap
    # toggle lets reviewers correct that without re-running diarisation.
    diarised_speaker_swap: bool = False
    status: CallImportRowStatus
    recording_s3_key: Optional[str] = None
    recording_content_type: Optional[str] = None
    recording_size_bytes: Optional[int] = None
    error_message: Optional[str] = None
    attempts: int
    raw_columns: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Call Import Schema (Input Parameter definitions) ---


class CallImportSchemaParameterBase(BaseModel):
    """A single typed parameter inside a Call Import schema.

    Used both in request bodies (create / update) and as the building
    block of :class:`CallImportSchemaParameterResponse`. Names are
    case-insensitive unique within their parent schema.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Parameter name as it appears in the schema editor and the "
            "upload mapping table. Must be unique within the schema "
            "(case-insensitive)."
        ),
    )
    type: CallImportParameterType = Field(
        ...,
        description=(
            "Parameter type. One of conversation_id / recording_url / "
            "recording_date / transcript / text / number / boolean / "
            "datetime / url. Exactly one parameter each of type "
            "'conversation_id' and 'recording_date' is required."
        ),
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2048,
        description="Free-text help shown next to the parameter in the mapping UI.",
    )
    is_required: bool = Field(
        default=False,
        description=(
            "When True, the parameter must be mapped to a CSV column on "
            "every upload. The ``conversation_id`` parameter is always "
            "required and is force-set to True by the server."
        ),
    )


class CallImportSchemaParameterCreate(CallImportSchemaParameterBase):
    """Create payload for a single parameter (inside a schema CRUD body)."""


class CallImportSchemaParameterResponse(CallImportSchemaParameterBase):
    """Response shape including the persisted id + ordering."""

    id: UUID
    ordering: int

    model_config = ConfigDict(from_attributes=True)


def _validate_schema_parameters(
    parameters: List[CallImportSchemaParameterBase],
) -> List[CallImportSchemaParameterBase]:
    """Apply the cross-parameter invariants shared by create + update."""

    if not parameters:
        raise ValueError("Schema must define at least one parameter.")

    seen_names: set[str] = set()
    conv_count = 0
    recording_date_count = 0
    rec_url_count = 0
    transcript_count = 0
    for param in parameters:
        norm = param.name.strip().lower()
        if not norm:
            raise ValueError("Parameter name must be non-empty.")
        if norm in seen_names:
            raise ValueError(
                f"Duplicate parameter name '{param.name}' "
                "(names must be unique within a schema)."
            )
        seen_names.add(norm)
        if param.type == CallImportParameterType.CONVERSATION_ID:
            conv_count += 1
        elif param.type == CallImportParameterType.RECORDING_DATE:
            recording_date_count += 1
        elif param.type == CallImportParameterType.RECORDING_URL:
            rec_url_count += 1
        elif param.type == CallImportParameterType.TRANSCRIPT:
            transcript_count += 1

    if conv_count != 1:
        raise ValueError(
            "Schema must contain exactly one parameter of type "
            "'conversation_id'."
        )
    if recording_date_count != 1:
        raise ValueError(
            "Schema must contain exactly one parameter of type "
            "'recording_date'."
        )
    if rec_url_count > 1:
        raise ValueError(
            "Schema may contain at most one parameter of type 'recording_url'."
        )
    if transcript_count > 1:
        raise ValueError(
            "Schema may contain at most one parameter of type 'transcript'."
        )
    return parameters


class CallImportSchemaCreate(BaseModel):
    """Create body for a new call-import schema."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2048)
    parameters: List[CallImportSchemaParameterCreate] = Field(
        ...,
        description=(
            "Ordered list of parameters. Order is preserved; the server "
            "stamps ``ordering`` from the list index."
        ),
    )

    @model_validator(mode="after")
    def _check_parameters(self):
        _validate_schema_parameters(list(self.parameters))
        return self


class CallImportSchemaUpdate(BaseModel):
    """Patch body for an existing schema (full parameter replacement)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2048)
    parameters: Optional[List[CallImportSchemaParameterCreate]] = Field(
        default=None,
        description=(
            "If provided, REPLACES the full set of parameters on the "
            "schema. Omit to leave parameters untouched."
        ),
    )

    @model_validator(mode="after")
    def _check_parameters(self):
        if self.parameters is not None:
            _validate_schema_parameters(list(self.parameters))
        return self


class CallImportSchemaResponse(BaseModel):
    """Read response for a single schema."""

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    description: Optional[str] = None
    parameters: List[CallImportSchemaParameterResponse] = Field(default_factory=list)
    # How many CallImport batches reference this schema. Populated by the
    # router when listing; defaults to 0 on detail responses where the
    # caller doesn't need it.
    usage_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CallImportSchemaListResponse(BaseModel):
    """Paginated list of schemas."""

    items: List[CallImportSchemaResponse] = Field(default_factory=list)
    total: int


class CallImportTagResponse(BaseModel):
    """Tag attached to call import batches."""

    id: UUID
    name: str
    color: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CallImportTagCreate(BaseModel):
    """Create a new call-import tag for the organization."""

    name: str = Field(..., min_length=1, max_length=255)
    color: Optional[str] = Field(None, max_length=32)


class CallImportTagUpdate(BaseModel):
    """Partial update for a call-import tag."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    color: Optional[str] = Field(None, max_length=32)


class CallImportPreviewSheet(BaseModel):
    """One worksheet (or one CSV file synthesized as a single sheet)."""

    name: str = Field(..., description="Sheet name for xlsx; filename for csv.")
    headers: List[str] = Field(
        default_factory=list,
        description="Column headers from the first non-empty row.",
    )
    row_count: int = Field(
        ...,
        description="Approximate count of data rows (excluding the header row).",
    )


class CallImportResponse(BaseModel):
    """Summary of a call-import batch."""

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    # Provider is optional in the new staged flow (only resolved at the
    # IMPORT stage). Stays populated for all post-import batches.
    provider: Optional[str] = None
    telephony_integration_id: Optional[UUID] = None
    original_filename: Optional[str] = None
    sheet_name: Optional[str] = None
    dataset: Optional[str] = None
    tags: List[CallImportTagResponse] = Field(default_factory=list)
    # New schema-driven mapping. Empty on legacy batches; pre-schema
    # batches keep their values in ``column_mapping`` / ``extra_columns``
    # / ``custom_column_mapping`` below for backwards-compatibility.
    schema_id: Optional[UUID] = None
    parameter_mapping: Dict[str, str] = Field(default_factory=dict)
    column_mapping: Dict[str, Optional[str]] = Field(default_factory=dict)
    extra_columns: List[str] = Field(default_factory=list)
    custom_column_mapping: Dict[str, str] = Field(default_factory=dict)
    # Persisted "drop these columns" decision captured at MAP time.
    # Empty for legacy one-shot uploads where the value was ephemeral.
    skipped_columns: List[str] = Field(default_factory=list)
    # Source-file staging fields populated at UPLOAD time. ``None`` on
    # legacy batches imported via the one-shot ``POST /upload`` endpoint.
    source_s3_key: Optional[str] = None
    source_format: Optional[str] = None
    source_size_bytes: Optional[int] = None
    source_content_type: Optional[str] = None
    # Snapshot of the file's sheets + headers captured at UPLOAD time
    # so the MAP UI can render without re-fetching the file from S3.
    available_sheets: Optional[List[CallImportPreviewSheet]] = None
    total_rows: int
    completed_rows: int
    failed_rows: int
    status: CallImportStatus
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CallImportDetailResponse(CallImportResponse):
    """A call-import batch with its rows expanded.

    ``filtered_total_rows`` is only set when the caller passed a ``q``
    search term — it lets the UI paginate against the filtered subset
    while still showing the unfiltered ``total_rows`` in the header.

    The ``diarised_*_rows`` counters aggregate
    ``CallImportRow.diarised_transcript_status`` across the batch so the
    UI can render a transcribe-and-diarise progress bar without paging
    through every row. Rows that have never been touched by the
    transcribe/diarise worker (``status='idle'``) are NOT counted here —
    callers compute the idle bucket as
    ``total_rows - (pending + running + completed + failed)``.
    """

    rows: List[CallImportRowResponse] = Field(default_factory=list)
    filtered_total_rows: Optional[int] = None
    diarised_pending_rows: int = 0
    diarised_running_rows: int = 0
    diarised_completed_rows: int = 0
    diarised_failed_rows: int = 0


class CallImportListResponse(BaseModel):
    """Paginated list of call-import batches."""

    items: List[CallImportResponse]
    total: int
    page: int
    page_size: int


class CallImportUploadResponse(BaseModel):
    """Response returned right after a CSV is accepted."""

    id: UUID
    total_rows: int
    status: CallImportStatus
    dataset: Optional[str] = None
    tags: List[CallImportTagResponse] = Field(default_factory=list)
    message: str


class CallImportPreviewResponse(BaseModel):
    """Sheets/headers extracted from an uploaded CSV or Excel workbook.

    The frontend uses this to drive the column-mapping UI without doing
    its own parsing — keeps client and server in lockstep on quoted
    fields, encodings, and Excel cell coercion.
    """

    format: str = Field(..., description="One of 'csv' or 'xlsx'.")
    sheets: List[CallImportPreviewSheet] = Field(default_factory=list)


class CallImportUpdate(BaseModel):
    """Partial update of a call-import batch."""

    dataset: Optional[str] = Field(
        None,
        description=(
            "Free-text dataset label. Pass an empty string to clear the dataset."
        ),
    )
    tag_ids: Optional[List[UUID]] = Field(
        None,
        description=(
            "Replace the full set of tag assignments. Pass an empty list to clear all tags."
        ),
    )
    schema_id: Optional[UUID] = Field(
        None,
        description=(
            "Reassign the Input Parameter schema. Only honoured while the "
            "batch is in ``uploaded`` or ``mapped`` state; once the batch "
            "has rows it's locked to its original schema."
        ),
    )


class CallImportMappingUpdate(BaseModel):
    """Mapping payload for the MAP stage (``PATCH /call-imports/{id}/mapping``).

    Idempotent: callers can submit this multiple times against an
    ``uploaded`` or ``mapped`` batch. Validation re-runs against the
    persisted ``available_sheets`` snapshot every time so the user can
    correct mistakes without re-uploading the file.
    """

    schema_id: UUID = Field(
        ...,
        description=(
            "Reusable Input Parameter schema this batch is mapped against. "
            "Must belong to the active workspace."
        ),
    )
    sheet_name: Optional[str] = Field(
        None,
        description=(
            "Worksheet to use when the staged source file is an Excel "
            "workbook. REQUIRED for xlsx; ignored / rejected for CSV."
        ),
    )
    parameter_mapping: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "``{schema_parameter_name: source_header}`` map covering every "
            "required schema parameter."
        ),
    )
    skipped_columns: List[str] = Field(
        default_factory=list,
        description=(
            "Source headers the uploader has explicitly skipped. Every "
            "source header must be either mapped or appear here."
        ),
    )


class CallImportStartRequest(BaseModel):
    """Provider + credential picker for the IMPORT stage."""

    provider: str = Field(
        ...,
        description=(
            "Telephony provider key. Must match the "
            "``telephony_integration_id``'s provider."
        ),
    )
    telephony_integration_id: UUID = Field(
        ...,
        description=(
            "Specific TelephonyIntegration credential row to use when "
            "downloading recordings for this batch."
        ),
    )


# --- Call Import Evaluation Schemas ---


class CallImportEvaluationLLMOverride(BaseModel):
    """Per-metric LLM override used on top of the run-level default.

    Any field left ``None`` falls back to the run-level value (which
    itself falls back to the historical OpenAI/gpt-4o default). This
    lets users pick a specific provider/model for a single metric (e.g.
    a stronger Anthropic model for a tricky qualitative metric) without
    re-typing the rest of the metrics in the run.
    """

    provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Override LLM provider key, e.g. 'openai' or 'anthropic'.",
    )
    model: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Override LLM model name, e.g. 'gpt-4o' or 'claude-3-opus'.",
    )
    credential_id: Optional[UUID] = Field(
        default=None,
        description="Optional AIProvider id when the org has multiple credentials.",
    )


CallImportEvaluationTranscriptSource = Literal["production", "diarised"]


class CallImportEvaluationCreate(BaseModel):
    """Request body for triggering an evaluation over a call-import batch."""

    metric_ids: List[UUID] = Field(
        ...,
        min_length=1,
        description="Org Metric ids to score every completed row against.",
    )
    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description=(
            "Optional human-readable label for the run. Shown in the UI "
            "instead of the UUID prefix."
        ),
    )
    transcript_sources: List[CallImportEvaluationTranscriptSource] = Field(
        default_factory=lambda: ["diarised"],
        min_length=1,
        max_length=1,
        description=(
            "Which transcript to score against. Only ``diarised`` is "
            "supported — every evaluation run scores the diarised "
            "transcript. Pass ``['diarised']`` explicitly or omit the "
            "field to take the default; any other value (including the "
            "legacy ``'production'`` source) is rejected with a 400."
        ),
    )

    @field_validator("transcript_sources")
    @classmethod
    def _validate_transcript_sources(
        cls, value: List[str]
    ) -> List["CallImportEvaluationTranscriptSource"]:
        # The Field min_length/max_length constraints catch empty +
        # over-long payloads; this validator's job is to reject any
        # non-diarised source value and normalize the result to
        # ``['diarised']`` for downstream code.
        invalid = [src for src in value if src != "diarised"]
        if invalid:
            raise ValueError(
                "Only the 'diarised' transcript source is supported "
                "(received: "
                + ", ".join(repr(src) for src in invalid)
                + "). Remove 'production' from transcript_sources or "
                "omit the field to use the default."
            )
        return ["diarised"]
    # --- Run-level LLM config ---
    llm_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "Run-level LLM provider key (e.g. 'openai', 'anthropic'). NULL "
            "preserves the historical OpenAI/gpt-4o default."
        ),
    )
    llm_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Run-level LLM model name. Required when llm_provider is set.",
    )
    llm_credential_id: Optional[UUID] = Field(
        default=None,
        description="Optional AIProvider row to pin for the run-level LLM.",
    )
    metric_llm_overrides: Optional[
        Dict[str, CallImportEvaluationLLMOverride]
    ] = Field(
        default=None,
        description=(
            "Optional per-metric LLM overrides keyed by metric UUID. Each "
            "entry overrides the run-level default for that metric only."
        ),
    )
    # --- Auto-transcribe / diarization hook ---
    # Every diarised run auto-diarises rows that don't already have a
    # diarised transcript. The flag stays on the schema so legacy API
    # callers don't 400 immediately, but the route now requires
    # ``stt_provider`` + ``stt_model`` on every run regardless of this
    # value.
    auto_transcribe: bool = Field(
        default=True,
        description=(
            "Auto-diarise rows missing a diarised transcript before "
            "evaluation. Defaults to true and is effectively required: "
            "``stt_provider`` + ``stt_model`` are mandatory on every "
            "evaluation run."
        ),
    )
    transcribe_overwrite: bool = Field(
        default=False,
        description=(
            "When auto_transcribe is on, overwrite existing transcripts "
            "instead of skipping rows that already have one."
        ),
    )
    transcribe_mode: Literal["stt_llm", "llm_only"] = Field(
        default="stt_llm",
        description=(
            "Diarisation pipeline shape for the auto-transcribe step. "
            "'stt_llm' (default) runs STT then an LLM diariser over the "
            "resulting text — ``stt_provider`` + ``stt_model`` must be "
            "provided. 'llm_only' skips STT and feeds the audio "
            "directly to the multimodal ``diarization_llm_*`` model "
            "along with ``diarization_prompt``; STT fields must be "
            "omitted in that case."
        ),
    )
    stt_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "STT provider key, e.g. 'deepgram', 'openai'. Required when "
            "``transcribe_mode='stt_llm'`` (the default); must be omitted "
            "when ``transcribe_mode='llm_only'``."
        ),
    )
    stt_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description=(
            "STT model name, e.g. 'nova-2', 'whisper-1'. Same presence "
            "rules as ``stt_provider``."
        ),
    )
    stt_credential_id: Optional[UUID] = Field(
        default=None,
        description="Optional AIProvider/Integration row to pin for STT.",
    )
    stt_language: Optional[str] = Field(
        default=None,
        max_length=20,
        description="ISO language hint for the STT provider, e.g. 'en'.",
    )
    # --- LLM diariser config (mirror of CallImportTranscribeRequest) ---
    # Auto-diarised eval rows go through the same LLM-based diariser as
    # the standalone Transcribe modal — the run remembers the provider /
    # model / prompt so a follow-up retry can reproduce them without
    # having to re-prompt the user.
    diarization_llm_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "LLM provider for diarising STT output into agent/user "
            "turns. Required when ``auto_transcribe`` is set (the worker "
            "no longer falls back to pyannote)."
        ),
    )
    diarization_llm_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description="LLM model for the diariser.",
    )
    diarization_llm_credential_id: Optional[UUID] = Field(
        default=None,
        description="Optional AIProvider row to pin for the diariser LLM.",
    )
    diarization_prompt: Optional[str] = Field(
        default=None,
        max_length=10_000,
        description=(
            "Custom system prompt for the diariser LLM; falls back to "
            "the canonical default when blank."
        ),
    )
    discover_new_metrics: bool = Field(
        default=False,
        description=(
            "When true, the LLM is invited to propose net-new top-level "
            "metrics (boolean / rating / category) observed in the "
            "transcripts in addition to scoring the selected metrics. "
            "Candidates surface in the Discovered metrics panel on the "
            "evaluation detail Flow tab and can be promoted into real "
            "standalone Metric rows. Defaults to false so existing "
            "callers retain previous behaviour."
        ),
    )


class CallImportEvaluationUpdate(BaseModel):
    """Patch body for editing a previously-created evaluation run."""

    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="New name for the evaluation. Empty string clears it.",
    )


class CallImportEvaluationBulkDelete(BaseModel):
    """Request body for deleting multiple evaluation runs in one call."""

    evaluation_ids: List[UUID] = Field(
        ...,
        min_length=1,
        description="Evaluation ids to delete.",
    )


class CallImportEvaluationRetryRequest(BaseModel):
    """Body for retrying a subset (or all failed rows) of an evaluation run.

    ``eval_row_ids`` is optional: when ``None`` the retry applies to
    every row in the run that is currently in the ``failed`` state. The
    selection always intersects with the run's actual rows, so unknown
    ids are silently skipped (and surfaced in the response's
    ``skipped`` list with reason ``unknown``).

    The optional ``llm_*`` / ``metric_llm_overrides`` / ``stt_*`` fields
    let the caller swap out the LLM or STT configuration that the
    failed rows were originally evaluated with. When a field is left
    ``None`` the run's existing value is preserved. When a field is
    set, it is persisted onto the run (so a follow-up retry sees the
    new value as the default) and used by the worker on the next
    pass. Providing only one half of provider+model is rejected so
    the worker never ends up with a half-configured run.
    """

    eval_row_ids: Optional[List[UUID]] = Field(
        default=None,
        description=(
            "Restrict the retry to a specific subset of evaluation rows. "
            "When omitted, every row with status='failed' in this run is "
            "re-enqueued."
        ),
    )

    # --- Metric-subset re-run ---
    # When ``metric_ids`` is set, the retry recomputes ONLY those
    # metrics instead of the whole row, and the new scores are merged
    # into the existing ``metric_scores`` JSON (other metrics'
    # previously-computed values are preserved). This is the path
    # taken by the "Re-run metrics" UI in CallImportEvaluationDetail.
    metric_ids: Optional[List[UUID]] = Field(
        default=None,
        description=(
            "Restrict the retry to a specific subset of metrics. When "
            "set, the worker recomputes only these metrics and merges "
            "the new scores into the row's existing metric_scores "
            "(other metrics' previous values are preserved). When "
            "omitted, the row is fully re-scored as before. Every id "
            "must already be present in the run's selected_metric_ids."
        ),
    )
    include_completed: bool = Field(
        default=False,
        description=(
            "When True, rows whose status is currently 'completed' "
            "become eligible for retry (otherwise only 'failed' rows "
            "are picked up). Required when ``metric_ids`` is set on a "
            "successful row, since otherwise the whole metric-subset "
            "retry would be skipped as 'completed'."
        ),
    )

    # --- LLM overrides ---
    llm_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "Override the run-level LLM provider for this retry (and "
            "future retries). Must be paired with ``llm_model``."
        ),
    )
    llm_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description=(
            "Override the run-level LLM model. Must be paired with "
            "``llm_provider``."
        ),
    )
    llm_credential_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Pin a specific AIProvider credential row for the LLM. "
            "When omitted, the resolver falls back to the org default."
        ),
    )
    metric_llm_overrides: Optional[
        Dict[str, CallImportEvaluationLLMOverride]
    ] = Field(
        default=None,
        description=(
            "Replace the run's per-metric LLM overrides. When omitted, "
            "the existing overrides are kept; when set, this dict "
            "fully replaces them (pass an empty object to clear)."
        ),
    )

    # --- STT overrides ---
    stt_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "Override the run-level STT provider for this retry. Must "
            "be paired with ``stt_model``. Only meaningful when the "
            "run is configured for the diarised transcript source."
        ),
    )
    stt_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Override the run-level STT model.",
    )
    stt_credential_id: Optional[UUID] = Field(
        default=None,
        description="Pin a specific credential row for the STT call.",
    )
    # --- LLM diariser overrides ---
    # When set, replace the run-stored diariser configuration for any
    # rows that have to be re-diarised as part of the retry (i.e.
    # ``transcribe_overwrite=True`` or the row never had a diarised
    # transcript). Same provider+model pairing rule as STT.
    diarization_llm_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "Override the run's diariser LLM provider. Must be paired "
            "with ``diarization_llm_model``."
        ),
    )
    diarization_llm_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Override the run's diariser LLM model.",
    )
    diarization_llm_credential_id: Optional[UUID] = Field(
        default=None,
        description="Pin a specific credential row for the diariser LLM.",
    )
    diarization_prompt: Optional[str] = Field(
        default=None,
        max_length=10_000,
        description=(
            "Override the run's diariser prompt. Pass an empty string "
            "to clear the override and fall back to the canonical "
            "default; pass None to leave the existing value untouched."
        ),
    )
    transcribe_overwrite: bool = Field(
        default=False,
        description=(
            "When True, wipe the diarised transcript on every retried "
            "row's source CallImportRow so the (possibly new) STT runs "
            "from scratch. When False, rows that already have a "
            "diarised transcript skip diarisation and only re-evaluate."
        ),
    )


class CallImportEvaluationRetrySkippedItem(BaseModel):
    """One entry in the retry response's ``skipped`` list."""

    eval_row_id: UUID
    reason: str = Field(
        ...,
        description=(
            "Why this row was not re-enqueued. Known values: "
            "'unknown' (id not in this run), 'in_progress' "
            "(status is pending/running), 'completed' (already "
            "successful), 'source_row_missing'."
        ),
    )


class CallImportEvaluationRetryResponse(BaseModel):
    """Summary of a retry fan-out request."""

    requeued: int = Field(
        ...,
        description="How many evaluation rows were reset and re-enqueued.",
    )
    transcribe_requeued: int = Field(
        default=0,
        description=(
            "Of those, how many were chained through a diarisation "
            "task first because the diarised transcript was missing "
            "(matches the auto-transcribe behavior of the create-run "
            "endpoint)."
        ),
    )
    skipped: List[CallImportEvaluationRetrySkippedItem] = Field(
        default_factory=list,
        description="Rows the caller asked for that we did not re-enqueue.",
    )


class CallImportMetricSummary(BaseModel):
    """Lightweight metric descriptor returned alongside an evaluation."""

    id: UUID
    name: str
    metric_type: Optional[str] = None
    description: Optional[str] = None
    parent_metric_id: Optional[UUID] = None
    selection_mode: Optional[SelectionMode] = None
    # Surfaced so the Flow tab can decide whether to render the
    # Discovered Labels panel next to a multi_label parent. Defaults to
    # False to keep legacy clients (and standalone metrics) unaffected.
    allow_discovery: bool = False

    model_config = ConfigDict(from_attributes=True)


class CallImportEvaluationResponse(BaseModel):
    """Parent record describing one evaluation run over a batch."""

    id: UUID
    call_import_id: UUID
    organization_id: UUID
    name: Optional[str] = None
    selected_metric_ids: List[UUID] = Field(default_factory=list)
    # Parent UUID string -> [child UUID string]. Captured at run creation
    # so the UI can rebuild the parent/child tree even after metrics are
    # renamed or deleted. Empty / NULL = no hierarchy was used.
    selected_metric_groups: Optional[Dict[str, List[str]]] = None
    metrics: List[CallImportMetricSummary] = Field(default_factory=list)
    status: str
    total_rows: int
    completed_rows: int
    failed_rows: int
    error_message: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_credential_id: Optional[UUID] = None
    metric_llm_overrides: Optional[Dict[str, Any]] = None
    stt_provider: Optional[str] = None
    stt_model: Optional[str] = None
    stt_credential_id: Optional[UUID] = None
    # Run-level LLM diariser config. Surfaced so the UI can show
    # "Diarised via openai/gpt-4o-mini" on the evaluation header and
    # pre-fill the retry modal with the previously-used prompt.
    diarisation_llm_provider: Optional[str] = None
    diarisation_llm_model: Optional[str] = None
    diarisation_llm_credential_id: Optional[UUID] = None
    diarisation_prompt: Optional[str] = None
    # Diarisation pipeline shape this run was created with. ``stt_llm``
    # (default) is the legacy STT-then-LLM-diariser flow; ``llm_only``
    # means the audio was fed directly to a multimodal diariser LLM.
    # Surfaced so the retry modal can preselect the right mode and the
    # eval header can render "Diarised via LLM only (Gemini)" instead of
    # an empty STT label.
    transcribe_mode: Literal["stt_llm", "llm_only"] = "stt_llm"
    # Which transcript column this run scored against. See the
    # ``CallImportEvaluation.transcript_source`` model docstring for
    # the semantics. Defaults to ``'production'`` on legacy rows.
    transcript_source: CallImportEvaluationTranscriptSource = "production"
    # Sibling evaluation ids created in the same Run Evaluation request.
    # Populated only on the POST response (and only when the user ticked
    # both Production and Diarised in the modal — the backend creates
    # one ``CallImportEvaluation`` per source and links them via this
    # field so the frontend can deep-link to either run). Empty for all
    # other reads.
    sibling_evaluation_ids: List[UUID] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Cached LLM-generated TLDR for the Visualizations tab. Lazily
    # populated by ``POST /evaluations/{eval_id}/insights``; ``None``
    # for runs the user has not summarised yet. ``is_stale`` on the
    # nested object is set by the route, not the model.
    tldr_summary: Optional["EvaluationTldrSummary"] = None
    # True when the user opted into top-level metric discovery on the
    # Run Evaluation modal. The frontend uses this to gate the
    # "Discovered metrics" panel on the Flow tab.
    discover_new_metrics: bool = False

    model_config = ConfigDict(from_attributes=True)


class CallImportEvaluationListResponse(BaseModel):
    """Wrapper for listing evaluations on a single batch."""

    items: List[CallImportEvaluationResponse]
    total: int


class CallImportEvaluationRowResponse(BaseModel):
    """Per-source-row evaluation output (one Metric set applied to one row).

    ``raw_columns``, ``recording_url`` and ``recording_s3_key`` come from
    the parent ``CallImportRow`` so the row-detail panel can show the
    full CSV row metadata + audio without a second round-trip. The UI
    prefers ``recording_s3_key`` (resolved via a presigned URL) over
    ``recording_url`` so playback uses our downloaded copy instead of
    the raw provider URL, which is often expired/auth-gated.
    """

    id: UUID
    evaluation_id: UUID
    call_import_row_id: UUID
    row_index: Optional[int] = None
    # Renamed from ``external_call_id``; same value, mirrors the renamed
    # ``call_import_rows.conversation_id`` column.
    conversation_id: Optional[str] = None
    transcript: Optional[str] = None
    raw_columns: Optional[Dict[str, Any]] = None
    recording_url: Optional[str] = None
    recording_date: Optional[date] = None
    recording_s3_key: Optional[str] = None
    status: str
    metric_scores: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CallImportEvaluationRowListResponse(BaseModel):
    """Paginated per-row evaluation results."""

    items: List[CallImportEvaluationRowResponse]
    total: int
    page: int
    page_size: int


class CallImportRowBulkDelete(BaseModel):
    """Request body for deleting multiple rows from a call-import batch."""

    row_ids: List[UUID] = Field(
        ...,
        min_length=1,
        description="Row ids to delete (must belong to the same call import).",
    )


class CallImportRowBulkDeleteResponse(BaseModel):
    """Response after a bulk-delete pass over ``CallImportRow`` rows."""

    deleted: int = Field(
        ...,
        description="How many rows were actually removed (unknown ids are skipped).",
    )


class CallImportRetryFailedRowsResponse(BaseModel):
    """Summary of a retry pass over failed call-import rows."""

    requeued: int = Field(
        ...,
        description=(
            "Rows reset to pending and successfully re-enqueued on the "
            "``imports`` worker queue."
        ),
    )
    enqueue_failed: int = Field(
        default=0,
        description=(
            "Rows that were eligible for retry but failed to enqueue again. "
            "These rows are left in ``failed`` with an enqueue error."
        ),
    )
    skipped: int = Field(
        default=0,
        description=(
            "Rows skipped because they were no longer in ``failed`` at retry "
            "time (for example, already retried from another tab)."
        ),
    )


# --- Diarization / Transcription request/response shapes ---


class CallImportTranscribeRequest(BaseModel):
    """Body for kicking off diarization for one or many call-import rows.

    The same shape powers both the per-row endpoint (where ``row_ids``
    is ignored) and the batch-level endpoint. ``only_missing`` is the
    safe default — rows with an existing transcript are skipped unless
    ``overwrite_existing`` is set.

    Two modes are supported:

    * ``mode="stt_llm"`` (default) — the legacy two-stage pipeline: STT
      produces plain text, an LLM splits it into agent/user turns using
      ``diarization_prompt``. ``stt_provider`` and ``stt_model`` are
      required in this mode.
    * ``mode="llm_only"`` — skip STT entirely and hand the recording's
      audio bytes to a multimodal chat model along with
      ``diarization_prompt``. The model both transcribes and diarises in
      a single pass. The STT fields are ignored (and must be omitted /
      null). Only providers whose chat API accepts audio input (OpenAI
      ``gpt-4o-audio-*``, Google Gemini ``1.5/2.0``) are usable; other
      providers will surface a typed error on the row.
    """

    mode: Literal["stt_llm", "llm_only"] = Field(
        default="stt_llm",
        description=(
            "Pipeline shape. 'stt_llm' (default) runs STT then an LLM "
            "diariser over the resulting text. 'llm_only' skips STT and "
            "feeds the raw audio to a multimodal LLM together with "
            "``diarization_prompt`` for a single-pass transcribe + "
            "diarise."
        ),
    )
    stt_provider: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "STT provider key, e.g. 'deepgram' or 'openai'. Required when "
            "``mode='stt_llm'``; must be omitted when ``mode='llm_only'``."
        ),
    )
    stt_model: Optional[str] = Field(
        default=None,
        max_length=100,
        description=(
            "STT model name, e.g. 'nova-2' or 'whisper-1'. Required when "
            "``mode='stt_llm'``; must be omitted when ``mode='llm_only'``."
        ),
    )
    credential_id: Optional[UUID] = Field(
        default=None,
        description="Optional AIProvider/Integration row to pin for this run.",
    )
    language: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Optional ISO language hint, e.g. 'en'.",
    )
    only_missing: bool = Field(
        default=True,
        description=(
            "When true, rows with an existing transcript are skipped (the "
            "default safe behavior)."
        ),
    )
    overwrite_existing: bool = Field(
        default=False,
        description=(
            "When true, existing transcripts are replaced. Mutually "
            "exclusive with only_missing."
        ),
    )
    row_ids: Optional[List[UUID]] = Field(
        default=None,
        description=(
            "Restrict the run to a specific subset of rows. NULL = every "
            "row in the import (subject to only_missing)."
        ),
    )
    # --- LLM diariser config ---
    # In ``stt_llm`` mode diarisation runs as a *second* step: STT
    # produces plain text, then this LLM splits it into agent/user
    # turns. In ``llm_only`` mode this same LLM directly receives the
    # audio and the prompt. Both fields are always mandatory because
    # there is no longer a pyannote fallback and ``llm_only`` cannot
    # function without an LLM either.
    diarization_llm_provider: str = Field(
        ...,
        max_length=50,
        description=(
            "LLM provider that diarises the call. In ``stt_llm`` it sees "
            "the STT text; in ``llm_only`` it sees the raw audio."
        ),
    )
    diarization_llm_model: str = Field(
        ...,
        max_length=100,
        description=(
            "LLM model name. In ``llm_only`` mode this must be a model "
            "that accepts audio input (e.g. 'gpt-4o-audio-preview', "
            "'gemini-1.5-pro')."
        ),
    )
    diarization_llm_credential_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Optional AIProvider row to pin for the diarisation LLM."
        ),
    )
    diarization_prompt: Optional[str] = Field(
        default=None,
        max_length=10_000,
        description=(
            "Operator-supplied system prompt for the diariser LLM. "
            "When NULL/empty the worker uses the canonical default "
            "(see ``GET /api/v1/call-imports/diarisation-prompt-default``)."
        ),
    )

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "CallImportTranscribeRequest":
        """Enforce STT-field presence rules based on ``mode``.

        ``stt_llm`` (default) requires both STT fields — the worker
        cannot diarise without a transcript. ``llm_only`` forbids them
        so the API contract makes it clear that the audio is going
        straight to the LLM; passing both would be ambiguous about
        which path the worker should take.
        """
        stt_provider = (self.stt_provider or "").strip() if self.stt_provider else None
        stt_model = (self.stt_model or "").strip() if self.stt_model else None
        if self.mode == "stt_llm":
            if not stt_provider or not stt_model:
                raise ValueError(
                    "stt_provider and stt_model are required when "
                    "mode='stt_llm'."
                )
        else:  # llm_only
            if stt_provider or stt_model:
                raise ValueError(
                    "stt_provider/stt_model must be omitted when "
                    "mode='llm_only'; the LLM consumes the audio "
                    "directly."
                )
        return self


class CallImportDiarisationPromptDefaultResponse(BaseModel):
    """Wrapper for the canonical diariser-prompt fetched by the modal."""

    prompt: str = Field(
        ...,
        description=(
            "The exact prompt the worker falls back to when the caller "
            "leaves ``diarization_prompt`` blank. The frontend pre-fills "
            "the textarea with this value so the operator can edit it."
        ),
    )


class CallImportRowIdsResponse(BaseModel):
    """Flat row-id list for cross-page bulk selection.

    Powers the "Select all M rows in this import" affordance on the
    detail page — returning only ids keeps the payload tiny so the UI
    can hold the full set in memory even for batches with thousands
    of rows. The frontend then passes those ids straight to the
    existing bulk-delete / bulk-transcribe endpoints.
    """

    ids: List[UUID] = Field(
        default_factory=list,
        description=(
            "Every ``CallImportRow.id`` that matches the ``q`` and "
            "``diarised_status`` filters (or every row when neither is "
            "supplied), sorted by ``row_index``."
        ),
    )
    total: int = Field(
        ...,
        description=(
            "Length of ``ids``. Sent explicitly so callers can show a "
            "count without re-measuring the array."
        ),
    )


class CallImportTranscribeResponse(BaseModel):
    """Summary of a transcribe fan-out request."""

    queued: int = Field(
        ...,
        description=(
            "How many rows were enqueued for diarization. Skipped rows "
            "(missing recording, transcript already present, etc.) are "
            "not counted."
        ),
    )
    skipped_rows: int = Field(
        default=0,
        description="Rows excluded by only_missing or because they had no recording.",
    )
    skipped_reason_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Per-reason breakdown of skipped rows for the UI to surface.",
    )


class CallImportCancelDiarisationRequest(BaseModel):
    """Body for the batch cancel-diarisation endpoint.

    Omit ``row_ids`` (or pass ``null``) to cancel every row in the
    import whose ``diarised_transcript_status`` is currently
    ``pending`` or ``running``. Pass an explicit list to scope the
    cancel to a subset (e.g. the rows the operator selected in the
    UI).
    """

    row_ids: Optional[List[UUID]] = Field(
        default=None,
        description=(
            "Optional subset of CallImportRow UUIDs. ``None`` cancels "
            "every pending / running diarisation in the import."
        ),
    )


class CallImportCancelDiarisationResponse(BaseModel):
    """Summary of a cancel-diarisation request.

    ``cancelled`` counts rows that were actively pending / running
    when the cancel landed and got flipped to ``failed`` with a
    "Cancelled by user" error. ``skipped`` counts rows that were
    requested (or matched the implicit "all rows" filter) but were
    not in a cancellable state — typically because they had already
    finished or were never queued for diarisation in the first place.
    """

    cancelled: int = Field(
        ...,
        description=(
            "Rows whose in-flight Celery task was revoked and whose "
            "``diarised_transcript_status`` was flipped to ``failed`` "
            "with a 'Cancelled by user' error message."
        ),
    )
    skipped: int = Field(
        default=0,
        description=(
            "Rows that were requested but not in a cancellable state "
            "(idle / completed / already failed)."
        ),
    )


# --- Per-run aggregation / visualization payloads ---


class CallImportMetricHistogramBucket(BaseModel):
    """One bin of a numeric metric histogram."""

    x0: float
    x1: float
    count: int


class CallImportMetricValueCount(BaseModel):
    """One row of a categorical metric's value frequency table."""

    label: str
    count: int


class CallImportMetricLabelPair(BaseModel):
    """One unordered pair-count cell of a multi-label parent's
    co-occurrence matrix.

    ``a`` and ``b`` are child label names; ``count`` is the number of
    rows on which both labels fired together (intersection size).
    Pairs are emitted with ``a < b`` lexicographically so the matrix
    can be reconstructed without duplicates on the frontend.
    """

    a: str
    b: str
    count: int


class CallImportMetricAggregate(BaseModel):
    """Per-metric aggregate computed from an evaluation run's rows.

    Numeric metrics return summary statistics + histogram buckets;
    categorical / pass-fail / text metrics return the top value counts.
    Both shapes can coexist if a metric mixes types — the UI prefers
    histogram when present, falls back to value_counts otherwise.
    """

    metric_id: str
    metric_name: str
    metric_type: Optional[str] = None
    metric_category: str = "quality"
    # True when this aggregate represents a multi-label parent metric
    # (selection_mode == "multi_label" with no parent_metric_id). For
    # those, ``value_counts`` lists per-child label tallies and the
    # rows scored != sum(value_counts.count). The UI uses this flag to
    # force a horizontal bar layout (slices wouldn't sum to 100%) and
    # to label the n-badge as rows scored, not label occurrences.
    is_multi_label_parent: bool = False
    count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    # Numeric stats (None when no numeric values were observed)
    mean: Optional[float] = None
    median: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    p95: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    stddev: Optional[float] = None
    histogram_buckets: List[CallImportMetricHistogramBucket] = Field(
        default_factory=list
    )
    value_counts: List[CallImportMetricValueCount] = Field(default_factory=list)
    # Pairwise label intersections for multi-label parent metrics.
    # Empty for everything else. The frontend reconstructs a square
    # symmetric matrix from these unordered pairs and renders the
    # co-occurrence heatmap chart type.
    co_occurrence: List[CallImportMetricLabelPair] = Field(default_factory=list)


class CallImportEvaluationAggregateResponse(BaseModel):
    """Aggregated metric distributions for a single evaluation run."""

    evaluation_id: UUID
    total_rows: int
    completed_rows: int
    failed_rows: int
    metrics: List[CallImportMetricAggregate] = Field(default_factory=list)


# --- LLM-generated TLDR for the Visualizations tab ---


class EvaluationTldrSummary(BaseModel):
    """Cached LLM-generated narrative + bullet patterns for an eval run.

    Persisted on ``CallImportEvaluation.tldr_summary`` (JSONB) and
    rendered above the per-metric charts. ``generated_at_completed_rows``
    is the snapshot of ``completed_rows`` at the time the summary was
    written; the API compares it against the current count to flag
    ``is_stale`` so the UI can prompt for a regenerate.
    """

    narrative: str
    patterns: List[str] = Field(default_factory=list)
    generated_at: datetime
    generated_at_completed_rows: int = 0
    provider: Optional[str] = None
    model: Optional[str] = None
    is_stale: bool = False


class EvaluationInsightsRequest(BaseModel):
    """Body for ``POST /evaluations/{eval_id}/insights``.

    All fields are optional. When ``provider``/``model`` are unset the
    backend resolves the org's first active OpenAI/Anthropic/Google
    provider (mirroring the Prompt Partials AI-generate flow) so
    callers that don't care can simply post ``{}``.
    """

    regenerate: bool = False
    provider: Optional[str] = None
    model: Optional[str] = Field(default=None, min_length=1)


# Resolve the forward reference on ``CallImportEvaluationResponse``
# (defined further up the file) now that ``EvaluationTldrSummary``
# exists. Without this Pydantic raises at first ``.model_validate``
# because the string annotation can't be evaluated.
CallImportEvaluationResponse.model_rebuild()


# --- Cross-run insights for a CallImport batch ---


class CallImportInsightsRunPoint(BaseModel):
    """One run's mean for a metric, used to render trend lines."""

    evaluation_id: UUID
    name: Optional[str] = None
    created_at: datetime
    mean: Optional[float] = None
    completed_rows: int = 0


class CallImportInsightsMetric(BaseModel):
    """Per-metric history across every evaluation run on this import."""

    metric_id: str
    metric_name: str
    metric_type: Optional[str] = None
    latest: Optional[CallImportMetricAggregate] = None
    trend: List[CallImportInsightsRunPoint] = Field(default_factory=list)


class CallImportInsightsResponse(BaseModel):
    """Aggregated cross-run signals for a single call-import batch."""

    call_import_id: UUID
    total_rows: int
    rows_with_transcript: int
    rows_without_transcript: int
    transcript_source_counts: Dict[str, int] = Field(default_factory=dict)
    evaluation_count: int = 0
    metrics: List[CallImportInsightsMetric] = Field(default_factory=list)


# --- Flow chart visualization for hierarchical metrics ---


class MetricFlowNode(BaseModel):
    """One step in the LLM-inferred temporal flow for a parent metric.

    Represents a child sub-metric label. ``count`` is the number of rows
    in the evaluation where this child appears anywhere in its
    ``sequence`` array. ``is_terminal`` is set when the child is the
    last entry in a meaningful fraction of those sequences.

    ``is_discovered`` is set when the node represents an LLM-discovered
    candidate (parent has ``allow_discovery=true``) rather than a
    user-defined child. The id of a discovered node is prefixed with
    ``disc:`` so it can't collide with real child UUIDs.
    """

    id: str
    label: str
    count: int = 0
    is_terminal: bool = False
    is_discovered: bool = False


class MetricFlowEdge(BaseModel):
    """One directed transition between two children across all rows.

    ``count`` is the number of rows where ``source`` immediately
    precedes ``target`` in the sequence. The synthetic ``START`` node
    is used as the ``source`` for the first child in every sequence.
    """

    source: str
    target: str
    count: int = 0


class MetricFlowResponse(BaseModel):
    """Aggregate flow diagram payload for a single parent metric."""

    parent_metric_id: str
    parent_metric_name: str
    selection_mode: Optional[SelectionMode] = None
    nodes: List[MetricFlowNode] = Field(default_factory=list)
    edges: List[MetricFlowEdge] = Field(default_factory=list)
    total_rows: int = 0
    rows_with_sequence: int = 0


class DiscoveredLabelItem(BaseModel):
    """One LLM-discovered candidate sub-label aggregated across rows.

    ``key`` is the slugified label identifier (matches what appears in
    ``sequence`` entries). ``count`` is the number of rows in the
    evaluation that emitted this slug. ``sample_rationale`` is the
    first non-empty rationale captured from any row (back-compat
    field, identical to ``examples[0]`` when present). ``examples``
    holds up to 3 distinct rationales — the UI surfaces 2 of them as
    ``Examples:`` in the rubric on Promote, with the third kept as
    headroom in case the first is unhelpful.
    """

    key: str
    name: str
    description: Optional[str] = None
    sample_rationale: Optional[str] = None
    examples: List[str] = Field(default_factory=list, max_length=3)
    count: int = 0


class DiscoveredLabelsResponse(BaseModel):
    """List of discovered candidate sub-labels for a parent metric."""

    parent_metric_id: str
    items: List[DiscoveredLabelItem] = Field(default_factory=list)


class DiscoveredLabelMergeRequest(BaseModel):
    """Body for POST /evaluations/{eval_id}/discovered-labels/merge.

    Rewrites every row's ``metric_scores[parent_id].discovered_labels``
    entries whose key is ``from_key`` to use ``to_key`` instead, so the
    user can collapse near-duplicate candidates ("On Hold" / "Customer
    Put On Hold") into a single promoted child.
    """

    parent_metric_id: UUID
    from_key: str = Field(..., min_length=1, max_length=120)
    to_key: str = Field(..., min_length=1, max_length=120)


class DiscoveredLabelDeleteRequest(BaseModel):
    """Body for POST /evaluations/{eval_id}/discovered-labels/delete.

    Strips a candidate sub-label from every row's
    ``discovered_labels`` list AND from each row's ``sequence`` array,
    then tombstones the slug at the evaluation level so workers
    finishing later can't re-introduce it. Use for gibberish or
    irrelevant candidates the LLM proposed; for near-duplicates that
    you want to keep but unify, use the merge endpoint instead.
    """

    parent_metric_id: UUID
    key: str = Field(..., min_length=1, max_length=120)


class PromoteDiscoveredChildRequest(BaseModel):
    """Body for POST /metrics/{parent_id}/children/from-discovered.

    ``key`` is the slug under which the candidate is currently stored
    on per-row ``metric_scores``. The newly-created child Metric's
    name is normalized so ``slugify(name) == key``, which keeps every
    already-scored row's ``sequence`` array resolvable against the
    promoted child without a backfill.
    """

    key: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=4000)
    # Default True: when promoting a discovered label we want the new
    # sub-metric to always capture rationales going forward, since the
    # candidate was itself proposed *with* a rationale and the user
    # almost always wants to see why future rows hit it. Explicit False
    # keeps the original opt-in behavior available for callers that
    # don't care about rationales.
    capture_rationale: bool = True


# --- Discovered top-level metrics (per-evaluation discovery) ---
#
# Parallel to ``DiscoveredLabelItem`` / merge / delete / promote — but
# scoped to the evaluation as a whole, not to a parent category metric.
# Used by the "Discovered metrics" panel at the top of the evaluation
# detail Flow tab when ``CallImportEvaluation.discover_new_metrics``
# is true.


# The promote endpoint accepts these three suggested types; "category"
# creates a parent (no children yet) that the user can later extend in
# the Metrics page.
DiscoveredMetricSuggestedType = Literal["boolean", "rating", "category"]


class DiscoveredMetricItem(BaseModel):
    """One LLM-discovered candidate top-level metric aggregated across rows.

    Mirrors :class:`DiscoveredLabelItem` but at the evaluation level
    (no ``parent_metric_id``). ``suggested_type`` is the LLM's guess at
    the best representation; the promote flow lets the user override
    it before creating the real :class:`Metric` row.
    """

    key: str
    name: str
    description: Optional[str] = None
    suggested_type: DiscoveredMetricSuggestedType = "boolean"
    sample_rationale: Optional[str] = None
    examples: List[str] = Field(default_factory=list, max_length=3)
    count: int = 0


class DiscoveredMetricsResponse(BaseModel):
    """List of discovered candidate top-level metrics for an evaluation."""

    evaluation_id: UUID
    items: List[DiscoveredMetricItem] = Field(default_factory=list)


class DiscoveredMetricMergeRequest(BaseModel):
    """Body for POST /evaluations/{eval_id}/discovered-metrics/merge.

    Rewrites every row's ``metric_scores["__discovered_metrics__"]``
    entries whose key is ``from_key`` to use ``to_key`` instead, and
    records the redirect in ``CallImportEvaluation.discovered_metric_aliases``
    so workers finishing later can't resurrect the merged-out slug.
    """

    from_key: str = Field(..., min_length=1, max_length=120)
    to_key: str = Field(..., min_length=1, max_length=120)


class DiscoveredMetricDeleteRequest(BaseModel):
    """Body for POST /evaluations/{eval_id}/discovered-metrics/delete.

    Strips a candidate from every row's
    ``metric_scores["__discovered_metrics__"]`` list and tombstones
    the slug at the evaluation level (empty-string alias) so workers
    finishing later can't re-introduce it.
    """

    key: str = Field(..., min_length=1, max_length=120)


class PromoteDiscoveredMetricRequest(BaseModel):
    """Body for POST /metrics/from-discovered.

    Creates a standalone :class:`Metric` (``parent_metric_id=None``)
    from an LLM-discovered candidate. The new metric's name is
    normalized so ``slugify(name) == key`` to keep already-scored row
    payloads resolvable against the promoted metric. ``metric_type``
    selects how the new metric will be scored on future runs;
    ``"category"`` creates a ``multi_label`` parent with no children
    (the user adds children via the existing Metrics page).
    """

    key: str = Field(..., min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=4000)
    metric_type: DiscoveredMetricSuggestedType = "boolean"
    capture_rationale: bool = True
    # Optional per-type config knobs passed through to ``Metric.custom_config``.
    # For ``rating`` the frontend can supply {"min": 1, "max": 5}; for
    # ``boolean`` / ``category`` the field is typically empty.
    custom_config: Optional[Dict[str, Any]] = None


# --- Workspace Schemas ---


class WorkspaceBase(BaseModel):
    """Shared fields for workspace create/update payloads."""

    name: str = Field(..., min_length=1, max_length=255)


class WorkspaceCreate(WorkspaceBase):
    """Body for POST /workspaces."""

    # Optional: derived from name when omitted; uniqueness is per-org.
    slug: Optional[str] = Field(
        default=None, min_length=1, max_length=255
    )


class WorkspaceUpdate(BaseModel):
    """Body for PATCH /workspaces/{id} (rename only in v1)."""

    name: str = Field(..., min_length=1, max_length=255)


class WorkspaceResponse(BaseModel):
    """Response schema for a single workspace."""

    id: UUID
    organization_id: UUID
    name: str
    slug: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
