#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""ElevenLabs services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for elevenlabs submodules."""
    if name == "ElevenLabsRealtimeSTTService":
        from .stt import ElevenLabsRealtimeSTTService
        return ElevenLabsRealtimeSTTService
    elif name in ("ElevenLabsTTSService", "ElevenLabsHttpTTSService"):
        from .tts import ElevenLabsTTSService, ElevenLabsHttpTTSService
        if name == "ElevenLabsTTSService":
            return ElevenLabsTTSService
        return ElevenLabsHttpTTSService
    elif name == "synthesize_elevenlabs_bytes":
        from .http_tts import synthesize_elevenlabs_bytes
        return synthesize_elevenlabs_bytes
    raise AttributeError(f"module 'efficientai.services.elevenlabs' has no attribute '{name}'")
