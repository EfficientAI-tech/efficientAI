"""SQLAlchemy database models."""

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Boolean, JSON, Enum
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


class BatchStatus(str, enum.Enum):
    """Batch job status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class APIKey(Base):
    """API Key model for authentication."""

    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), nullable=True)


class AudioFile(Base):
    """Audio file model."""

    __tablename__ = "audio_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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


class BatchJob(Base):
    """Batch evaluation job model."""

    __tablename__ = "batch_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(Enum(BatchStatus), default=BatchStatus.PENDING, nullable=False)
    total_files = Column(Integer, nullable=False)
    processed_files = Column(Integer, default=0, nullable=False)
    failed_files = Column(Integer, default=0, nullable=False)
    evaluation_ids = Column(JSON, nullable=True)  # List of evaluation IDs in this batch
    evaluation_type = Column(Enum(EvaluationType), nullable=False)
    model_name = Column(String(100), nullable=True)
    metrics_requested = Column(JSON, nullable=True)
    aggregated_metrics = Column(JSON, nullable=True)  # Aggregated metrics across batch
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(String, nullable=True)

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
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    language = Column(Enum(LanguageEnum), nullable=False, default=LanguageEnum.ENGLISH)
    description = Column(String)
    call_type = Column(Enum(CallTypeEnum), nullable=False, default=CallTypeEnum.OUTBOUND)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String)


class Persona(Base):
    """Persona - The simulated caller/user for testing"""
    __tablename__ = "personas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    name = Column(String, nullable=False)
    description = Column(String)
    required_info = Column(JSON)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String)

