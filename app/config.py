"""Configuration management using Pydantic settings."""

import json
import yaml
from pathlib import Path
from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Application
    APP_NAME: str = "Voice AI Evaluation Platform"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: Optional[str] = None
    POSTGRES_USER: str = "efficientai"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "efficientai"

    # Redis
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 500
    ALLOWED_AUDIO_FORMATS: List[str] = ["wav", "mp3", "flac", "m4a"]
    
    # S3 Configuration
    S3_ENABLED: bool = False
    S3_BUCKET_NAME: Optional[str] = None
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY_ID: Optional[str] = None
    S3_SECRET_ACCESS_KEY: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None  # For S3-compatible services
    S3_PREFIX: str = "audio/"  # Prefix for audio files in bucket

    # Celery
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # API Settings
    API_KEY_HEADER: str = "X-API-Key"
    RATE_LIMIT_PER_MINUTE: int = 60
    
    # Frontend
    FRONTEND_DIR: str = "./frontend/dist"
    
    # SMTP / Email Notifications (for Alerts)
    SMTP_HOST: Optional[str] = None  # e.g., "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None  # e.g., "alerts@efficientai.dev"
    SMTP_FROM_NAME: str = "EfficientAI Alerts"
    SMTP_USE_TLS: bool = True
    
    # Speaker Diarization (Optional)
    HUGGINGFACE_TOKEN: Optional[str] = None  # For pyannote.audio speaker diarization
    DIARIZATION_NUM_SPEAKERS: Optional[int] = 2  # Force pyannote to detect this many speakers (None = auto-detect)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Make .env file optional - if it doesn't exist or has errors, use defaults
        env_ignore_empty=True,
        extra="ignore",  # Ignore extra fields from env file
        # Don't validate on assignment to allow validators to handle parsing
        validate_assignment=False,
    )
    
    @field_validator("ALLOWED_AUDIO_FORMATS", mode="before")
    @classmethod
    def parse_allowed_formats(cls, v: Union[str, List[str], None]) -> List[str]:
        """Parse ALLOWED_AUDIO_FORMATS from various formats."""
        # Handle None or empty values
        if v is None:
            return ["wav", "mp3", "flac", "m4a"]
        
        if isinstance(v, list):
            return v if v else ["wav", "mp3", "flac", "m4a"]
        
        if isinstance(v, str):
            # Handle empty or whitespace-only strings
            v = v.strip()
            if not v:
                return ["wav", "mp3", "flac", "m4a"]
            
            # Try JSON first
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    return parsed if isinstance(parsed, list) and parsed else ["wav", "mp3", "flac", "m4a"]
                except (json.JSONDecodeError, ValueError):
                    pass
            
            # Fall back to comma-separated
            formats = [fmt.strip() for fmt in v.split(",") if fmt.strip()]
            return formats if formats else ["wav", "mp3", "flac", "m4a"]
        
        return ["wav", "mp3", "flac", "m4a"]  # Default
    
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str], None]) -> List[str]:
        """Parse CORS_ORIGINS from various formats."""
        # Handle None or empty values
        if v is None:
            return ["http://localhost:3000", "http://localhost:8000"]
        
        if isinstance(v, list):
            return v if v else ["http://localhost:3000", "http://localhost:8000"]
        
        if isinstance(v, str):
            # Handle empty or whitespace-only strings
            v = v.strip()
            if not v:
                return ["http://localhost:3000", "http://localhost:8000"]
            
            # Try JSON first
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list) and parsed:
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            
            # Fall back to comma-separated
            origins = [origin.strip() for origin in v.split(",") if origin.strip()]
            return origins if origins else ["http://localhost:3000", "http://localhost:8000"]
        
        return ["http://localhost:3000", "http://localhost:8000"]  # Default
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Build DATABASE_URL if not provided
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        
        # Build REDIS_URL if not provided
        if not self.REDIS_URL:
            self.REDIS_URL = f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        
        # Build Celery URLs if not provided
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = self.REDIS_URL


