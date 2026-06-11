"""
LLM service for generating text responses using various LLM providers.

Uses LiteLLM as a unified gateway so every provider (OpenAI, Anthropic,
Google, DeepSeek, Groq, Azure, AWS Bedrock, ...) is accessed through a
single interface. LiteLLM handles message-format translation, parameter
mapping, and endpoint selection (e.g. OpenAI Responses API vs Chat
Completions) automatically.
"""

import re
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
    "xai": "xai",
    "fireworks": "fireworks_ai",
}

# Matches the model-name half of the Gemini 2.5 family: ``gemini-2.5-pro``,
# ``gemini-2.5-flash``, ``gemini-2.5-flash-lite``, plus the ``-stt`` /
# ``-tts`` / ``-preview-XX-YYYY`` suffix variants. Anchored on a clean
# ``2.5`` token so future ``gemini-25-foo`` typos don't sneak in.
_GEMINI_25_RE = re.compile(r"(?:^|[/-])gemini-2\.5(?:[-.]|$)", re.IGNORECASE)

# Matches the Gemini 3 family: ``gemini-3-pro-preview``,
# ``gemini-3-flash-preview``, ``gemini-3.1-pro-preview``,
# ``gemini-3.2-flash``, etc. Loose on the minor version so 3.1 / 3.2 /
# next-month's-preview all route through the same thinking-policy
# branch without code edits.
_GEMINI_3_RE = re.compile(
    r"(?:^|[/-])gemini-3(?:\.\d+)?(?:[-.]|$)", re.IGNORECASE
)


def _gemini_family(model: str) -> Optional[str]:
    """Return ``"2.5"``, ``"3"``, or ``None`` for the given model name.

    Encapsulates the family detection in one place so the thinking-
    policy branch and the ``max_tokens`` floor branch can't drift out
    of sync. Returns ``None`` for non-Gemini models AND for older
    Gemini families (1.5 / 2.0) that don't need a thinking workaround
    because thinking either isn't a feature or is already off by
    default.
    """
    if not model:
        return None
    if _GEMINI_25_RE.search(model):
        return "2.5"
    if _GEMINI_3_RE.search(model):
        return "3"
    return None


def _gemini_thinking_kwargs(model: str) -> Dict[str, Any]:
    """Build the LiteLLM kwargs that minimise / disable thinking.

    The two Gemini "thinking" generations are controlled by
    **mutually exclusive** parameters — passing both makes Gemini 3
    return HTTP 400 — so this helper picks the right one per family:

    * **Gemini 2.5** (``thinkingBudget`` integer):
      - Flash / Flash-Lite: ``thinkingBudget=0`` fully disables
        thinking — ideal for structured-JSON workloads (diariser,
        evaluator) where chain-of-thought is wasted output budget.
      - Pro: cannot be disabled below ``128``; we still pass
        ``reasoning_effort="disable"`` so LiteLLM clamps to the
        provider minimum rather than the default ``8192``.
      The native ``thinking={type: disabled, budget_tokens: 0}``
      flag is sent alongside as belt-and-braces — LiteLLM honours
      whichever the installed Gemini SDK version understands.

    * **Gemini 3** (``thinkingLevel`` enum):
      - Flash: ``thinking_level="minimal"`` — the lowest setting the
        Flash variants accept (Pro doesn't expose ``MINIMAL``).
      - Pro: ``thinking_level="low"`` — the floor for Pro. Thinking
        cannot be fully disabled on Gemini 3 Pro.
      We send ONLY ``reasoning_effort`` (no native ``thinking={...}``)
      because Gemini 3 errors on the conflict. LiteLLM's
      cross-provider ``reasoning_effort`` switch maps the enum string
      to ``thinkingLevel`` for Gemini 3 and ``thinkingBudget`` for
      Gemini 2.5, so we get correct behaviour for both families
      through the same surface.

    Returns an empty dict for non-Gemini models or pre-2.5 Gemini
    models so the caller can ``call_kwargs.update(...)`` unconditionally.
    """
    family = _gemini_family(model)
    if family is None:
        return {}

    model_lower = (model or "").lower()
    is_pro = "pro" in model_lower
    is_flash = "flash" in model_lower

    if family == "2.5":
        kwargs: Dict[str, Any] = {
            # LiteLLM cross-provider switch → ``thinkingBudget=0``
            # for Gemini 2.5; silently dropped by other providers.
            "reasoning_effort": "disable",
            # Belt-and-braces: provider-native flag in case LiteLLM's
            # mapping has a stale signature for the installed SDK.
            "thinking": {"type": "disabled", "budget_tokens": 0},
        }
        return kwargs

    # family == "3"
    # Gemini 3 cannot be fully disabled and rejects the native
    # ``thinking={budget_tokens: 0}`` form, so we ONLY pass the
    # cross-provider ``reasoning_effort`` string here.
    if is_flash:
        return {"reasoning_effort": "minimal"}
    if is_pro:
        return {"reasoning_effort": "low"}
    # Unknown 3.x variant (e.g. a future ``gemini-3-nano``) — pick
    # the more conservative "low" so we never accidentally upgrade a
    # diariser/evaluator to HIGH thinking on a model we haven't
    # explicitly characterised.
    return {"reasoning_effort": "low"}


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
        if provider_value.lower() == "fireworks" and not model.startswith("accounts/"):
            model = f"accounts/fireworks/models/{model}"
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
        # Gemini "thinking" families (2.5 + 3.x) ship with reasoning
        # enabled by default. For structured-JSON workloads (the
        # diariser and evaluator) chain-of-thought is wasted output
        # budget — and on Gemini 2.5 it actively breaks parsing
        # because thinking tokens are deducted from ``max_output_tokens``,
        # so a tight budget gets consumed by reasoning and the visible
        # JSON is truncated mid-string (``finish_reason="length"``).
        # ``_gemini_thinking_kwargs`` picks the right minimisation
        # parameter for each family (``thinkingBudget`` vs
        # ``thinkingLevel``) and is a no-op for non-Gemini models.
        gemini_family = _gemini_family(llm_model)
        thinking_kwargs = _gemini_thinking_kwargs(llm_model)
        for key, value in thinking_kwargs.items():
            call_kwargs.setdefault(key, value)

        if max_tokens:
            # Gemini families with minimised-but-not-disabled thinking
            # still need a generous ceiling because some evaluation
            # prompts request many metrics + rationales. Bump the
            # caller-supplied cap to a sane floor so we don't keep
            # tripping ``finish_reason="length"``. Applies to both
            # Gemini 2.5 (where thinking can be 0 but the answer
            # itself can be long) and Gemini 3 (where ``MINIMAL`` /
            # ``LOW`` thinking still consumes some of the budget).
            effective_max_tokens = max_tokens
            if gemini_family is not None and effective_max_tokens < 4096:
                effective_max_tokens = 4096
            call_kwargs["max_tokens"] = effective_max_tokens
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
        finish_reason = (
            response.choices[0].finish_reason if response.choices else None
        )
        usage = getattr(response, "usage", None)

        # Surface output truncation clearly. Without this, callers (notably
        # the JSON parser for evaluator results) only see a cryptic
        # "Unterminated string" error and never learn the real cause.
        if finish_reason == "length":
            logger.warning(
                "[LLMService] {} returned finish_reason='length' "
                "(output truncated at max_tokens={}). "
                "Response will likely fail to parse as JSON.",
                model_str,
                call_kwargs.get("max_tokens"),
            )

        result: Dict[str, Any] = {
            "text": text or "",
            "model": llm_model,
            "finish_reason": finish_reason,
            "truncated": finish_reason == "length",
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
