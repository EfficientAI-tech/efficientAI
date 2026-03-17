#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""OpenAI services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for openai submodules."""
    if name == "OpenAILLMService":
        from .llm import OpenAILLMService
        return OpenAILLMService
    elif name == "OpenAISTTService":
        from .stt import OpenAISTTService
        return OpenAISTTService
    elif name == "OpenAITTSService":
        from .tts import OpenAITTSService
        return OpenAITTSService
    elif name == "OpenAIImageService":
        from .image import OpenAIImageService
        return OpenAIImageService
    elif name == "synthesize_openai_bytes":
        from .http_tts import synthesize_openai_bytes
        return synthesize_openai_bytes
    raise AttributeError(f"module 'efficientai.services.openai' has no attribute '{name}'")