def load_config_from_file(config_path: str) -> None:
    """Load configuration from a YAML file and update global settings."""
    import yaml
    
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, "r") as f:
        config_data = yaml.safe_load(f) or {}
    
    # Update settings with YAML values
    if "app" in config_data:
        app_config = config_data["app"]
        if "name" in app_config:
            settings.APP_NAME = app_config["name"]
        if "version" in app_config:
            settings.APP_VERSION = app_config["version"]
        if "debug" in app_config:
            settings.DEBUG = app_config["debug"]
        if "secret_key" in app_config:
            settings.SECRET_KEY = app_config["secret_key"]
    
    if "server" in config_data:
        server_config = config_data["server"]
        if "host" in server_config:
            settings.HOST = server_config["host"]
        if "port" in server_config:
            settings.PORT = server_config["port"]
    
    if "database" in config_data:
        db_config = config_data["database"]
        if "url" in db_config:
            settings.DATABASE_URL = db_config["url"]
        else:
            if "user" in db_config:
                settings.POSTGRES_USER = db_config["user"]
            if "password" in db_config:
                settings.POSTGRES_PASSWORD = db_config["password"]
            if "host" in db_config:
                settings.POSTGRES_HOST = db_config["host"]
            if "port" in db_config:
                settings.POSTGRES_PORT = db_config["port"]
            if "db" in db_config:
                settings.POSTGRES_DB = db_config["db"]
            # Rebuild DATABASE_URL
            settings.DATABASE_URL = (
                f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
                f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            )
    
    if "redis" in config_data:
        redis_config = config_data["redis"]
        if "url" in redis_config:
            settings.REDIS_URL = redis_config["url"]
        else:
            if "host" in redis_config:
                settings.REDIS_HOST = redis_config["host"]
            if "port" in redis_config:
                settings.REDIS_PORT = redis_config["port"]
            if "db" in redis_config:
                settings.REDIS_DB = redis_config["db"]
            # Rebuild REDIS_URL
            settings.REDIS_URL = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    
    if "celery" in config_data:
        celery_config = config_data["celery"]
        if "broker_url" in celery_config:
            settings.CELERY_BROKER_URL = celery_config["broker_url"]
        if "result_backend" in celery_config:
            settings.CELERY_RESULT_BACKEND = celery_config["result_backend"]
    
    if "storage" in config_data:
        storage_config = config_data["storage"]
        if "upload_dir" in storage_config:
            settings.UPLOAD_DIR = storage_config["upload_dir"]
        if "max_file_size_mb" in storage_config:
            settings.MAX_FILE_SIZE_MB = storage_config["max_file_size_mb"]
        if "allowed_audio_formats" in storage_config:
            settings.ALLOWED_AUDIO_FORMATS = storage_config["allowed_audio_formats"]
    
    if "s3" in config_data:
        s3_config = config_data["s3"]
        if "enabled" in s3_config:
            settings.S3_ENABLED = s3_config["enabled"]
        if "bucket_name" in s3_config:
            settings.S3_BUCKET_NAME = s3_config["bucket_name"]
        if "region" in s3_config:
            settings.S3_REGION = s3_config["region"]
        if "access_key_id" in s3_config:
            settings.S3_ACCESS_KEY_ID = s3_config["access_key_id"]
        if "secret_access_key" in s3_config:
            settings.S3_SECRET_ACCESS_KEY = s3_config["secret_access_key"]
        if "endpoint_url" in s3_config:
            settings.S3_ENDPOINT_URL = s3_config["endpoint_url"]
        if "prefix" in s3_config:
            settings.S3_PREFIX = s3_config["prefix"]
    
    if "smtp" in config_data:
        smtp_config = config_data["smtp"]
        if "host" in smtp_config:
            settings.SMTP_HOST = smtp_config["host"]
        if "port" in smtp_config:
            settings.SMTP_PORT = smtp_config["port"]
        if "username" in smtp_config:
            settings.SMTP_USERNAME = smtp_config["username"]
        if "password" in smtp_config:
            settings.SMTP_PASSWORD = smtp_config["password"]
        if "from_email" in smtp_config:
            settings.SMTP_FROM_EMAIL = smtp_config["from_email"]
        if "from_name" in smtp_config:
            settings.SMTP_FROM_NAME = smtp_config["from_name"]
        if "use_tls" in smtp_config:
            settings.SMTP_USE_TLS = smtp_config["use_tls"]
    
    if "diarization" in config_data:
        diarization_config = config_data["diarization"]
        if "huggingface_token" in diarization_config and diarization_config["huggingface_token"]:
            settings.HUGGINGFACE_TOKEN = diarization_config["huggingface_token"]
        if "num_speakers" in diarization_config:
            val = diarization_config["num_speakers"]
            settings.DIARIZATION_NUM_SPEAKERS = int(val) if val is not None else None

    if "cors" in config_data:
        cors_config = config_data["cors"]
        if "origins" in cors_config:
            settings.CORS_ORIGINS = cors_config["origins"]
    
    if "api" in config_data:
        api_config = config_data["api"]
        if "prefix" in api_config:
            settings.API_V1_PREFIX = api_config["prefix"]
        if "key_header" in api_config:
            settings.API_KEY_HEADER = api_config["key_header"]
        if "rate_limit_per_minute" in api_config:
            settings.RATE_LIMIT_PER_MINUTE = api_config["rate_limit_per_minute"]
    
    # Update Celery URLs if they weren't explicitly set
    if not settings.CELERY_BROKER_URL:
        settings.CELERY_BROKER_URL = settings.REDIS_URL
    if not settings.CELERY_RESULT_BACKEND:
        settings.CELERY_RESULT_BACKEND = settings.REDIS_URL


# Initialize settings with error handling for problematic env vars
# If .env file has invalid format, we'll use defaults (YAML config will override anyway)
try:
    settings = Settings()
except Exception as e:
    # If there's an error loading from .env (e.g., invalid JSON in list fields),
    # create settings with defaults. The YAML config loaded later will override these.
    import warnings
    import os
    
    warnings.warn(
        f"Error loading .env file, using defaults. YAML config will override. Error: {str(e)[:100]}",
        UserWarning,
        stacklevel=2
    )
    
    # Try to create settings without .env file by temporarily removing it
    env_file = ".env"
    if os.path.exists(env_file):
        # Temporarily rename .env to avoid loading it
        backup_file = f"{env_file}.backup"
        try:
            os.rename(env_file, backup_file)
            settings = Settings()
            os.rename(backup_file, env_file)
        except Exception:
            # If rename fails or Settings still fails, restore and use defaults
            if os.path.exists(backup_file):
                try:
                    os.rename(backup_file, env_file)
                except Exception:
                    pass
            # Create with explicit defaults - manually construct with default values
            settings = Settings(
                ALLOWED_AUDIO_FORMATS=["wav", "mp3", "flac", "m4a"],
                CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"],
                _env_file=None,  # Don't load .env
            )
    else:
        # No .env file, create normally
        settings = Settings()

