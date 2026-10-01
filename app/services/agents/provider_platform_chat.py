"""Live text chat turns against voice platforms (Vapi chat API)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import Agent, Integration
from app.models.enums import IntegrationPlatform
from app.services.voice_providers import get_voice_provider

_RETELL_CHAT_422_HINT = (
    "Retell returned 422 for create-chat. Use a Retell chat agent ID "
    "(dashboard: create or convert to chat agent), not a voice-only agent ID. "
    "The API key must belong to the same Retell account as that agent."
)


def _provider_http_error(
    exc: httpx.HTTPStatusError,
    *,
    platform: str,
    operation: str,
) -> ValueError:
    detail = ""
    try:
        payload = exc.response.json()
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("detail") or "").strip()
    except Exception:
        detail = (exc.response.text or "").strip()[:500]
    base = detail or exc.response.reason_phrase or str(exc)
    if platform == IntegrationPlatform.RETELL.value and exc.response.status_code == 422:
        if operation == "create-chat":
            return ValueError(f"{_RETELL_CHAT_422_HINT} Retell: {base}")
    return ValueError(f"{platform} {operation} failed ({exc.response.status_code}): {base}")


@dataclass
class ProviderChatState:
    platform: str = ""
    vapi_session_id: Optional[str] = None
    vapi_previous_chat_id: Optional[str] = None
    retell_chat_id: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


def _last_user_utterance(transcript: list[dict[str, str]]) -> str:
    for entry in reversed(transcript):
        if (entry.get("speaker") or "").strip() == "Speaker 1":
            text = (entry.get("text") or "").strip()
            if text:
                return text
    return ""


def _extract_vapi_output(data: dict[str, Any]) -> str:
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    for key in ("message", "text", "content", "reply"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _vapi_chat_turn(
    api_key: str,
    assistant_id: str,
    user_input: str,
    state: ProviderChatState,
    *,
    timeout: float = 90.0,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base = "https://api.vapi.ai"
    with httpx.Client(timeout=timeout) as client:
        if not state.vapi_session_id and not state.vapi_previous_chat_id:
            session_resp = client.post(
                f"{base}/session",
                headers=headers,
                json={"assistantId": assistant_id},
            )
            session_resp.raise_for_status()
            session_data = session_resp.json()
            state.vapi_session_id = session_data.get("id") or session_data.get("sessionId")

        body: dict[str, Any] = {"input": user_input}
        if state.vapi_previous_chat_id:
            body["previousChatId"] = state.vapi_previous_chat_id
        elif state.vapi_session_id:
            body["sessionId"] = state.vapi_session_id
        else:
            body["assistantId"] = assistant_id

        chat_resp = client.post(f"{base}/chat", headers=headers, json=body)
        try:
            chat_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 402:
                raise ValueError(
                    "Vapi Chat API returned 402 Payment Required. "
                    "Vapi bills chat (POST /chat) separately from voice phone calls — "
                    "check chat credits/plan in the Vapi dashboard and use a chat-capable assistant ID."
                ) from exc
            raise _provider_http_error(
                exc, platform=IntegrationPlatform.VAPI.value, operation="chat"
            ) from exc
        chat_data = chat_resp.json()
        chat_id = chat_data.get("id")
        if isinstance(chat_id, str):
            state.vapi_previous_chat_id = chat_id
        reply = _extract_vapi_output(chat_data)
        if not reply:
            raise ValueError("Vapi chat returned an empty assistant message")
        return reply


def _extract_retell_agent_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    parts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").lower()
        if role not in ("agent", "assistant"):
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
    return " ".join(parts).strip()


def _retell_chat_turn(
    api_key: str,
    agent_id: str,
    user_input: str,
    state: ProviderChatState,
    *,
    timeout: float = 90.0,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base = "https://api.retellai.com"
    with httpx.Client(timeout=timeout) as client:
        if not state.retell_chat_id:
            session_resp = client.post(
                f"{base}/create-chat",
                headers=headers,
                json={"agent_id": agent_id},
            )
            try:
                session_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _provider_http_error(
                    exc, platform=IntegrationPlatform.RETELL.value, operation="create-chat"
                ) from exc
            session_data = session_resp.json()
            chat_id = session_data.get("chat_id") or session_data.get("id")
            if not isinstance(chat_id, str) or not chat_id.strip():
                raise ValueError("Retell create-chat did not return chat_id")
            state.retell_chat_id = chat_id.strip()

        chat_resp = client.post(
            f"{base}/create-chat-completion",
            headers=headers,
            json={"chat_id": state.retell_chat_id, "content": user_input},
        )
        try:
            chat_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _provider_http_error(
                exc, platform=IntegrationPlatform.RETELL.value, operation="create-chat-completion"
            ) from exc
        chat_data = chat_resp.json()
        reply = _extract_retell_agent_text(chat_data.get("messages"))
        if not reply:
            raise ValueError("Retell chat completion returned no agent message")
        state.extra["production_leg"] = "retell_chat"
        return reply


def close_provider_chat_session(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    state: ProviderChatState,
) -> None:
    """Best-effort teardown after an eval simulation (Retell end-chat, Vapi delete session)."""
    from app.services.agents.customer_websocket_chat import close_customer_websocket_session

    close_customer_websocket_session(state)

    elevenlabs_session = state.extra.get("_elevenlabs_convai_session")
    if elevenlabs_session is not None:
        try:
            elevenlabs_session.close()
        except Exception as exc:
            logger.warning("[ProviderChat] ElevenLabs convai close failed: {}", exc)
        state.extra.pop("_elevenlabs_convai_session", None)

    smallest_session = state.extra.get("_smallest_atoms_session")
    if smallest_session is not None:
        try:
            smallest_session.close()
        except Exception as exc:
            logger.warning("[ProviderChat] Smallest Atoms chat close failed: {}", exc)
        state.extra.pop("_smallest_atoms_session", None)

    if not state.retell_chat_id and not state.vapi_session_id:
        return
    if not agent.voice_ai_integration_id:
        return
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
        return
    platform = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else str(integration.platform)
    ).lower()
    api_key = decrypt_api_key(integration.api_key)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            if platform == IntegrationPlatform.RETELL.value and state.retell_chat_id:
                resp = client.patch(
                    f"https://api.retellai.com/end-chat/{state.retell_chat_id}",
                    headers=headers,
                )
                if resp.status_code not in (200, 204):
                    logger.warning(
                        "[ProviderChat] Retell end-chat {} returned {}",
                        state.retell_chat_id,
                        resp.status_code,
                    )
            elif platform == IntegrationPlatform.VAPI.value and state.vapi_session_id:
                resp = client.delete(
                    f"https://api.vapi.ai/session/{state.vapi_session_id}",
                    headers=headers,
                )
                if resp.status_code not in (200, 204):
                    logger.warning(
                        "[ProviderChat] Vapi delete session {} returned {}",
                        state.vapi_session_id,
                        resp.status_code,
                    )
    except Exception as exc:
        logger.warning("[ProviderChat] Session teardown failed (non-fatal): {}", exc)


def generate_provider_platform_reply(
    db: Session,
    *,
    agent: Agent,
    integration: Integration,
    transcript: list[dict[str, str]],
    state: ProviderChatState,
) -> str:
    platform = (integration.platform.value if hasattr(integration.platform, "value") else str(integration.platform)).lower()
    state.platform = platform
    assistant_id = (agent.voice_ai_agent_id or "").strip()
    if not assistant_id:
        raise ValueError("Provider chat agent is missing voice_ai_agent_id")

    user_input = _last_user_utterance(transcript)
    if not user_input:
        raise ValueError("No user message in transcript for provider chat turn")

    api_key = decrypt_api_key(integration.api_key)

    if platform == IntegrationPlatform.VAPI.value:
        state.extra["production_leg"] = "vapi_chat"
        return _vapi_chat_turn(api_key, assistant_id, user_input, state)

    if platform == IntegrationPlatform.RETELL.value:
        return _retell_chat_turn(api_key, assistant_id, user_input, state)

    if platform == IntegrationPlatform.ELEVENLABS.value:
        from app.services.agents.elevenlabs_convai_chat import (
            ElevenLabsConvaiSession,
            elevenlabs_convai_reply,
        )

        session = state.extra.get("_elevenlabs_convai_session")
        if session is None:
            session = ElevenLabsConvaiSession(api_key, assistant_id)
            conv_id = state.extra.get("elevenlabs_conversation_id")
            if isinstance(conv_id, str) and conv_id.strip():
                session.conversation_id = conv_id.strip()
            state.extra["_elevenlabs_convai_session"] = session

        reply, new_conv_id = elevenlabs_convai_reply(
            api_key,
            assistant_id,
            user_input,
            conversation_id=session.conversation_id,
            session=session,
        )
        if new_conv_id:
            state.extra["elevenlabs_conversation_id"] = new_conv_id
        state.extra["production_leg"] = "elevenlabs_convai"
        return reply

    if platform == IntegrationPlatform.SMALLEST.value:
        from app.services.agents.smallest_atoms_chat import (
            SmallestAtomsChatSession,
            smallest_atoms_chat_reply,
        )

        session = state.extra.get("_smallest_atoms_session")
        if session is None:
            session = SmallestAtomsChatSession(api_key, assistant_id)
            state.extra["_smallest_atoms_session"] = session

        reply, sm_meta = smallest_atoms_chat_reply(
            api_key,
            assistant_id,
            user_input,
            session=session,
        )
        state.extra.update(sm_meta)
        state.extra["production_leg"] = "smallest_atoms_chat"
        return reply

    get_voice_provider(platform)
    prompt = (agent.provider_prompt or agent.description or "").strip()
    if not prompt:
        raise ValueError("Provider chat fallback requires a production prompt on the agent")

    from app.services.agents.chat_llm_config import resolve_simulation_llm
    from app.services.ai.llm_service import llm_service

    main_llm = resolve_simulation_llm(
        db, agent=agent, organization_id=agent.organization_id, leg="main"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_input},
    ]
    result = llm_service.generate_response(
        messages=messages,
        llm_provider=main_llm.provider,
        llm_model=main_llm.model,
        organization_id=agent.organization_id,
        db=db,
        llm_config=main_llm.llm_config,
        credential_id=main_llm.credential_id,
        task_defaults={"temperature": 0.7, "max_tokens": 400},
    )
    text = (result.get("text") or "").strip()
    if not text:
        raise ValueError(f"Provider {platform} has no native chat API; LLM fallback returned empty")
    state.extra["production_leg"] = f"{platform}_llm_fallback"
    logger.warning(
        "[ProviderChat] Platform {} has no live chat API in EfficientAI; used LLM fallback",
        platform,
    )
    return text
