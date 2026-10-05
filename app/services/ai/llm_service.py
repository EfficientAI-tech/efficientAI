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
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import litellm
from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import ModelProvider, AIProvider
from app.services.credentials import resolve_ai_provider, resolve_integration
from app.services.ai.llm_generation_config import build_litellm_kwargs
from app.services.ai.openrouter_jev import (
    call_openrouter_systemone,
    call_systemone,
    extract_jev_payload,
    gateway_systemone_url,
    is_openrouter_jev_model,
    normalize_typesafe_model_id,
    systemone_response_to_text,
)
from app.services.ai.llm_gateway import (
    apply_llm_gateway,
    resolve_effective_routing,
    resolve_litellm_api_key,
    resolve_litellm_model,
    routing_context_from_ai_provider,
    routing_context_from_integration,
    CredentialRoutingContext,
)

# LiteLLM will silently drop params the target provider doesn't support
# rather than raising an error.
litellm.drop_params = True

_TOGETHER_TEV_DIRECT_CTX = CredentialRoutingContext(routing_mode="direct")


def _requires_direct_together_tev(provider_value: str, llm_model: str | None) -> bool:
    """Together Tev must hit Together's API with the org's Together key."""
    if (provider_value or "").lower() != "together":
        return False
    return "tev" in (llm_model or "").lower()


def canonical_litellm_model_id(model_str: str) -> str:
    """Normalize provider prefixes on the final model string passed to LiteLLM."""
    from app.services.ai.together_models import normalize_together_model_name

    text = (model_str or "").strip()
    if not text:
        return text
    lower = text.lower()
    if lower.startswith("together/") or lower.startswith("together_ai/"):
        prefix = "together_ai"
        body = text.split("/", 1)[1]
        return f"{prefix}/{normalize_together_model_name(body)}"
    if lower.startswith("meta-llama/"):
        return normalize_together_model_name(text)
    return text


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
    "together": "together_ai",
    "typesafe": "typesafe",
    "sarvam": "sarvam",
    "openrouter": "openrouter",
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


def _looks_like_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _normalize_azure_endpoint(raw: str) -> tuple[str, Optional[str]]:
    """Normalize Azure endpoint URLs for LiteLLM.

    Accepts resource roots and OpenAI-compatible v1 URLs such as
    ``https://resource.openai.azure.com/openai/v1/chat/completions``.
    Returns ``(api_base, api_version_hint)`` where ``api_version_hint`` is
    ``"v1"`` for Foundry / v1-compatible endpoints.
    """
    from urllib.parse import urlparse

    url = raw.strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")

    if "/openai/v1" in url.lower():
        parsed = urlparse(url)
        resource_root = f"{parsed.scheme}://{parsed.netloc}"
        return resource_root, "v1"

    parsed = urlparse(url)
    if parsed.netloc.lower().endswith(".openai.azure.com"):
        return url, "v1"

    return url, None


def _azure_openai_v1_api_base(resource_root: str) -> str:
    """Build the OpenAI-compatible v1 base URL for Azure Foundry."""
    base = resource_root.rstrip("/")
    if base.lower().endswith("/openai/v1"):
        return base
    return f"{base}/openai/v1"


def _azure_uses_openai_v1_routing(api_version: Optional[str], version_hint: Optional[str]) -> bool:
    resolved = (api_version or version_hint or "").strip().lower()
    return resolved == "v1"


