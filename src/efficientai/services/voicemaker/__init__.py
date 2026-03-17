"""VoiceMaker services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for voicemaker submodules."""
    if name == "synthesize_voicemaker_bytes":
        from .http_tts import synthesize_voicemaker_bytes
        return synthesize_voicemaker_bytes
    if name == "VoiceMakerTTSService":
        from .tts import VoiceMakerTTSService
        return VoiceMakerTTSService
    raise AttributeError(f"module 'efficientai.services.voicemaker' has no attribute '{name}'")
