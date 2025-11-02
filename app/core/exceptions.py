"""Custom exceptions for the application."""


class EfficientAIException(Exception):
    """Base exception for EfficientAI platform."""

    pass


class AudioFileNotFoundError(EfficientAIException):
    """Raised when audio file is not found."""

    pass


class InvalidAudioFormatError(EfficientAIException):
    """Raised when audio format is not supported."""

    pass


class EvaluationNotFoundError(EfficientAIException):
    """Raised when evaluation is not found."""

    pass


class EvaluationAlreadyProcessingError(EfficientAIException):
    """Raised when trying to modify a processing evaluation."""

    pass


class InvalidAPIKeyError(EfficientAIException):
    """Raised when API key is invalid."""

    pass


class StorageError(EfficientAIException):
    """Raised when file storage operations fail."""

    pass


class MetricsCalculationError(EfficientAIException):
    """Raised when metrics calculation fails."""

    pass

