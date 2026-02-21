"""Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field, field_validator, validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from app.models.enums import (
    EvaluationType, EvaluationStatus, EvaluatorResultStatus, RoleEnum, InvitationStatus,
    LanguageEnum, CallTypeEnum, CallMediumEnum, GenderEnum, AccentEnum, BackgroundNoiseEnum,
    IntegrationPlatform, ModelProvider, VoiceBundleType, TestAgentConversationStatus,
    MetricType, MetricTrigger, CallRecordingStatus, AlertMetricType, AlertAggregation,
    AlertOperator, AlertNotifyFrequency, AlertStatus, AlertHistoryStatus, CronJobStatus
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

    class Config:
        from_attributes = True


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

    @validator("metrics")
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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


class MetricsResponse(BaseModel):
    """Schema for metrics breakdown."""

    evaluation_id: UUID
    metrics: Dict[str, Any]
    processing_time: Optional[float] = None


# Comparison Schema
class ComparisonRequest(BaseModel):
    """Schema for comparing multiple evaluations."""

    evaluation_ids: List[UUID] = Field(..., min_items=2, description="At least 2 evaluation IDs to compare")


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

    class Config:
        from_attributes = True


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

    class Config:
        json_schema_extra = {
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
        }


class AgentUpdate(BaseModel):
    """Schema for updating an agent"""
    name: Optional[str] = None
    phone_number: Optional[str] = None
    language: Optional[LanguageEnum] = None
    description: Optional[str] = None
    call_type: Optional[CallTypeEnum] = None
    call_medium: Optional[CallMediumEnum] = None
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
    voice_bundle_id: Optional[UUID]
    ai_provider_id: Optional[UUID]
    voice_ai_integration_id: Optional[UUID]
    voice_ai_agent_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    @validator('language', pre=True)
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

    @validator('call_type', pre=True)
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

    @validator('call_medium', pre=True)
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

    class Config:
        from_attributes = True


# Persona Schemas
class PersonaCreate(BaseModel):
    """Schema for creating a new persona"""
    name: str = Field(..., min_length=1, max_length=255)
    language: LanguageEnum = LanguageEnum.ENGLISH
    accent: AccentEnum = AccentEnum.AMERICAN
    gender: GenderEnum = GenderEnum.NEUTRAL
    background_noise: BackgroundNoiseEnum = BackgroundNoiseEnum.NONE


class PersonaUpdate(BaseModel):
    """Schema for updating a persona"""
    name: Optional[str] = None
    language: Optional[LanguageEnum] = None
    accent: Optional[AccentEnum] = None
    gender: Optional[GenderEnum] = None
    background_noise: Optional[BackgroundNoiseEnum] = None


class PersonaResponse(BaseModel):
    """Schema for persona response"""
    id: UUID
    name: str
    language: LanguageEnum
    accent: AccentEnum
    gender: GenderEnum
    background_noise: BackgroundNoiseEnum
    created_at: datetime
    updated_at: datetime

    @validator('language', pre=True)
    def convert_language(cls, v):
        """Convert string to LanguageEnum (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
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

    @validator('accent', pre=True)
    def convert_accent(cls, v):
        """Convert string to AccentEnum (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return AccentEnum(v_lower)
            except ValueError:
                for enum_member in AccentEnum:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid AccentEnum value: {v}")
        return v

    @validator('gender', pre=True)
    def convert_gender(cls, v):
        """Convert string to GenderEnum (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return GenderEnum(v_lower)
            except ValueError:
                for enum_member in GenderEnum:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid GenderEnum value: {v}")
        return v

    @validator('background_noise', pre=True)
    def convert_background_noise(cls, v):
        """Convert string to BackgroundNoiseEnum (handles uppercase DB values)."""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower()
            try:
                return BackgroundNoiseEnum(v_lower)
            except ValueError:
                for enum_member in BackgroundNoiseEnum:
                    if enum_member.name == v or enum_member.value == v:
                        return enum_member
                raise ValueError(f"Invalid BackgroundNoiseEnum value: {v}")
        return v

    class Config:
        from_attributes = True


class PersonaCloneRequest(BaseModel):
    """Schema for cloning a persona"""
    name: Optional[str] = None


# Scenario Schemas
class ScenarioCreate(BaseModel):
    """Schema for creating a new scenario"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    required_info: Dict[str, str] = Field(default_factory=dict)


class ScenarioUpdate(BaseModel):
    """Schema for updating a scenario"""
    name: Optional[str] = None
    description: Optional[str] = None
    required_info: Optional[Dict[str, str]] = None


class ScenarioResponse(BaseModel):
    """Schema for scenario response"""
    id: UUID
    name: str
    description: Optional[str]
    required_info: Dict[str, str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


class OrganizationMemberResponse(BaseModel):
    """Schema for organization member response."""
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: RoleEnum
    joined_at: datetime
    user: UserResponse  # Include user details

    class Config:
        from_attributes = True


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

    @validator('role', pre=True)
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

    @validator('status', pre=True)
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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


# ============================================
# INTEGRATION SCHEMAS
# ============================================

class IntegrationCreate(BaseModel):
    """Schema for creating an integration."""
    platform: IntegrationPlatform
    api_key: str = Field(..., description="Private API key for the platform")
    public_key: Optional[str] = Field(None, description="Optional public API key (e.g. for Vapi)")
    name: Optional[str] = Field(None, description="Optional friendly name for the integration")


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
    created_at: datetime
    updated_at: datetime
    last_tested_at: Optional[datetime] = None
    # Note: api_key is NOT included in response for security

    @validator('platform', pre=True)
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

    class Config:
        from_attributes = True


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
    created_at: datetime
    updated_at: datetime
    last_tested_at: Optional[datetime]

    @validator('provider', pre=True)
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
    
    class Config:
        from_attributes = True


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
    
    # LLM Configuration - required for STT_LLM_TTS, optional for S2S
    llm_provider: Optional[ModelProvider] = None
    llm_model: Optional[str] = Field(None, min_length=1)
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    llm_max_tokens: Optional[int] = Field(None, gt=0)
    llm_config: Optional[Dict[str, Any]] = None
    
    # TTS Configuration - required for STT_LLM_TTS, optional for S2S
    tts_provider: Optional[ModelProvider] = None
    tts_model: Optional[str] = Field(None, min_length=1)
    tts_voice: Optional[str] = None
    tts_config: Optional[Dict[str, Any]] = None
    
    # S2S Configuration - required for S2S, optional for STT_LLM_TTS
    s2s_provider: Optional[ModelProvider] = None
    s2s_model: Optional[str] = Field(None, min_length=1)
    s2s_config: Optional[Dict[str, Any]] = None
    
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
    
    # LLM Configuration
    llm_provider: Optional[ModelProvider] = None
    llm_model: Optional[str] = Field(None, min_length=1)
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    llm_max_tokens: Optional[int] = Field(None, gt=0)
    llm_config: Optional[Dict[str, Any]] = None
    
    # TTS Configuration
    tts_provider: Optional[ModelProvider] = None
    tts_model: Optional[str] = Field(None, min_length=1)
    tts_voice: Optional[str] = None
    tts_config: Optional[Dict[str, Any]] = None
    
    # S2S Configuration
    s2s_provider: Optional[ModelProvider] = None
    s2s_model: Optional[str] = Field(None, min_length=1)
    s2s_config: Optional[Dict[str, Any]] = None
    
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
    
    @validator('bundle_type', pre=True)
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
    
    @validator('stt_provider', 'llm_provider', 'tts_provider', 's2s_provider', pre=True)
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
    
    # LLM Configuration
    llm_provider: Optional[ModelProvider]
    llm_model: Optional[str]
    llm_temperature: Optional[float]
    llm_max_tokens: Optional[int]
    llm_config: Optional[Dict[str, Any]]
    
    # TTS Configuration
    tts_provider: Optional[ModelProvider]
    tts_model: Optional[str]
    tts_voice: Optional[str]
    tts_config: Optional[Dict[str, Any]]
    
    # S2S Configuration
    s2s_provider: Optional[ModelProvider]
    s2s_model: Optional[str]
    s2s_config: Optional[Dict[str, Any]]
    
    # Additional metadata
    extra_metadata: Optional[Dict[str, Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    
    class Config:
        from_attributes = True


# Test Agent Conversation Schemas
class TestAgentConversationCreate(BaseModel):
    """Schema for creating a new test agent conversation."""
    agent_id: UUID
    persona_id: UUID
    scenario_id: UUID
    voice_bundle_id: UUID
    conversation_metadata: Optional[Dict[str, Any]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "agent_id": "123e4567-e89b-12d3-a456-426614174000",
                "persona_id": "123e4567-e89b-12d3-a456-426614174001",
                "scenario_id": "123e4567-e89b-12d3-a456-426614174002",
                "voice_bundle_id": "123e4567-e89b-12d3-a456-426614174003"
            }
        }


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
    
    class Config:
        from_attributes = True


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
    
    class Config:
        json_schema_extra = {
            "example": {
                "transcription_id": "123e4567-e89b-12d3-a456-426614174000",
                "agent_id": "123e4567-e89b-12d3-a456-426614174001",
                "llm_provider": "openai",
                "llm_model": "gpt-4o"
            }
        }


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
    
    class Config:
        from_attributes = True


# Evaluator Schemas
class EvaluatorCreate(BaseModel):
    """Schema for creating an evaluator."""
    agent_id: UUID
    persona_id: UUID
    scenario_id: UUID
    tags: Optional[List[str]] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "agent_id": "123e4567-e89b-12d3-a456-426614174000",
                "persona_id": "123e4567-e89b-12d3-a456-426614174001",
                "scenario_id": "123e4567-e89b-12d3-a456-426614174002",
                "tags": ["test", "production"]
            }
        }


class EvaluatorUpdate(BaseModel):
    """Schema for updating an evaluator."""
    agent_id: Optional[UUID] = None
    persona_id: Optional[UUID] = None
    scenario_id: Optional[UUID] = None
    tags: Optional[List[str]] = None


class EvaluatorResponse(BaseModel):
    """Schema for evaluator response."""
    id: UUID
    evaluator_id: str
    organization_id: UUID
    agent_id: UUID
    persona_id: UUID
    scenario_id: UUID
    tags: Optional[List[str]]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    
    class Config:
        from_attributes = True


class EvaluatorBulkCreate(BaseModel):
    """Schema for creating multiple evaluators at once."""
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
    
    class Config:
        from_attributes = True
    
    class Config:
        json_schema_extra = {
            "example": {
                "agent_id": "123e4567-e89b-12d3-a456-426614174000",
                "scenario_id": "123e4567-e89b-12d3-a456-426614174002",
                "persona_ids": [
                    "123e4567-e89b-12d3-a456-426614174001",
                    "123e4567-e89b-12d3-a456-426614174003"
                ],
                "tags": ["test", "production"]
            }
        }


# Metric Schemas
class MetricCreate(BaseModel):
    """Schema for creating a metric."""
    name: str
    description: Optional[str] = None
    metric_type: MetricType = MetricType.RATING
    trigger: MetricTrigger = MetricTrigger.ALWAYS
    enabled: bool = True
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Professionalism",
                "description": "Measures the professional tone and behavior",
                "metric_type": "rating",
                "trigger": "always",
                "enabled": True
            }
        }


class MetricUpdate(BaseModel):
    """Schema for updating a metric."""
    name: Optional[str] = None
    description: Optional[str] = None
    metric_type: Optional[MetricType] = None
    trigger: Optional[MetricTrigger] = None
    enabled: Optional[bool] = None


class MetricResponse(BaseModel):
    """Schema for metric response."""
    id: UUID
    organization_id: UUID
    name: str
    description: Optional[str]
    metric_type: MetricType
    trigger: MetricTrigger
    enabled: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    @validator('metric_type', pre=True)
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

    @validator('trigger', pre=True)
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
    
    class Config:
        from_attributes = True


# Evaluator Result Schemas
class EvaluatorResultCreate(BaseModel):
    """Schema for creating an evaluator result."""
    evaluator_id: UUID
    agent_id: UUID
    persona_id: UUID
    scenario_id: UUID
    name: str
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
    agent_id: UUID
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

    @validator('status', pre=True)
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
    
    class Config:
        from_attributes = True


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
    
    class Config:
        json_schema_extra = {
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
        }


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

    @validator('metric_type', pre=True)
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

    @validator('aggregation', pre=True)
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

    @validator('operator', pre=True)
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

    @validator('notify_frequency', pre=True)
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

    @validator('status', pre=True)
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
    
    class Config:
        from_attributes = True


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

    @validator('status', pre=True)
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
    
    class Config:
        from_attributes = True


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
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Daily Evaluation Run",
                "cron_expression": "0 9 * * 1-5",
                "timezone": "America/New_York",
                "max_runs": 100,
                "evaluator_ids": ["123e4567-e89b-12d3-a456-426614174000"]
            }
        }


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

    @validator('status', pre=True)
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

    @validator('evaluator_ids', pre=True)
    def convert_evaluator_ids(cls, v):
        """Convert evaluator_ids from JSON to list of UUIDs."""
        if v is None:
            return []
        if isinstance(v, list):
            return [UUID(str(id)) if not isinstance(id, UUID) else id for id in v]
        return v

    class Config:
        from_attributes = True