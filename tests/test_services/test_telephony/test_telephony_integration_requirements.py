import pytest

from app.services.telephony.telephony_integration_requirements import (
    validate_telephony_integration_for_save,
)


def test_meta_whatsapp_requires_waba():
    with pytest.raises(ValueError, match="WABA"):
        validate_telephony_integration_for_save(
            "meta_whatsapp",
            {"auth_id": "1395406326980468", "auth_token": "tok"},
            is_create=True,
        )


def test_meta_whatsapp_accepts_waba():
    validate_telephony_integration_for_save(
        "meta_whatsapp",
        {
            "auth_id": "1395406326980468",
            "auth_token": "tok",
            "voice_app_id": "1531697088984781",
        },
        is_create=True,
    )


def test_telnyx_create_requires_webhook_public_key():
    with pytest.raises(ValueError, match="webhook public key"):
        validate_telephony_integration_for_save(
            "telnyx",
            {"auth_id": "x", "auth_token": "tok"},
            is_create=True,
        )
