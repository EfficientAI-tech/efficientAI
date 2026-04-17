"""Smallest.ai services - lazy imports to defer optional dependencies."""


def __getattr__(name):
    if name == "SmallestSTTService":
        from .stt import SmallestSTTService

        return SmallestSTTService
    if name == "SmallestTTSService":
        from .tts import SmallestTTSService

        return SmallestTTSService
    if name == "synthesize_smallest_bytes":
        from .http_tts import synthesize_smallest_bytes

        return synthesize_smallest_bytes
    raise AttributeError(f"module 'efficientai.services.smallest' has no attribute '{name}'")
