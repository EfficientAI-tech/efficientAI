"""
LLM service for generating text responses using various LLM providers.

Uses LiteLLM as a unified gateway so every provider (OpenAI, Anthropic,
Google, DeepSeek, Groq, Azure, AWS Bedrock, ...) is accessed through a
single interface. LiteLLM handles message-format translation, parameter
mapping, and endpoint selection (e.g. OpenAI Responses API vs Chat
Completions) automatically.
"""

import time
from typing import Optional, Dict, Any, List
from uuid import UUID

import litellm
from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import ModelProvider, AIProvider
from app.services.credentials import resolve_ai_provider

# LiteLLM will silently drop params the target provider doesn't support
# rather than raising an error.
litellm.drop_params = True

# Map our internal ModelProvider enum to the prefix LiteLLM expects.
_LITELLM_PROVIDER_PREFIX: Dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini",
    "azure": "azure",
    "aws": "bedrock",
    "deepseek": "deepseek",
    "groq": "groq",
}


class LLMService:
    """Service for generating text responses using various LLM providers."""

    def _get_ai_provider(
        self,
        provider: ModelProvider,
        db: Session,
        organization_id: UUID,
        credential_id: Optional[UUID] = None,
    ) -> Optional[AIProvider]:
        """Resolve the AIProvider row to use for this organization.

        Delegates to :func:`resolve_ai_provider` so that callers can pin a
        specific credential row when multiple keys exist for the same
        provider.
        """
        return resolve_ai_provider(
            provider, db, organization_id, credential_id=credential_id
        )

    @staticmethod
    def _litellm_model_name(provider: ModelProvider, model: str) -> str:
        """Build the ``provider/model`` string that LiteLLM expects."""
        provider_value = provider.value if hasattr(provider, "value") else str(provider)
        prefix = _LITELLM_PROVIDER_PREFIX.get(provider_value.lower(), provider_value.lower())
        return f"{prefix}/{model}"

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        llm_provider: ModelProvider,
        llm_model: str,
        organization_id: UUID,
        db: Session,
        temperature: Optional[float] = 0.7,
        max_tokens: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
        credential_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Generate a text response using the specified LLM via LiteLLM.

        ``credential_id`` lets callers pin a specific AIProvider row when an
        organization has multiple keys for the same provider; when omitted
        the resolver falls back to the row marked ``is_default`` (or the
        most recently updated active row for back-compat).
        """
        start_time = time.time()

        # --- resolve API key from database --------------------------------
        ai_provider = self._get_ai_provider(
            llm_provider, db, organization_id, credential_id=credential_id
        )
        if not ai_provider:
            raise RuntimeError(
                f"AI provider {llm_provider} not configured for this organization."
            )

        from app.core.encryption import decrypt_api_key

        try:
            api_key = decrypt_api_key(ai_provider.api_key)
        except Exception as e:
            raise RuntimeError(
                f"Failed to decrypt API key for provider {llm_provider}: {e}"
            )

        # --- call LiteLLM --------------------------------------------------
        model_str = self._litellm_model_name(llm_provider, llm_model)

        call_kwargs: Dict[str, Any] = {
            "model": model_str,
            "messages": messages,
            "api_key": api_key,
            "temperature": temperature,
        }
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens
        if config:
            call_kwargs.update(config)

        try:
            response = litellm.completion(**call_kwargs)
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            logger.error(f"[LLMService] LiteLLM call failed ({model_str}): {e}")
            raise RuntimeError(
                f"LLM generation failed for {model_str}: {e}\nDetails: {tb}"
            )

        # --- normalise response into our standard shape --------------------
        text = response.choices[0].message.content if response.choices else ""
        usage = getattr(response, "usage", None)

        result: Dict[str, Any] = {
            "text": text or "",
            "model": llm_model,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            },
            "raw_response": response,
            "processing_time": time.time() - start_time,
        }
        return result


# Singleton instance
llm_service = LLMService()
