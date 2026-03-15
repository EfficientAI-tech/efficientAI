"""Service for managing AI model configurations from JSON file."""

import ast
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
            config_path = Path(__file__).parent.parent.parent / "config" / "models.json"
        self.config_path = config_path
        self._config: Optional[Dict[str, Any]] = None
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
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
        Get models by provider and type (stt, llm, tts, s2s).

        Args:
            provider: The model provider
            model_type: One of 'stt', 'llm', 'tts', 's2s'
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
            Dict with keys 'stt', 'llm', 'tts', 's2s' and values as lists of model names
        """
        return {
            "stt": self.get_models_by_type(provider, "stt"),
            "llm": self.get_models_by_type(provider, "llm"),
            "tts": self.get_models_by_type(provider, "tts"),
            "s2s": self.get_models_by_type(provider, "s2s"),
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
            config.get("provider") == provider.value
            and config.get("model_type") == model_type
        )

    def get_voices_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        """Get the list of compatible voices for a specific TTS model.

        Returns:
            List of voice dicts with keys like 'id', 'name', 'gender', or empty list.
        """
        config = self.get_model_config(model_name)
        if config is None:
            return []
        voices = config.get("voices")
        if voices:
            return voices

        # Optional external file source for large voice catalogs.
        voices_source_file = config.get("voices_source_file")
        if not voices_source_file:
            return []

        source_path = Path(voices_source_file)
        if not source_path.is_absolute():
            # Prefer paths relative to app/config (same dir as models.json).
            config_relative_path = self.config_path.parent / voices_source_file
            if config_relative_path.exists():
                source_path = config_relative_path
            else:
                # Backward compatibility: also allow repo-root relative paths.
                source_path = self.config_path.parent.parent.parent / voices_source_file
        if not source_path.exists():
            return []

        try:
            raw = source_path.read_text(encoding="utf-8").strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # Accept Python-literal list dumps too.
                parsed = ast.literal_eval(raw)
        except Exception:
            return []

        if not isinstance(parsed, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            voice_id = item.get("id") or item.get("voice_id") or item.get("voiceId")
            if not voice_id:
                continue
            display_name = item.get("name") or item.get("displayName") or voice_id
            normalized.append(
                {
                    "id": str(voice_id),
                    "name": str(display_name),
                    "gender": str(item.get("gender") or "Unknown"),
                    "accent": str(item.get("accent") or "Unknown"),
                }
            )
        return normalized

    def get_tts_voices_by_provider(self, provider: ModelProvider) -> Dict[str, List[Dict[str, Any]]]:
        """Get voice options keyed by TTS model name for a given provider.

        Returns:
            Dict mapping model_name -> list of voice dicts.
        """
        if self._config is None:
            self._load_config()
        provider_str = provider.value
        result: Dict[str, List[Dict[str, Any]]] = {}
        for model_name, config in self._config.items():
            if model_name == "sample_spec":
                continue
            if config.get("provider") == provider_str and config.get("model_type") == "tts":
                voices = self.get_voices_for_model(model_name)
                if voices:
                    result[model_name] = voices
        return result


# Singleton instance
model_config_service = ModelConfigService()
