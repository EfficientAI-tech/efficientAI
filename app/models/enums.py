
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


class AlertMetricType(str, enum.Enum):
    """Alert metric type enumeration."""
    NUMBER_OF_CALLS = "number_of_calls"
    CALL_DURATION = "call_duration"
    ERROR_RATE = "error_rate"
    SUCCESS_RATE = "success_rate"
    LATENCY = "latency"
    CUSTOM = "custom"


class AlertAggregation(str, enum.Enum):
    """Alert aggregation type enumeration."""
    SUM = "sum"
    AVG = "avg"
    COUNT = "count"
    MIN = "min"
    MAX = "max"


class AlertOperator(str, enum.Enum):
    """Alert comparison operator enumeration."""
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN_OR_EQUAL = "<="
    EQUAL = "="
    NOT_EQUAL = "!="


class AlertNotifyFrequency(str, enum.Enum):
    """Alert notification frequency enumeration."""
    IMMEDIATE = "immediate"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


class AlertStatus(str, enum.Enum):
    """Alert status enumeration."""
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class AlertHistoryStatus(str, enum.Enum):
    """Alert history status enumeration."""
    TRIGGERED = "triggered"
    NOTIFIED = "notified"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