def _resolve_azure_endpoint_from_provider(
    ai_provider: Optional[AIProvider],
    config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Resolve Azure OpenAI endpoint from call config or credential row."""
    extra = config or {}
    azure_endpoint = extra.get("azure_endpoint") or extra.get("api_base")
    if azure_endpoint:
        return str(azure_endpoint).strip()
    if ai_provider:
        endpoint_url = getattr(ai_provider, "endpoint_url", None)
        if endpoint_url and str(endpoint_url).strip():
            return str(endpoint_url).strip()
        if ai_provider.name and _looks_like_url(ai_provider.name.strip()):
            return ai_provider.name.strip()
    return None


def _azure_has_direct_endpoint(
    ai_provider: Optional[AIProvider],
    config: Optional[Dict[str, Any]],
) -> bool:
    return _resolve_azure_endpoint_from_provider(ai_provider, config) is not None


def _build_azure_litellm_kwargs(
    ai_provider: Optional[AIProvider],
    config: Optional[Dict[str, Any]],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]], bool]:
    """Inject Azure OpenAI endpoint kwargs for direct (non-gateway) calls.

    Returns ``(litellm_kwargs, remaining_config, uses_openai_v1_routing)``.
    Foundry / v1 endpoints use the OpenAI-compatible ``/openai/v1`` path and
    must not pass ``azure_endpoint`` (the v1 API rejects it).
    """
    extra = dict(config or {})
    azure_endpoint = extra.pop("azure_endpoint", None) or extra.pop("api_base", None)
    api_version = extra.pop("api_version", None)

    if not azure_endpoint:
        azure_endpoint = _resolve_azure_endpoint_from_provider(ai_provider, None)

    if not azure_endpoint:
        return {}, extra or None, False

    api_base, version_hint = _normalize_azure_endpoint(azure_endpoint)
    if _azure_uses_openai_v1_routing(api_version, version_hint):
        return (
            {"api_base": _azure_openai_v1_api_base(api_base)},
            extra or None,
            True,
        )

    return (
        {
            "api_base": api_base,
            "azure_endpoint": api_base,
            "api_version": api_version or version_hint or "2024-08-01-preview",
        },
        extra or None,
        False,
    )


def _normalize_openai_compatible_api_base(raw: str) -> str:
    """Normalize a user-supplied OpenAI-compatible base URL for LiteLLM."""
    url = (raw or "").strip().rstrip("/")
    if not url:
        return url
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/completions",
        "/completions",
    ):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    parsed = urlparse(url)
    path = (parsed.path or "").rstrip("/")
    if not path.endswith("/v1"):
        if path in ("", "/"):
            path = "/v1"
        elif not path.endswith("/v1"):
            path = f"{path}/v1"
    return urlunparse(parsed._replace(path=path))


def _openai_compatible_model_from_custom(model: str) -> str:
    """Map ``custom/typesafe/jev-1.13.0`` to ``openai/typesafe/jev-1.13.0``."""
    normalized = (model or "").strip()
    if normalized.startswith("custom/"):
        normalized = normalized[len("custom/") :]
    if normalized.startswith("openai/"):
        return normalized
    return f"openai/{normalized}"


def _apply_direct_custom_provider_kwargs(
    call_kwargs: Dict[str, Any],
    *,
    ai_provider: AIProvider,
) -> Dict[str, Any]:
    """Apply ``endpoint_url`` for org Custom integrations (OpenAI-compatible)."""
    if call_kwargs.get("api_base"):
        return call_kwargs

    endpoint = (getattr(ai_provider, "endpoint_url", None) or "").strip()
    if not endpoint:
        endpoint = (getattr(ai_provider, "gateway_base_url", None) or "").strip()
    if not endpoint:
        return call_kwargs

    result = dict(call_kwargs)
    result["api_base"] = _normalize_openai_compatible_api_base(endpoint)
    model = str(result.get("model") or "")
    if model.startswith("custom/") or "/" in model:
        result["model"] = _openai_compatible_model_from_custom(model)
        result["custom_llm_provider"] = "openai"
    return result


def _azure_deployment_name(catalog_model: str) -> str:
    """Map Azure catalog keys to LiteLLM deployment names.

    Catalog entries use an ``azure-`` prefix to avoid colliding with
    OpenAI keys in ``models.json``. LiteLLM expects the actual Azure
    deployment name (e.g. ``gpt-5-mini``), not the catalog alias.
    """
    if catalog_model == "azure-openai-gpt4":
        return "gpt-4"
    if catalog_model.startswith("azure-"):
        return catalog_model[len("azure-") :]
    return catalog_model


def _record_generate_response_usage(
    result: Dict[str, Any],
    *,
    llm_model: str,
    organization_id: UUID,
    raw_response: Any = None,
    usage: Any = None,
) -> None:
    """Persist token usage for billing rollups (best-effort)."""
    try:
        from app.services.usage.context import (
            LLMUsageProductSection,
            ensure_usage_context,
            reset_usage_context,
        )
        from app.services.usage.normalize import (
            normalize_llm_usage,
            usage_snapshot_is_billable,
        )
        from app.services.usage.llm_usage import record_llm_usage

        usage_token = ensure_usage_context(
            organization_id,
            product_section=LLMUsageProductSection.OTHER,
        )
        try:
            snapshot = normalize_llm_usage(raw_response=raw_response, usage=usage)
            result["usage"]["cache_read_tokens"] = snapshot.cache_read_tokens
            result["usage"]["cache_creation_tokens"] = snapshot.cache_creation_tokens
            result["usage"]["reasoning_tokens"] = snapshot.reasoning_tokens
            if usage_snapshot_is_billable(snapshot):
                record_llm_usage(
                    llm_model, snapshot, organization_id=organization_id
                )
        finally:
            if usage_token is not None:
                reset_usage_context(usage_token)
    except Exception as exc:
        logger.debug("llm usage record skipped: {}", exc)


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

    def _resolve_credential_context(
        self,
        llm_provider: ModelProvider,
        db: Session,
        organization_id: UUID,
        credential_id: Optional[UUID] = None,
    ) -> Tuple[Optional[AIProvider], Optional[CredentialRoutingContext]]:
        """Resolve AIProvider or Integration row and its routing context."""
        ai_provider = self._get_ai_provider(
            llm_provider, db, organization_id, credential_id=credential_id
        )
        if ai_provider:
            return ai_provider, routing_context_from_ai_provider(ai_provider)

        provider_value = (
            llm_provider.value if hasattr(llm_provider, "value") else str(llm_provider)
        )
        integration = resolve_integration(
            provider_value, db, organization_id, credential_id=credential_id
        )
        if integration:
            return None, routing_context_from_integration(integration)

        return None, None

    def _resolve_api_key(
        self,
        provider: ModelProvider,
        db: Session,
        organization_id: UUID,
        credential_id: Optional[UUID] = None,
    ) -> str:
        """Resolve and decrypt an API key from AIProvider or Integration tables."""
        from app.core.encryption import decrypt_api_key

        ai_provider = self._get_ai_provider(
            provider, db, organization_id, credential_id=credential_id
        )
        if ai_provider:
            try:
                return decrypt_api_key(ai_provider.api_key)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to decrypt API key for provider {provider}: {e}"
                )

        integration = resolve_integration(
            provider, db, organization_id, credential_id=credential_id
        )
        if integration:
            try:
                return decrypt_api_key(integration.api_key)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to decrypt API key for provider {provider}: {e}"
                )

        provider_label = provider.value if hasattr(provider, "value") else str(provider)
        raise RuntimeError(
            f"AI provider {provider_label} not configured for this organization."
        )

    @staticmethod
    def _litellm_model_name(provider: ModelProvider, model: str) -> str:
        """Build the ``provider/model`` string that LiteLLM expects."""
        provider_value = provider.value if hasattr(provider, "value") else str(provider)
        prefix = _LITELLM_PROVIDER_PREFIX.get(provider_value.lower(), provider_value.lower())
        if provider_value.lower() == "azure":
            model = _azure_deployment_name(model)
        if provider_value.lower() == "fireworks":
            from app.services.ai.fireworks_model_aliases import (
                resolve_fireworks_catalog_model,
            )

            model = resolve_fireworks_catalog_model(model)
            if not model.startswith("accounts/"):
                model = f"accounts/fireworks/models/{model}"
        if provider_value.lower() == "openrouter":
            normalized = model.strip()
            if normalized.lower().startswith("openrouter/"):
                return normalized
            return f"openrouter/{normalized}"
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
        llm_config: Optional[Dict[str, Any]] = None,
        override_llm_config: Optional[Dict[str, Any]] = None,
        task_defaults: Optional[Dict[str, Any]] = None,
        credential_id: Optional[UUID] = None,
        completion_extra: Optional[Dict[str, Any]] = None,
        on_text_delta: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a text response using the specified LLM via LiteLLM.

        When ``on_text_delta`` is given, the completion is streamed and the
        callback receives each visible text delta as it arrives (reasoning
        deltas are not forwarded). The return value is the same as the
        non-streaming call.

        ``credential_id`` lets callers pin a specific AIProvider row when an
        organization has multiple keys for the same provider; when omitted
        the resolver falls back to the row marked ``is_default`` (or the
        most recently updated active row for back-compat).

        Generation parameters resolve as:
        override_llm_config > llm_config/config > legacy temperature/max_tokens > task_defaults.
        """
        gen_kwargs = build_litellm_kwargs(
            llm_config=llm_config or config,
            override_llm_config=override_llm_config,
            legacy_temperature=temperature,
            legacy_max_tokens=max_tokens,
            task_defaults=task_defaults,
        )
        temperature = gen_kwargs["temperature"]
        max_tokens = gen_kwargs["max_tokens"]
        config = gen_kwargs["config"]

        start_time = time.time()

        # --- resolve API key from database --------------------------------
        ai_provider, credential_ctx = self._resolve_credential_context(
            llm_provider, db, organization_id, credential_id=credential_id
        )
        if ai_provider:
            api_key = resolve_litellm_api_key(
                organization_id,
                db,
                ai_provider,
                credential=credential_ctx,
            )
        else:
            api_key = self._resolve_api_key(
                llm_provider, db, organization_id, credential_id=credential_id
            )

        # --- call LiteLLM --------------------------------------------------
        workload_model_str = self._litellm_model_name(llm_provider, llm_model)
        _, effective_routing = resolve_effective_routing(
            organization_id, db, credential_ctx
        )
        model_str = canonical_litellm_model_id(
            resolve_litellm_model(
                workload_model_str=workload_model_str,
                gateway_active=effective_routing != "direct",
                credential=credential_ctx,
            )
        )

        call_kwargs: Dict[str, Any] = {
            "model": model_str,
            "messages": messages,
            "temperature": temperature,
        }
        if api_key is not None:
            call_kwargs["api_key"] = api_key
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

        provider_value = (
            llm_provider.value if hasattr(llm_provider, "value") else str(llm_provider)
        ).lower()
        remaining_config = config
        if provider_value == "azure":
            azure_kwargs, remaining_config, azure_v1_routing = _build_azure_litellm_kwargs(
                ai_provider, config
            )
            call_kwargs.update(azure_kwargs)
            if azure_v1_routing:
                model_str = f"openai/{_azure_deployment_name(llm_model)}"
                call_kwargs["model"] = model_str
        if remaining_config:
            call_kwargs.update(remaining_config)

        if _requires_direct_together_tev(provider_value, llm_model):
            # Tev uses Together's native chat API (see tev1 examples). LLM gateway
            # proxy settings strip provider keys or substitute placeholders, which
            # Together rejects with 401 invalid_api_key.
            if ai_provider and not call_kwargs.get("api_key"):
                tev_key = resolve_litellm_api_key(
                    organization_id,
                    db,
                    ai_provider,
                    credential=_TOGETHER_TEV_DIRECT_CTX,
                )
                if not tev_key:
                    raise RuntimeError(
                        "Together Tev requires a direct Together API key on this "
                        "credential. Gateway-managed keys are not supported for Tev."
                    )
                call_kwargs["api_key"] = tev_key
        else:
            call_kwargs = apply_llm_gateway(
                call_kwargs,
                organization_id=organization_id,
                db=db,
                model=model_str,
                credential=credential_ctx,
            )

        if provider_value == "custom" and ai_provider is not None:
            call_kwargs = _apply_direct_custom_provider_kwargs(
                call_kwargs,
                ai_provider=ai_provider,
            )
            model_str = str(call_kwargs.get("model") or model_str)

        if is_openrouter_jev_model(provider_value, llm_model):
            jev_payload = extract_jev_payload(messages, completion_extra)
            if jev_payload is None:
                raise RuntimeError(
                    f"OpenRouter Jev model {llm_model} requires structured "
                    "state/questions; chat/completions is not supported."
                )
            state, questions = jev_payload
            if effective_routing != "direct":
                # Honour the org's gateway: use its TypeSafe pass-through with the
                # gateway-routed auth (virtual/master key) and headers, never a
                # direct OpenRouter call that would bypass it.
                body = call_systemone(
                    url=gateway_systemone_url(str(call_kwargs.get("api_base") or "")),
                    api_key=str(call_kwargs.get("api_key") or ""),
                    model_id=normalize_typesafe_model_id(llm_model),
                    state=state,
                    questions=questions,
                    extra_headers=call_kwargs.get("extra_headers") or None,
                )
            else:
                if not api_key:
                    raise RuntimeError(
                        "OpenRouter Jev requires a direct API key on this credential."
                    )
                body = call_openrouter_systemone(
                    api_key=api_key,
                    model=llm_model,
                    state=state,
                    questions=questions,
                )
            from app.services.usage.normalize import normalize_llm_usage

            snapshot = normalize_llm_usage(raw_response=body)
            result = {
                "text": systemone_response_to_text(body),
                "model": llm_model,
                "finish_reason": "stop",
                "truncated": False,
                "usage": {
                    "prompt_tokens": snapshot.prompt_tokens,
                    "completion_tokens": snapshot.completion_tokens,
                    "total_tokens": snapshot.total_tokens,
                },
                "raw_response": body,
                "processing_time": time.time() - start_time,
            }
            _record_generate_response_usage(
                result,
                llm_model=llm_model,
                organization_id=organization_id,
                raw_response=body,
            )
            return result

        if completion_extra:
            for key, value in completion_extra.items():
                if value is not None:
                    call_kwargs[key] = value

        try:
            if on_text_delta is not None:
                response = _stream_completion(call_kwargs, messages, on_text_delta)
            else:
                response = litellm.completion(**call_kwargs)
        except Exception as e:
            logger.exception("[LLMService] LiteLLM call failed (%s)", model_str)
            raise RuntimeError(f"LLM generation failed for {model_str}: {e}") from e

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
        _record_generate_response_usage(
            result,
            llm_model=llm_model,
            organization_id=organization_id,
            raw_response=response,
        )
        return result


def _stream_completion(
    call_kwargs: Dict[str, Any],
    messages: List[Dict[str, str]],
    on_text_delta: Callable[[str], None],
) -> Any:
    """Run a streaming completion, forwarding text deltas, and rebuild the
    full response so callers and usage accounting see the usual shape."""
    stream = litellm.completion(
        **call_kwargs,
        stream=True,
        stream_options={"include_usage": True},
    )
    chunks = []
    for chunk in stream:
        chunks.append(chunk)
        choices = getattr(chunk, "choices", None) or []
        delta = getattr(choices[0], "delta", None) if choices else None
        content = getattr(delta, "content", None) if delta is not None else None
        if content:
            on_text_delta(content)
    return litellm.stream_chunk_builder(chunks, messages=messages)


# Singleton instance
llm_service = LLMService()
