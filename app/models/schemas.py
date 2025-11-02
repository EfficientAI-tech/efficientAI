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

