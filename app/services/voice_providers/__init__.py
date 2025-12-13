"""
Voice Provider Services
Modular structure for integrating with different voice AI providers (Retell, Vapi, etc.)
"""
from app.services.voice_providers.base import BaseVoiceProvider
from app.services.voice_providers.retell import RetellVoiceProvider

__all__ = [
    "BaseVoiceProvider",
    "RetellVoiceProvider",
]

# Registry of voice providers by platform
VOICE_PROVIDERS = {
    "retell": RetellVoiceProvider,
    # Add more providers here as they are implemented
    # "vapi": VapiVoiceProvider,
}

def get_voice_provider(platform: str) -> type[BaseVoiceProvider]:
    """Get voice provider class for a given platform."""
    provider_class = VOICE_PROVIDERS.get(platform.lower())
    if not provider_class:
        raise ValueError(f"Voice provider for platform '{platform}' is not implemented")
    return provider_class

