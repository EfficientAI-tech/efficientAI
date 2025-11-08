"""Service for managing AI model configurations from JSON file."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from app.models.database import ModelProvider


class ModelConfigService:
    """Service to load and manage model configurations from JSON file."""
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize the service with config file path."""
        if config_path is None:
            # Default to app/config/models.json
            config_path = Path(__file__).parent.parent / "config" / "models.json"
        self.config_path = config_path
        self._config: Optional[Dict[str, Any]] = None
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Model config file not found: {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")
    
    def reload_config(self) -> None:
        """Reload configuration from file."""
        self._load_config()
    
    def get_all_models(self) -> Dict[str, Any]:
        """Get all model configurations."""
        if self._config is None:
            self._load_config()
        # Exclude sample_spec
        return {k: v for k, v in self._config.items() if k != "sample_spec"}
    
    def get_model_config(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific model."""
        if self._config is None:
            self._load_config()
        return self._config.get(model_name)
    
    def get_models_by_provider(self, provider: ModelProvider) -> List[str]:
        """Get all model names for a specific provider."""
        if self._config is None:
            self._load_config()
        provider_str = provider.value
        models = []
        for model_name, config in self._config.items():
            if model_name == "sample_spec":
                continue
            if config.get("provider") == provider_str:
                models.append(model_name)
        return models
    
    def get_models_by_type(self, provider: ModelProvider, model_type: str) -> List[str]:
        """
        Get models by provider and type (stt, llm, tts).
        
        Args:
            provider: The model provider
            model_type: One of 'stt', 'llm', 'tts'
        """
        if self._config is None:
            self._load_config()
        provider_str = provider.value
        models = []
        for model_name, config in self._config.items():
            if model_name == "sample_spec":
                continue
            if config.get("provider") == provider_str and config.get("model_type") == model_type:
                models.append(model_name)
        return models
    
    def get_model_options_by_provider(self, provider: ModelProvider) -> Dict[str, List[str]]:
        """
        Get model options organized by type for a provider.
        
        Returns:
            Dict with keys 'stt', 'llm', 'tts' and values as lists of model names
        """
        return {
            "stt": self.get_models_by_type(provider, "stt"),
            "llm": self.get_models_by_type(provider, "llm"),
            "tts": self.get_models_by_type(provider, "tts"),
        }
    
    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a model.
        
        Returns:
            Dict with model configuration (provider and model_type)
        """
        return self.get_model_config(model_name)
    
    def validate_model(self, provider: ModelProvider, model_name: str, model_type: str) -> bool:
        """Validate that a model exists and matches the provider and type."""
        config = self.get_model_config(model_name)
        if config is None:
            return False
        return (
            config.get("provider") == provider.value and
            config.get("model_type") == model_type
        )


# Singleton instance
model_config_service = ModelConfigService()

