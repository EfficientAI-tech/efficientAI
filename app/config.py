"""Configuration management using Pydantic settings."""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings."""

    # Application
    APP_NAME: str = "Voice AI Evaluation Platform"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-here-change-in-production"

    # Database
    DATABASE_URL: str = "postgresql://efficientai:password@localhost:5432/efficientai"
    POSTGRES_USER: str = "efficientai"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "efficientai"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 500
    ALLOWED_AUDIO_FORMATS: List[str] = ["wav", "mp3", "flac", "m4a"]

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # API Settings
    API_KEY_HEADER: str = "X-API-Key"
    RATE_LIMIT_PER_MINUTE: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

