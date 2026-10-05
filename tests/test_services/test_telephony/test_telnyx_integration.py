from types import SimpleNamespace

from app.services.telephony.telnyx_integration import telnyx_messaging_profile_for_number


def test_messaging_profile_falls_back_to_number_provider_app_id():
    integration = SimpleNamespace(voice_app_id=None, verify_app_uuid=None, auth_token="x")
    number_row = SimpleNamespace(provider_app_id="profile-from-number", capabilities=None)
    assert telnyx_messaging_profile_for_number(integration, number_row) == "profile-from-number"


def test_messaging_profile_prefers_integration_voice_app_id():
    integration = SimpleNamespace(voice_app_id="profile-on-integration", verify_app_uuid=None, auth_token="x")
    number_row = SimpleNamespace(provider_app_id="profile-from-number", capabilities=None)
    assert telnyx_messaging_profile_for_number(integration, number_row) == "profile-on-integration"
