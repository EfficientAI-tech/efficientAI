"""Is the copilot usable for this org? It runs on the org's own LLM credential.

Ready means: the feature is on, the org has an active default AI provider, and
its model can call tools (or we can't tell, in which case we allow it and warn;
gateway and custom models are often unknown to LiteLLM's model map).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.services.ai.llm_resolver import OrgDefaultLLM, resolve_org_default_llm
from app.services.copilot.registry import LLMChoice

TOOL_CALLING_SUPPORTED = "supported"
TOOL_CALLING_UNSUPPORTED = "unsupported"
TOOL_CALLING_UNKNOWN = "unknown"


@dataclass
class Reason:
    code: str
    message: str


@dataclass
class Readiness:
    ready: bool
    reasons: list[Reason] = field(default_factory=list)
    warnings: list[Reason] = field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None
    credential_id: Optional[UUID] = None
    credential_name: Optional[str] = None
    tool_calling: Optional[str] = None
    llm: Optional[LLMChoice] = None

    def public(self) -> dict:
        out = asdict(self)
        out.pop("llm", None)
        return out


def tool_calling_support(provider: str, model: str) -> str:
    try:
        import litellm

        supported = litellm.supports_function_calling(model=f"{provider}/{model}")
    except Exception as exc:  # unknown model, custom provider, gateway alias
        logger.debug("[Copilot] tool-calling support unknown for {}/{}: {}", provider, model, exc)
        return TOOL_CALLING_UNKNOWN
    return TOOL_CALLING_SUPPORTED if supported else TOOL_CALLING_UNSUPPORTED


def check_readiness(db: Session, organization_id: UUID) -> Readiness:
    if not settings.COPILOT_ENABLED:
        return Readiness(
            ready=False,
            reasons=[Reason("disabled", "The assistant is turned off on this deployment.")],
        )
    try:
        default: Optional[OrgDefaultLLM] = resolve_org_default_llm(db, organization_id)
    except Exception as exc:  # unsupported provider string, no default model
        logger.warning("[Copilot] default LLM unusable for org {}: {}", organization_id, exc)
        return Readiness(
            ready=False,
            reasons=[Reason(
                "llm_unusable",
                "Your default AI provider can't be used by the assistant. "
                "Pick another default in Settings → AI Providers.",
            )],
        )
    if default is None:
        return Readiness(
            ready=False,
            reasons=[Reason(
                "no_llm",
                "Connect an LLM to use the assistant. Add one in Settings → AI Providers.",
            )],
        )

    provider = default.provider.value
    support = tool_calling_support(provider, default.model)
    result = Readiness(
        ready=support != TOOL_CALLING_UNSUPPORTED,
        provider=provider,
        model=default.model,
        credential_id=default.credential.id,
        credential_name=default.credential.name,
        tool_calling=support,
        llm=LLMChoice(provider=default.provider, model=default.model, credential_id=default.credential.id),
    )
    if support == TOOL_CALLING_UNSUPPORTED:
        result.reasons.append(Reason(
            "model_no_tools",
            f"{default.model} can't call tools, which the assistant needs. "
            "Choose a different default model in Settings → AI Providers.",
        ))
    elif support == TOOL_CALLING_UNKNOWN:
        result.warnings.append(Reason(
            "model_tools_unknown",
            f"We couldn't confirm that {default.model} supports tool calling. "
            "If answers look wrong, switch to a model that does.",
        ))
    return result
