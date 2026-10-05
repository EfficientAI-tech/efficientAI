from app.services.agents.messaging_channel_chat import (
    TWILIO_TRIAL_SMS_BODY_TEMPLATES,
    _sms_outbound_body,
)


def test_sms_outbound_body_uses_trial_template_when_configured():
    cfg = {"twilio_sms_trial_body_template": "sms_appointment_reminders"}
    assert _sms_outbound_body(cfg, "Simulated customer opener") == "sms_appointment_reminders"


def test_sms_outbound_body_falls_back_to_user_text():
    assert _sms_outbound_body({}, "hello") == "hello"


def test_trial_template_names_non_empty():
    assert "sms_appointment_reminders" in TWILIO_TRIAL_SMS_BODY_TEMPLATES
