"""Production-side chat reply for evaluator simulation (pre-prod and post-prod live)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, Integration
from app.models.enums import ChatConnectionTypeEnum, ChatEvalModeEnum
from app.services.agents.chat_connection import (
    chat_connection_config,
    normalized_chat_connection_type,
)
from app.services.agents.chat_llm_config import resolve_simulation_llm
from app.services.agents.customer_api_chat import call_customer_chat_api
from app.services.agents.provider_platform_chat import ProviderChatState, generate_provider_platform_reply
from app.services.ai.llm_service import llm_service
from app.services.testing.test_agent_simulation_prompt import is_chat_agent


def _agent_messages(system_prompt: str, transcript: list[dict[str, str]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for entry in transcript:
        speaker = entry.get("speaker")
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        if speaker == "Speaker 2":
            messages.append({"role": "assistant", "content": text})
        else:
            messages.append({"role": "user", "content": text})
    return messages


def normalized_chat_eval_mode(agent: Agent) -> str:
    raw = getattr(agent, "chat_eval_mode", None) or ChatEvalModeEnum.PRE_PROD_SIM.value
    return str(raw).lower()


def uses_live_production_leg(agent: Agent) -> bool:
    mode = normalized_chat_eval_mode(agent)
    if mode != ChatEvalModeEnum.POST_PROD_LIVE.value:
        return False
    conn = normalized_chat_connection_type(agent)
    return conn in (
        ChatConnectionTypeEnum.PROVIDER_CHAT.value,
        ChatConnectionTypeEnum.CUSTOMER_API.value,
        ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
    )


def generate_production_chat_reply(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    transcript: list[dict[str, str]],
    provider_state: ProviderChatState,
) -> tuple[str, dict[str, Any]]:
    """Return assistant text and metadata to merge into evaluator call_data."""
    conn = normalized_chat_connection_type(agent)
    mode = normalized_chat_eval_mode(agent)
    meta: dict[str, Any] = {
        "chat_eval_mode": mode,
        "chat_connection_type": conn,
    }

    if conn == ChatConnectionTypeEnum.CUSTOMER_API.value:
        from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime

        cfg = chat_connection_config_for_runtime(chat_connection_config(agent))
        reply = call_customer_chat_api(
            cfg,
            transcript=transcript,
            agent_name=(agent.name or "Agent").strip(),
            language=str(agent.language or "en"),
        )
        meta["production_leg"] = "customer_api"
        return reply, meta

    if conn == ChatConnectionTypeEnum.PROVIDER_CHAT.value and mode == ChatEvalModeEnum.POST_PROD_LIVE.value:
        if not agent.voice_ai_integration_id:
            raise ValueError("Provider chat requires voice_ai_integration_id")
        integration = (
            db.query(Integration)
            .filter(
                Integration.id == agent.voice_ai_integration_id,
                Integration.organization_id == organization_id,
                Integration.is_active == True,
            )
            .first()
        )
        if not integration:
            raise ValueError("Voice platform integration not found or inactive")
        reply = generate_provider_platform_reply(
            db,
            agent=agent,
            integration=integration,
            transcript=transcript,
            state=provider_state,
        )
        meta["production_leg"] = provider_state.extra.get("production_leg") or f"provider_{provider_state.platform}"
        if provider_state.vapi_session_id:
            meta["vapi_session_id"] = provider_state.vapi_session_id
        if provider_state.vapi_previous_chat_id:
            meta["vapi_previous_chat_id"] = provider_state.vapi_previous_chat_id
        return reply, meta

    if conn == ChatConnectionTypeEnum.MESSAGING_CHANNELS.value and mode == ChatEvalModeEnum.POST_PROD_LIVE.value:
        from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime
        from app.services.agents.messaging_channel_chat import try_messaging_worker_send

        cfg = chat_connection_config_for_runtime(chat_connection_config(agent))
        reply, leg = try_messaging_worker_send(
            db,
            organization_id=organization_id,
            cfg=cfg,
            transcript=transcript,
        )
        if reply:
            meta["production_leg"] = leg
            return reply, meta
        if leg and not leg.startswith("messaging_skip"):
            meta["production_leg"] = leg

        webhook = (cfg.get("outbound_webhook_url") or cfg.get("messaging_webhook_url") or "").strip()
        if webhook:
            import httpx

            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    webhook,
                    json={
                        "messages": transcript,
                        "channel": cfg.get("messaging_channel"),
                        "sender_id": cfg.get("messaging_sender_id"),
                    },
                )
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                from app.services.agents.customer_api_chat import extract_reply_text

                reply = extract_reply_text(data) or resp.text.strip()
                if reply:
                    meta["production_leg"] = "messaging_webhook"
                    return reply, meta

    from app.services.testing.llm_to_llm_evaluator_simulation import _build_agent_system_prompt

    main_llm = resolve_simulation_llm(db, agent=agent, organization_id=organization_id, leg="main")
    agent_system = _build_agent_system_prompt(agent)
    messages = _agent_messages(agent_system, transcript)
    result = llm_service.generate_response(
        messages=messages,
        llm_provider=main_llm.provider,
        llm_model=main_llm.model,
        organization_id=organization_id,
        db=db,
        llm_config=main_llm.llm_config,
        credential_id=main_llm.credential_id,
        task_defaults={"temperature": 0.7, "max_tokens": 400},
    )
    text = (result.get("text") or "").strip()
    if not text:
        raise ValueError("Production LLM returned an empty message")
    meta["production_leg"] = "internal_llm_sim"
    meta["main_llm_source"] = main_llm.source
    if is_chat_agent(agent) and conn == ChatConnectionTypeEnum.MESSAGING_CHANNELS.value:
        meta["production_leg"] = "messaging_llm_sim"
    if conn == ChatConnectionTypeEnum.PROVIDER_CHAT.value:
        meta["production_leg"] = "provider_prompt_llm_sim"
    return text, meta
