"""Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from app.models.database import EvaluationType, EvaluationStatus, BatchStatus, RoleEnum, InvitationStatus, IntegrationPlatform, ModelProvider


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


# Batch Job Schemas
class BatchCreate(BaseModel):
    """Schema for creating a batch evaluation."""

    audio_ids: List[UUID] = Field(..., min_items=1, description="List of audio file IDs to evaluate")
    reference_texts: Optional[Dict[str, str]] = Field(
        None, description="Mapping of audio_id to reference text"
    )
    evaluation_type: EvaluationType
    model_name: Optional[str] = None
    metrics: Optional[List[str]] = Field(default=["wer", "latency"], description="Metrics to calculate")

    @validator("metrics")
    def validate_metrics(cls, v):
        """Validate metrics list."""
        allowed_metrics = ["wer", "cer", "latency", "quality_score", "rtf"]
        if v:
            invalid = [m for m in v if m not in allowed_metrics]
            if invalid:
                raise ValueError(f"Invalid metrics: {invalid}")
        return v


class BatchResponse(BaseModel):
    """Schema for batch job response."""

    id: UUID
    status: BatchStatus
    total_files: int
    processed_files: int
    failed_files: int
    evaluation_type: EvaluationType
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BatchResultsResponse(BaseModel):
    """Schema for batch results summary."""

    batch_id: UUID
    status: BatchStatus
    total_files: int
    processed_files: int
    failed_files: int
    aggregated_metrics: Optional[Dict[str, Any]] = None
    individual_results: List[EvaluationResultResponse]


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

from enum import Enum as PyEnum

class LanguageEnum(str, PyEnum):
    ENGLISH = "en"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"
    CHINESE = "zh"
    JAPANESE = "ja"
    HINDI = "hi"
    ARABIC = "ar"


class CallTypeEnum(str, PyEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class GenderEnum(str, PyEnum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


class AccentEnum(str, PyEnum):
    AMERICAN = "american"
    BRITISH = "british"
    AUSTRALIAN = "australian"
    INDIAN = "indian"
    CHINESE = "chinese"
    SPANISH = "spanish"
    FRENCH = "french"
    GERMAN = "german"
    NEUTRAL = "neutral"


class BackgroundNoiseEnum(str, PyEnum):
    NONE = "none"
    OFFICE = "office"
    STREET = "street"
    CAFE = "cafe"
    HOME = "home"
    CALL_CENTER = "call_center"


# Agent Schemas
class AgentCreate(BaseModel):
    """Schema for creating a new agent"""
    name: str = Field(..., min_length=1, max_length=255)
    phone_number: str
    language: LanguageEnum = LanguageEnum.ENGLISH
    description: Optional[str] = None
    call_type: CallTypeEnum = CallTypeEnum.OUTBOUND

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Customer Support Bot",
                "phone_number": "+1234567890",
                "language": "en",
                "description": "Handles customer support",
                "call_type": "outbound"
            }
        }


class AgentUpdate(BaseModel):
    """Schema for updating an agent"""
    name: Optional[str] = None
    phone_number: Optional[str] = None
    language: Optional[LanguageEnum] = None
    description: Optional[str] = None
    call_type: Optional[CallTypeEnum] = None


class AgentResponse(BaseModel):
    """Schema for agent response"""
    id: UUID
    name: str
    phone_number: str
    language: LanguageEnum
    description: Optional[str]
    call_type: CallTypeEnum
    created_at: datetime
    updated_at: datetime

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
    email: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response."""
    id: UUID
    email: str
    name: Optional[str]
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
    api_key: str = Field(..., description="API key for the platform")
    name: Optional[str] = Field(None, description="Optional friendly name for the integration")


class IntegrationUpdate(BaseModel):
    """Schema for updating an integration."""
    name: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    id: UUID
    organization_id: UUID
    platform: IntegrationPlatform
    name: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_tested_at: Optional[datetime] = None
    # Note: api_key is NOT included in response for security

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
    
    class Config:
        from_attributes = True


# VoiceBundle Schemas
class VoiceBundleCreate(BaseModel):
    """Schema for creating a VoiceBundle."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    
    # STT Configuration
    stt_provider: ModelProvider
    stt_model: str = Field(..., min_length=1)
    
    # LLM Configuration
    llm_provider: ModelProvider
    llm_model: str = Field(..., min_length=1)
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    llm_max_tokens: Optional[int] = Field(None, gt=0)
    llm_config: Optional[Dict[str, Any]] = None
    
    # TTS Configuration
    tts_provider: ModelProvider
    tts_model: str = Field(..., min_length=1)
    tts_voice: Optional[str] = None
    tts_config: Optional[Dict[str, Any]] = None
    
    # Additional metadata
    extra_metadata: Optional[Dict[str, Any]] = None


class VoiceBundleUpdate(BaseModel):
    """Schema for updating a VoiceBundle."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    
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
    
    # Additional metadata
    extra_metadata: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class VoiceBundleResponse(BaseModel):
    """Schema for VoiceBundle response."""
    id: UUID
    name: str
    description: Optional[str]
    
    # STT Configuration
    stt_provider: ModelProvider
    stt_model: str
    
    # LLM Configuration
    llm_provider: ModelProvider
    llm_model: str
    llm_temperature: Optional[float]
    llm_max_tokens: Optional[int]
    llm_config: Optional[Dict[str, Any]]
    
    # TTS Configuration
    tts_provider: ModelProvider
    tts_model: str
    tts_voice: Optional[str]
    tts_config: Optional[Dict[str, Any]]
    
    # Additional metadata
    extra_metadata: Optional[Dict[str, Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    
    class Config:
        from_attributes = True
