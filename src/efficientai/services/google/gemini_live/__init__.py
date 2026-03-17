"""Gemini Live services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for gemini_live submodules."""
    if name == "GeminiFileAPI":
        from .file_api import GeminiFileAPI
        return GeminiFileAPI
    elif name == "GeminiLiveLLMService":
        from .llm import GeminiLiveLLMService
        return GeminiLiveLLMService
    elif name == "GeminiLiveVertexLLMService":
        from .llm_vertex import GeminiLiveVertexLLMService
        return GeminiLiveVertexLLMService
    raise AttributeError(f"module 'efficientai.services.google.gemini_live' has no attribute '{name}'")
