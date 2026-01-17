
import enum

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
    TRANSCRIBING = "transcribing"
    EVALUATING = "evaluating"
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

class IntegrationPlatform(str, enum.Enum):
    """Integration platform enumeration."""
    RETELL = "retell"
    VAPI = "vapi"
    CARTESIA = "cartesia"
    ELEVENLABS = "elevenlabs"
    DEEPGRAM = "deepgram"

class ModelProvider(str, enum.Enum):
    """Model provider enumeration for extensibility."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    AZURE = "azure"
    AWS = "aws"
    DEEPGRAM = "deepgram"
    CARTESIA = "cartesia"
    CUSTOM = "custom"

class VoiceBundleType(str, enum.Enum):
    """VoiceBundle type enumeration."""
    STT_LLM_TTS = "stt_llm_tts"
    S2S = "s2s"

class TestAgentConversationStatus(str, enum.Enum):
    """Test agent conversation status enumeration."""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class MetricType(str, enum.Enum):
    """Metric type enumeration."""
    NUMBER = "number"
    BOOLEAN = "boolean"
    RATING = "rating"

class MetricTrigger(str, enum.Enum):
    """Metric trigger enumeration."""
    ALWAYS = "always"

class CallRecordingStatus(str, enum.Enum):
    """Call recording status enumeration."""
    PENDING = "pending"
    UPDATED = "updated"
