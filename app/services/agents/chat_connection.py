"""Validation helpers for agent chat connection types."""

from __future__ import annotations

from typing import Any, Optional

from app.models.database import Agent
from app.models.enums import ChatConnectionTypeEnum


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


def normalized_chat_connection_type(agent: Agent) -> str:
    raw = getattr(agent, "chat_connection_type", None)
    return coerce_chat_connection_type(raw)


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
    if not agent_has_test_llm_config(agent):
        return "Chat agent requires test LLM credentials for the test agent leg."

    if conn == ChatConnectionTypeEnum.INTERNAL_LLM.value:
        main_provider = (getattr(agent, "main_llm_provider", None) or "").strip()
        main_model = (getattr(agent, "main_llm_model", None) or "").strip()
        test_provider = (getattr(agent, "test_llm_provider", None) or "").strip()
        test_model = (getattr(agent, "test_llm_model", None) or "").strip()
        if (main_provider and main_model) or (test_provider and test_model):
            return None
        if agent.voice_bundle_id:
            return None
        return (
            "Platform LLM chat agents require LLM credentials "
            "(test LLM or agent leg)."
        )

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

    return f"Unsupported chat connection type: {conn}"
