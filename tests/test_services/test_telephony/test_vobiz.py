"""Unit tests for Vobiz telephony helpers."""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.database import Organization, TelephonyIntegration
from app.services.telephony.phone_routing import safe_normalize_phone
from app.services.telephony.plivo_client import expand_phone_candidates, normalize_e164
from app.services.telephony.vobiz_client import VobizClient, build_vobiz_client_for_org
from app.services.telephony.vobiz_session import create_call_session, delete_call_session, get_call_session
from app.services.telephony.carrier_media_serializer import build_carrier_frame_serializer
from app.services.telephony.vobiz_xml import reject_call, speak_and_hangup, stream_to_agent
from efficientai.serializers.plivo import PlivoFrameSerializer
from efficientai.serializers.vobiz import VobizFrameSerializer


def test_normalize_e164_adds_plus_for_digit_only_numbers():
    assert normalize_e164("91171366938") == "+91171366938"
    assert normalize_e164("+91171366938") == "+91171366938"


def test_normalize_e164_handles_indian_trunk_prefix():
    assert normalize_e164("08071579610") == "+918071579610"


def test_expand_phone_candidates_includes_trunk_and_e164_variants():
    candidates = expand_phone_candidates("08071579610", default_country_code="91")
    assert "+918071579610" in candidates


def test_safe_normalize_phone_returns_none_for_invalid():
    assert safe_normalize_phone("") is None
    assert safe_normalize_phone("not-a-number") is None


def test_stream_to_agent_xml_contains_websocket_and_record():
    xml = stream_to_agent(
        "wss://example.com/api/v1/telephony/carrier/ws?agent_id=abc&session=xyz",
        record_action_url="https://example.com/api/v1/telephony/vobiz/webhooks/recording-ready",
    )
    assert "<Stream bidirectional=\"true\"" in xml
    assert "audio/x-mulaw;rate=8000" in xml
    assert "wss://example.com/api/v1/telephony/carrier/ws" in xml
    assert "<Record action=" in xml


def test_speak_and_hangup_escapes_xml_entities():
    xml = speak_and_hangup("Route <failed> & unavailable")
    assert "&lt;failed&gt;" in xml
    assert "&amp;" in xml
    assert "<Hangup" in xml


def test_reject_call_returns_spoken_message():
    xml = reject_call("Number not configured")
    assert "Number not configured" in xml
    assert "<Speak>" in xml


@patch("app.services.telephony.vobiz_client.httpx.Client")
def test_vobiz_client_create_outbound_call(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"request_uuid": "req-123", "message": "call queued"}'
    mock_response.json.return_value = {"request_uuid": "req-123", "message": "call queued"}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    mock_client.request.return_value = mock_response
    mock_client_cls.return_value = mock_client

    client = VobizClient(auth_id="MA_TEST", auth_token="token", api_base="https://api.vobiz.ai")
    result = client.create_outbound_call(
        from_="+14155550100",
        to_="+14155550101",
        answer_url="https://example.com/answer",
        hangup_url="https://example.com/events",
    )

    assert result["request_uuid"] == "req-123"
    mock_client.request.assert_called_once()
    args, kwargs = mock_client.request.call_args
    assert args[0] == "POST"
    assert args[1] == "https://api.vobiz.ai/api/v1/Account/MA_TEST/Call/"
    assert kwargs["json"]["from"] == "+14155550100"
    assert kwargs["json"]["to"] == "+14155550101"
    assert kwargs["json"]["answer_url"] == "https://example.com/answer"


@patch("app.services.telephony.vobiz_client.httpx.Client")
def test_vobiz_client_hangup_call(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 204

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.request.return_value = mock_response
    mock_client_cls.return_value = mock_client

    client = VobizClient(auth_id="MA_TEST", auth_token="token")
    assert client.hangup_call("call-1") is True
    mock_client.request.assert_called_once()
    args, kwargs = mock_client.request.call_args
    assert args[0] == "DELETE"
    assert args[1] == "https://api.vobiz.ai/api/v1/Account/MA_TEST/Call/call-1/"


@patch("app.services.telephony.vobiz_client.httpx.Client")
def test_vobiz_client_list_account_numbers(mock_client_cls):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"items": [{"e164": "+919876543210", "id": "num-1"}], "total": 1}'
    mock_response.json.return_value = {"items": [{"e164": "+919876543210", "id": "num-1"}], "total": 1}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.request.return_value = mock_response
    mock_client_cls.return_value = mock_client

    client = VobizClient(auth_id="MA_TEST", auth_token="token")
    numbers = client.list_account_numbers()
    assert numbers[0]["e164"] == "+919876543210"


@patch("app.services.telephony.vobiz_client.VobizClient.attach_number_to_application")
@patch("app.services.telephony.vobiz_client.VobizClient.create_application")
def test_vobiz_client_set_number_answer_url_creates_app(mock_create, mock_attach):
    mock_create.return_value = {"app_id": "app-123"}
    mock_attach.return_value = {"message": "linked"}

    client = VobizClient(auth_id="MA_TEST", auth_token="token")
    ok, message, app_id = client.set_number_answer_url(
        "+919876543210",
        "https://example.com/answer",
    )
    assert ok is True
    assert app_id == "app-123"
    mock_create.assert_called_once()
    mock_attach.assert_called_once_with("+919876543210", "app-123")


