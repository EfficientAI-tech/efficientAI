#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Deepgram services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for deepgram submodules."""
    if name == "DeepgramSTTService":
        from .stt import DeepgramSTTService
        return DeepgramSTTService
    elif name == "DeepgramTTSService":
        from .tts import DeepgramTTSService
        return DeepgramTTSService
    elif name == "synthesize_deepgram_bytes":
        from .http_tts import synthesize_deepgram_bytes
        return synthesize_deepgram_bytes
    raise AttributeError(f"module 'efficientai.services.deepgram' has no attribute '{name}'")
