"""Validation helpers for agent chat connection types."""

from __future__ import annotations

from typing import Any, Optional

from app.models.database import Agent
from app.models.enums import CallMediumEnum, ChatConnectionTypeEnum


def coerce_chat_connection_type(raw: Any) -> str:
    """Return a canonical chat_connection_type value (e.g. internal_llm)."""
    if raw is None:
        return ChatConnectionTypeEnum.INTERNAL_LLM.value
    if isinstance(raw, ChatConnectionTypeEnum):
        return raw.value
    if hasattr(raw, "value") and not isinstance(raw, str):
        return coerce_chat_connection_type(raw.value)

    text = str(raw).strip()
    if not text:
        return ChatConnectionTypeEnum.INTERNAL_LLM.value

    lower = text.lower()
    for member in ChatConnectionTypeEnum:
        if lower == member.value:
            return member.value

    if "." in lower:
        suffix = lower.rsplit(".", 1)[-1]
        for member in ChatConnectionTypeEnum:
            if suffix == member.value:
                return member.value

    return lower


def _is_chat_medium(agent: Agent) -> bool:
    raw = getattr(agent, "call_medium", None)
    if raw is None:
        return False
    if hasattr(raw, "value") and not isinstance(raw, str):
        raw = raw.value
    return str(raw).lower() == CallMediumEnum.CHAT.value


def _has_platform_chat_link(agent: Agent) -> bool:
    return bool(
        agent.voice_ai_integration_id and (agent.voice_ai_agent_id or "").strip()
    )


def normalized_chat_connection_type(agent: Agent) -> str:
    """Resolve connection type; trust stored enum, infer only when type was never set."""
    raw = getattr(agent, "chat_connection_type", None)
    conn = coerce_chat_connection_type(raw)
    if not _is_chat_medium(agent):
        return conn

    if raw is not None and str(raw).strip():
        return conn

    cfg = chat_connection_config(agent)
    has_platform = _has_platform_chat_link(agent)
    has_api = bool((cfg.get("api_base_url") or "").strip())
    channel = (cfg.get("messaging_channel") or "").strip().lower()
    has_messaging = channel in ("whatsapp", "sms")

    if has_platform:
        return ChatConnectionTypeEnum.PROVIDER_CHAT.value
    if has_api:
        return ChatConnectionTypeEnum.CUSTOMER_API.value
    if has_messaging:
        return ChatConnectionTypeEnum.MESSAGING_CHANNELS.value
    return conn


def chat_connection_config(agent: Agent) -> dict[str, Any]:
    cfg = getattr(agent, "chat_connection_config", None)
    return cfg if isinstance(cfg, dict) else {}


def agent_has_test_llm_config(agent: Agent) -> bool:
    test_provider = (getattr(agent, "test_llm_provider", None) or "").strip()
    test_model = (getattr(agent, "test_llm_model", None) or "").strip()
    if test_provider and test_model:
        return True
    main_provider = (getattr(agent, "main_llm_provider", None) or "").strip()
    main_model = (getattr(agent, "main_llm_model", None) or "").strip()
    return bool(main_provider and main_model)


def validate_chat_connection_for_agent(agent: Agent) -> Optional[str]:
    """Return error message if chat agent cannot run simulation, else None."""
    conn = normalized_chat_connection_type(agent)

    if conn == ChatConnectionTypeEnum.PROVIDER_CHAT.value:
        if not agent.voice_ai_integration_id or not (agent.voice_ai_agent_id or "").strip():
            return "Provider chat agents require a voice platform integration and provider agent ID."
        prompt = (agent.provider_prompt or agent.description or "").strip()
        if len(prompt.split()) < 3:
            return "Provider chat agents require a production prompt (at least 3 words)."
        return None

    if conn == ChatConnectionTypeEnum.CUSTOMER_API.value:
        cfg = chat_connection_config(agent)
        if not (cfg.get("api_base_url") or "").strip():
            return "Customer API agents require api_base_url in chat_connection_config."
        return None

    if conn == ChatConnectionTypeEnum.MESSAGING_CHANNELS.value:
        cfg = chat_connection_config(agent)
        channel = (cfg.get("messaging_channel") or "").strip()
        if channel not in ("whatsapp", "sms"):
            return "Messaging agents require messaging_channel (whatsapp or sms)."
        return None

    if conn == ChatConnectionTypeEnum.INTERNAL_LLM.value:
        main_provider = (getattr(agent, "main_llm_provider", None) or "").strip()
        main_model = (getattr(agent, "main_llm_model", None) or "").strip()
        if main_provider and main_model:
            return None
        if agent.voice_bundle_id:
            return None
        return "LLM chat agents require chat agent LLM credentials (main LLM)."

    return f"Unsupported chat connection type: {conn}"