@patch("app.services.telephony.vobiz_client.build_vobiz_client_from_settings")
@patch("app.services.telephony.vobiz_client.resolve_telephony_integration")
@patch("app.services.telephony.vobiz_client.decrypt_api_key")
def test_build_vobiz_client_for_org_uses_byo_credentials(mock_decrypt, mock_resolve, mock_platform):
    org_id = uuid4()
    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider="vobiz",
        auth_id="enc-id",
        auth_token="enc-token",
        is_active=True,
    )
    mock_resolve.return_value = integration
    mock_decrypt.side_effect = lambda value: "plain-" + value

    client, resolved = build_vobiz_client_for_org(MagicMock(), org_id)
    assert resolved is integration
    assert client.auth_id == "plain-enc-id"
    mock_platform.assert_not_called()


@patch("app.services.telephony.vobiz_client.build_vobiz_client_from_settings")
@patch("app.services.telephony.vobiz_client.resolve_telephony_integration")
def test_build_vobiz_client_for_org_falls_back_to_platform(mock_resolve, mock_platform):
    mock_resolve.return_value = None
    platform_client = VobizClient(auth_id="MA_PLATFORM", auth_token="token")
    mock_platform.return_value = platform_client

    client, resolved = build_vobiz_client_for_org(MagicMock(), uuid4())
    assert resolved is None
    assert client is platform_client


def test_vobiz_call_session_round_trip(monkeypatch):
    store = {}

    class FakeRedis:
        def setex(self, key, ttl, value):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr(
        "app.services.telephony.vobiz_session._get_redis",
        lambda: FakeRedis(),
    )

    agent_id = str(uuid4())
    org_id = str(uuid4())
    session = create_call_session(agent_id=agent_id, organization_id=org_id, to_number="+14155550101")
    loaded = get_call_session(session.call_ref)
    assert loaded is not None
    assert loaded.agent_id == agent_id
    assert loaded.organization_id == org_id
    assert loaded.to_number == "+14155550101"

    delete_call_session(session.call_ref)
    assert get_call_session(session.call_ref) is None


@pytest.mark.asyncio
async def test_vobiz_serializer_round_trip_media_frame():
    serializer = VobizFrameSerializer(
        stream_id="stream-1",
        call_id="call-1",
        params=VobizFrameSerializer.InputParams(sample_rate=8000),
    )

    from efficientai.frames.frames import StartFrame

    await serializer.setup(StartFrame(audio_in_sample_rate=8000, audio_out_sample_rate=8000))

    media_message = json.dumps(
        {
            "event": "media",
            "media": {
                "payload": "f8f8f8f8",
            },
        }
    )
    frame = await serializer.deserialize(media_message)
    assert frame is not None
    assert len(frame.audio) > 0


def test_carrier_frame_serializer_uses_plivo_credentials_for_plivo_calls(monkeypatch):
    org_id = uuid4()
    integration = MagicMock()
    integration.auth_id = "enc-auth-id"
    integration.auth_token = "enc-auth-token"
    pinned_id = uuid4()

    def _resolve(provider, db, organization_id, credential_id=None, **_kwargs):
        assert provider == "plivo"
        assert organization_id == org_id
        assert credential_id == pinned_id
        return integration

    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.resolve_telephony_integration",
        _resolve,
    )
    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.decrypt_api_key",
        lambda value: {"enc-auth-id": "plivo-auth-id", "enc-auth-token": "plivo-token"}[value],
    )

    serializer = build_carrier_frame_serializer(
        provider_platform="plivo",
        stream_id="stream-plivo",
        call_id="call-plivo",
        organization_id=org_id,
        db=MagicMock(),
        telephony_integration_id=pinned_id,
    )

    assert isinstance(serializer, PlivoFrameSerializer)
    assert serializer._auth_id == "plivo-auth-id"
    assert serializer._auth_token == "plivo-token"
    assert serializer._call_id == "call-plivo"


def test_carrier_frame_serializer_falls_back_to_platform_plivo_credentials(monkeypatch):
    org_id = uuid4()

    def _resolve(*_args, credential_id=None, **_kwargs):
        assert credential_id is None
        return None

    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.resolve_telephony_integration",
        _resolve,
    )
    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.settings.PLIVO_AUTH_ID",
        "platform-plivo-id",
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.settings.PLIVO_AUTH_TOKEN",
        "platform-plivo-token",
        raising=False,
    )

    serializer = build_carrier_frame_serializer(
        provider_platform="plivo",
        stream_id="stream-plivo",
        call_id="call-plivo",
        organization_id=org_id,
        db=MagicMock(),
    )

    assert isinstance(serializer, PlivoFrameSerializer)
    assert serializer._auth_id == "platform-plivo-id"
    assert serializer._auth_token == "platform-plivo-token"


def test_carrier_frame_serializer_keeps_vobiz_credentials_for_vobiz_calls(monkeypatch):
    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.settings.VOBIZ_AUTH_ID",
        "vobiz-auth-id",
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.settings.VOBIZ_AUTH_TOKEN",
        "vobiz-token",
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.telephony.carrier_media_serializer.settings.VOBIZ_API_BASE",
        "https://api.vobiz.ai",
        raising=False,
    )

    serializer = build_carrier_frame_serializer(
        provider_platform="vobiz",
        stream_id="stream-vobiz",
        call_id="call-vobiz",
        organization_id=uuid4(),
        db=MagicMock(),
    )

    assert isinstance(serializer, VobizFrameSerializer)
    assert serializer._auth_id == "vobiz-auth-id"
    assert serializer._auth_token == "vobiz-token"
    assert serializer._call_id == "call-vobiz"
