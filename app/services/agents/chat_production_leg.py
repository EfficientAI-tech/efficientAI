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
from app.services.agents.chat_outbound_urls import assert_chat_connection_urls_safe
from app.services.agents.customer_api_chat import call_customer_chat_api
from app.services.agents.provider_platform_chat import ProviderChatState, generate_provider_platform_reply
from app.services.ai.llm_service import llm_service
from app.services.testing.simulation_prompts import build_agent_system_prompt
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
    """Use stored mode, or connection-type default (platform/API = live, internal LLM = sim)."""
    from app.services.agents.chat_preprod_scope import (
        POST_PROD_LIVE_EVAL_MODE,
        default_chat_eval_mode_for_connection,
    )

    conn = normalized_chat_connection_type(agent)
    raw = getattr(agent, "chat_eval_mode", None)
    if raw is None or not str(raw).strip():
        return default_chat_eval_mode_for_connection(conn)
    mode = str(raw).lower()
    if (
        mode == ChatEvalModeEnum.PRE_PROD_SIM.value
        and default_chat_eval_mode_for_connection(conn) == POST_PROD_LIVE_EVAL_MODE.value
    ):
        return POST_PROD_LIVE_EVAL_MODE.value
    return mode


def generate_internal_agent_reply(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    transcript: list[dict[str, str]],
) -> str:
    main_llm = resolve_simulation_llm(db, agent=agent, organization_id=organization_id, leg="main")
    agent_system = build_agent_system_prompt(agent)
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
    return text


def uses_live_production_leg(agent: Agent) -> bool:
    conn = normalized_chat_connection_type(agent)
    if conn == ChatConnectionTypeEnum.PROVIDER_CHAT.value:
        return True
    mode = normalized_chat_eval_mode(agent)
    if mode != ChatEvalModeEnum.POST_PROD_LIVE.value:
        return False
    return conn in (
        ChatConnectionTypeEnum.CUSTOMER_API.value,
        ChatConnectionTypeEnum.CUSTOMER_WEBSOCKET.value,
        ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
    )


def _fail_live_messaging(conn: str, leg: Optional[str], detail: str) -> None:
    raise ValueError(
        f"Live messaging production leg failed ({leg or 'unknown'}): {detail}. "
        "Eval will not fall back to LLM simulation."
    )


def _live_messaging_failure_detail(leg: Optional[str]) -> str:
    if not leg:
        return (
            "No production reply (check send credentials, recipient, inbound webhook, "
            "and messaging_sync_reply_url for send-only setups)"
        )
    if leg.startswith("messaging_send_failed:"):
        return leg.split(":", 1)[1]
    if leg.startswith("messaging_turn_wait_failed:"):
        return leg.split(":", 1)[1]
    if "concurrent_turn" in leg:
        return (
            "Another messaging eval turn is still pending for this agent and recipient. "
            "Wait about two minutes and try again, or run only one suite at a time."
        )
    leg_l = leg.lower()
    if "meta_whatsapp" in leg_l and "send_only" in leg_l:
        return (
            "WhatsApp was accepted by Meta but no reply was received in ~90s. "
            "Confirm the suite recipient is your real WhatsApp number (E.164, on Meta’s test list), "
            "you received the hello_world message, you replied on WhatsApp, and the inbound webhook is verified."
        )
    if "telnyx" in leg_l and "send_only" in leg_l:
        return (
            "Telnyx SMS was sent but no inbound production reply arrived in time (~90s). "
            "Reply by SMS to your Telnyx number with the agent answer and ensure the Telnyx "
            "inbound webhook URL is configured on the messaging profile."
        )
    if "send_only" in leg_l:
        return (
            "Outbound SMS was sent but no inbound production reply arrived in time (~90s). "
            "From the eval recipient phone, send an SMS reply to your Twilio From number with "
            "the agent answer. In Twilio Console set “A message comes in” to POST the agent’s "
            "inbound webhook URL (PUBLIC_BASE_URL/ngrok must reach this API)."
        )
    return (
        "No production reply (check send credentials, recipient, inbound webhook, "
        "and messaging_sync_reply_url for send-only setups)"
    )


