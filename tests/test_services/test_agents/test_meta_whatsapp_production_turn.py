from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.agents.messaging_channel_chat import (
    meta_whatsapp_prod_mode,
    run_meta_whatsapp_live_production_turn,
)


def test_meta_whatsapp_prod_mode_defaults_manual():
    assert meta_whatsapp_prod_mode({}) == "manual_inbound"
    assert meta_whatsapp_prod_mode({"meta_whatsapp_prod_mode": "simulated_llm"}) == "simulated_llm"


@patch(
    "app.services.agents.chat_messaging_turn_wait.wait_messaging_sms_reply_or_raise",
    return_value="Sure, I can help.",
)
@patch(
    "app.services.agents.chat_messaging_turn_wait.register_messaging_sms_turn",
    return_value="turn-1",
)
@patch("app.services.agents.messaging_channel_chat._send_meta_whatsapp_text")
@patch("app.services.agents.messaging_channel_chat._send_meta_whatsapp")
@patch("app.services.agents.messaging_channel_chat._resolve_messaging_meta_whatsapp_context")
@patch(
    "app.services.telephony.meta_whatsapp_webhook_setup.ensure_meta_whatsapp_webhook_delivery",
    return_value=("1531697088984781", True),
)
def test_meta_whatsapp_manual_prod_waits_for_inbound(
    _ensure,
    resolve_ctx,
    send_template,
    send_customer_text,
    _register,
    _wait,
):
    resolve_ctx.return_value = ("1395406326980468", "token")
    db = MagicMock()
    cfg = {
        "messaging_channel": "whatsapp",
        "messaging_recipient": "+917051228092",
    }
    transcript = [{"speaker": "Speaker 1", "text": "I need help with my order"}]
    reply, leg = run_meta_whatsapp_live_production_turn(
        db,
        organization_id=uuid4(),
        cfg=cfg,
        transcript=transcript,
        agent_id=uuid4(),
        generate_agent_reply=lambda t: "should not run",
    )
    assert reply == "Sure, I can help."
    assert leg == "messaging_meta_whatsapp_manual_prod"
    send_customer_text.assert_called_once()
    assert "order" in send_customer_text.call_args.kwargs["body"]


@patch("app.services.agents.messaging_channel_chat._send_meta_whatsapp_text")
@patch("app.services.agents.messaging_channel_chat._send_meta_whatsapp")
@patch("app.services.agents.messaging_channel_chat._resolve_messaging_meta_whatsapp_context")
@patch(
    "app.services.telephony.meta_whatsapp_webhook_setup.ensure_meta_whatsapp_webhook_delivery",
    return_value=("1531697088984781", True),
)
def test_meta_whatsapp_simulated_llm_sends_prod_text(
    _ensure,
    resolve_ctx,
    send_template,
    send_text,
):
    resolve_ctx.return_value = ("1395406326980468", "token")
    db = MagicMock()
    cfg = {
        "messaging_channel": "whatsapp",
        "messaging_recipient": "+917051228092",
        "meta_whatsapp_prod_mode": "simulated_llm",
    }
    transcript = [{"speaker": "Speaker 1", "text": "Hi"}]
    reply, leg = run_meta_whatsapp_live_production_turn(
        db,
        organization_id=uuid4(),
        cfg=cfg,
        transcript=transcript,
        agent_id=uuid4(),
        generate_agent_reply=lambda t: "Hello from prod LLM.",
    )
    assert reply == "Hello from prod LLM."
    assert leg == "messaging_meta_whatsapp_sim_prod"
    send_text.assert_called_once()
    assert send_text.call_args.kwargs["body"] == "Hello from prod LLM."
