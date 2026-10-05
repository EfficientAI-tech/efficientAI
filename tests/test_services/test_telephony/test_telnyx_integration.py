from types import SimpleNamespace

from app.services.telephony.telnyx_integration import telnyx_messaging_profile_for_number


def test_messaging_profile_falls_back_to_number_capabilities():
    integration = SimpleNamespace(voice_app_id=None, verify_app_uuid=None, auth_token="x")
    number_row = SimpleNamespace(
        provider_app_id="voice-connection-id",
        capabilities={"messaging_profile_id": "profile-from-number"},
    )
    assert telnyx_messaging_profile_for_number(integration, number_row) == "profile-from-number"


def test_messaging_profile_ignores_provider_app_id_voice_connection():
    integration = SimpleNamespace(voice_app_id=None, verify_app_uuid=None, auth_token="x")
    number_row = SimpleNamespace(
        provider_app_id="connection-abc",
        capabilities={"voice": True, "sms": False, "connection_id": "connection-abc"},
    )
    assert telnyx_messaging_profile_for_number(integration, number_row) == ""


def test_messaging_profile_ignores_provider_app_id_when_it_matches_connection_id():
    integration = SimpleNamespace(voice_app_id=None, verify_app_uuid=None, auth_token="x")
    number_row = SimpleNamespace(
        provider_app_id="connection-abc",
        capabilities={"voice": True, "sms": True, "connection_id": "connection-abc"},
    )
    assert telnyx_messaging_profile_for_number(integration, number_row) == ""


def test_messaging_profile_legacy_provider_app_id_when_sms_capable():
    integration = SimpleNamespace(voice_app_id=None, verify_app_uuid=None, auth_token="x")
    number_row = SimpleNamespace(
        provider_app_id="profile-legacy",
        capabilities={"voice": True, "sms": True},
    )
    assert telnyx_messaging_profile_for_number(integration, number_row) == "profile-legacy"


def test_messaging_profile_prefers_integration_voice_app_id():
    integration = SimpleNamespace(voice_app_id="profile-on-integration", verify_app_uuid=None, auth_token="x")
    number_row = SimpleNamespace(
        provider_app_id="connection-abc",
        capabilities={"messaging_profile_id": "profile-from-number"},
    )
    assert telnyx_messaging_profile_for_number(integration, number_row) == "profile-on-integration"