def generate_production_chat_reply(
    db: Session,
    *,
    agent: Agent,
    organization_id: UUID,
    transcript: list[dict[str, str]],
    provider_state: ProviderChatState,
    evaluator_result: Optional[Any] = None,
) -> tuple[str, dict[str, Any]]:
    """Return assistant text and metadata to merge into evaluator call_data."""
    conn = normalized_chat_connection_type(agent)
    mode = normalized_chat_eval_mode(agent)
    meta: dict[str, Any] = {
        "chat_eval_mode": mode,
        "chat_connection_type": conn,
    }
    cfg_raw = chat_connection_config(agent)
    from app.config import settings

    assert_chat_connection_urls_safe(cfg_raw, allow_loopback=bool(settings.DEBUG))

    def _apply_run_messaging_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
        if not evaluator_result or not isinstance(getattr(evaluator_result, "call_data", None), dict):
            return cfg
        call_data = evaluator_result.call_data
        merged: dict[str, Any] | None = None
        recipient = call_data.get("run_messaging_recipient")
        if isinstance(recipient, str) and recipient.strip():
            merged = dict(cfg)
            merged["messaging_recipient"] = recipient.strip()
        trial_tpl = call_data.get("run_twilio_sms_trial_body_template")
        if "run_twilio_sms_trial_body_template" in call_data:
            merged = dict(merged if merged is not None else cfg)
            if isinstance(trial_tpl, str) and trial_tpl.strip():
                merged["twilio_sms_trial_body_template"] = trial_tpl.strip()
            else:
                merged.pop("twilio_sms_trial_body_template", None)
        return merged if merged is not None else cfg

    if conn == ChatConnectionTypeEnum.CUSTOMER_API.value:
        from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime

        cfg = chat_connection_config_for_runtime(cfg_raw)
        reply = call_customer_chat_api(
            cfg,
            transcript=transcript,
            agent_name=(agent.name or "Agent").strip(),
            language=str(agent.language or "en"),
        )
        meta["production_leg"] = "customer_api"
        return reply, meta

    if conn == ChatConnectionTypeEnum.CUSTOMER_WEBSOCKET.value:
        from app.services.agents.chat_connection_config_store import chat_connection_config_for_runtime
        from app.services.agents.customer_websocket_chat import call_customer_websocket_chat

        cfg = chat_connection_config_for_runtime(cfg_raw)
        reply = call_customer_websocket_chat(
            cfg,
            transcript=transcript,
            agent_name=(agent.name or "Agent").strip(),
            language=str(agent.language or "en"),
            state=provider_state,
        )
        meta["production_leg"] = "customer_websocket"
        return reply, meta

    if conn == ChatConnectionTypeEnum.PROVIDER_CHAT.value:
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
        from app.services.agents.messaging_channel_chat import (
            is_meta_whatsapp_live_cfg,
            run_meta_whatsapp_live_production_turn,
            try_messaging_worker_send,
        )

        cfg = _apply_run_messaging_overrides(chat_connection_config_for_runtime(cfg_raw))
        if is_meta_whatsapp_live_cfg(cfg, db=db, organization_id=organization_id):
            reply, leg = run_meta_whatsapp_live_production_turn(
                db,
                organization_id=organization_id,
                cfg=cfg,
                transcript=transcript,
                agent_id=agent.id,
                generate_agent_reply=lambda aug: generate_internal_agent_reply(
                    db,
                    agent=agent,
                    organization_id=organization_id,
                    transcript=aug,
                ),
            )
            if reply:
                meta["production_leg"] = leg
                return reply, meta
        else:
            reply, leg = try_messaging_worker_send(
                db,
                organization_id=organization_id,
                cfg=cfg,
                transcript=transcript,
                telephony_phone_number_id=getattr(agent, "telephony_phone_number_id", None),
                agent_id=agent.id,
            )
            if reply:
                meta["production_leg"] = leg
                return reply, meta

        webhook = (cfg.get("outbound_webhook_url") or cfg.get("messaging_webhook_url") or "").strip()
        if webhook:
            import httpx

            from app.services.agents.customer_api_chat import extract_reply_text

            assert_chat_connection_urls_safe({"outbound_webhook_url": webhook})
            from app.services.agents.chat_outbound_payload import messaging_webhook_request_body

            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    webhook,
                    json=messaging_webhook_request_body(
                        transcript=transcript,
                        channel=cfg.get("messaging_channel"),
                        sender_id=cfg.get("messaging_sender_id"),
                    ),
                )
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                reply = extract_reply_text(data) or resp.text.strip()
                if reply:
                    meta["production_leg"] = "messaging_webhook"
                    return reply, meta

        _fail_live_messaging(
            conn,
            leg,
            _live_messaging_failure_detail(leg),
        )

    if conn in (
        ChatConnectionTypeEnum.MESSAGING_CHANNELS.value,
        ChatConnectionTypeEnum.CUSTOMER_API.value,
        ChatConnectionTypeEnum.CUSTOMER_WEBSOCKET.value,
    ) and mode == ChatEvalModeEnum.POST_PROD_LIVE.value:
        raise ValueError(
            f"Live production chat ({conn}) could not complete this turn. "
            "Check agent connection settings and platform credentials."
        )

    try:
        text = generate_internal_agent_reply(
            db,
            agent=agent,
            organization_id=organization_id,
            transcript=transcript,
        )
    except RuntimeError as exc:
        main_llm = resolve_simulation_llm(db, agent=agent, organization_id=organization_id, leg="main")
        raise RuntimeError(
            f"Production-side LLM simulation failed ({main_llm.source}): {exc}"
        ) from exc
    main_llm = resolve_simulation_llm(db, agent=agent, organization_id=organization_id, leg="main")
    meta["production_leg"] = "internal_llm_sim"
    meta["main_llm_source"] = main_llm.source
    return text, meta
