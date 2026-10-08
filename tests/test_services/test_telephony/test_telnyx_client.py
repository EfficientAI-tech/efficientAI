from unittest.mock import MagicMock, patch

from app.services.telephony.telnyx_client import TelnyxClient


def test_telnyx_send_message_includes_profile():
    client = TelnyxClient("KEY", messaging_profile_id="prof-1")
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.json.return_value = {"data": {"id": "msg-1"}}
    with patch("httpx.Client") as client_cls:
        instance = client_cls.return_value.__enter__.return_value
        instance.post.return_value = mock_resp
        msg_id = client.send_message(from_e164="+15551234567", to_e164="+15557654321", text="hi")
    assert msg_id == "msg-1"
    payload = instance.post.call_args.kwargs["json"]
    assert payload["messaging_profile_id"] == "prof-1"
