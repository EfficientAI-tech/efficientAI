"""Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from app.models.database import EvaluationType, EvaluationStatus, BatchStatus


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
        schema_extra = {
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
        orm_mode = True


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
        orm_mode = True


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
        orm_mode = True

