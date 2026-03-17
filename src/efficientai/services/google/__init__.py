#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Google services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for google submodules."""
    if name == "GoogleLLMService":
        from .llm import GoogleLLMService
        return GoogleLLMService
    elif name == "GoogleLLMOpenAIService":
        from .llm_openai import GoogleLLMOpenAIService
        return GoogleLLMOpenAIService
    elif name == "GoogleLLMVertexService":
        from .llm_vertex import GoogleLLMVertexService
        return GoogleLLMVertexService
    elif name == "GoogleSTTService":
        from .stt import GoogleSTTService
        return GoogleSTTService
    elif name == "GoogleTTSService":
        from .tts import GoogleTTSService
        return GoogleTTSService
    elif name == "GoogleImageService":
        from .image import GoogleImageService
        return GoogleImageService
    elif name == "synthesize_google_bytes":
        from .http_tts import synthesize_google_bytes
        return synthesize_google_bytes
    elif name in ("GeminiLiveLLMService",):
        from .gemini_live import GeminiLiveLLMService
        return GeminiLiveLLMService
    raise AttributeError(f"module 'efficientai.services.google' has no attribute '{name}'")
