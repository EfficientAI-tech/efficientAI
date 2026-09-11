"""Unit tests for PlivoClient."""

from unittest.mock import patch

import pytest

from app.services.telephony.plivo_client import PlivoClient


@pytest.fixture
def plivo_client():
    with patch("app.services.telephony.plivo_client.plivo") as mock_plivo_module:
        mock_plivo_module.RestClient.return_value = object()
        yield PlivoClient(
            auth_id="MA_TEST",
            auth_token="secret-token",
            credential_fingerprint="fp-test",
        )


def test_download_recording_uses_basic_auth(plivo_client):
    recording_url = "https://media.plivo.com/recordings/rec.mp3"

    with patch(
        "app.services.telephony.recording_download.download_recording_url",
        return_value=(b"audio-bytes", "audio/mpeg"),
    ) as mock_download:
        body, content_type = plivo_client.download_recording(recording_url)

    mock_download.assert_called_once_with(
        recording_url,
        auth=("MA_TEST", "secret-token"),
        credential_fingerprint="fp-test",
    )
    assert body == b"audio-bytes"
    assert content_type == "audio/mpeg"
