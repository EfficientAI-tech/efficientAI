from app.services.agents.messaging_channel_chat import (
    TWILIO_TRIAL_SMS_BODY_TEMPLATES,
    _meta_graph_api_error_detail,
    _meta_whatsapp_outbound_payload,
    _normalize_whatsapp_to,
    _sms_outbound_body,
)


def test_sms_outbound_body_uses_trial_template_when_configured():
    cfg = {"twilio_sms_trial_body_template": "sms_appointment_reminders"}
    assert _sms_outbound_body(cfg, "Simulated customer opener") == "sms_appointment_reminders"


def test_sms_outbound_body_falls_back_to_user_text():
    assert _sms_outbound_body({}, "hello") == "hello"


def test_trial_template_names_non_empty():
    assert "sms_appointment_reminders" in TWILIO_TRIAL_SMS_BODY_TEMPLATES


def test_meta_whatsapp_outbound_uses_template_when_configured():
    payload = _meta_whatsapp_outbound_payload(
        {"meta_whatsapp_opening_template": "hello_world", "meta_whatsapp_template_language": "en_US"},
        "919876543210",
        "ignored",
    )
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "hello_world"


def test_meta_whatsapp_outbound_defaults_hello_world_template():
    payload = _meta_whatsapp_outbound_payload({}, "919876543210", "Hi there")
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "hello_world"


def test_normalize_whatsapp_to_strips_plus():
    assert _normalize_whatsapp_to("+919876543210") == "919876543210"


def test_meta_graph_api_error_detail_parses_json():
    import httpx

    resp = httpx.Response(
        400,
        json={
            "error": {
                "message": "(#131030) Recipient phone number not in allowed list",
                "type": "OAuthException",
                "code": 131030,
            }
        },
    )
    detail = _meta_graph_api_error_detail(resp)
    assert "131030" in detail
    assert "allowed list" in detail
