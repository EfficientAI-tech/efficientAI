"""Tests for recording URL download SSRF guards."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.telephony.exotel_client import ExotelInvalidContentError
from app.services.telephony import recording_download as module


def test_assert_recording_url_safe_rejects_metadata_ip():
    with pytest.raises(ExotelInvalidContentError, match="blocked network address"):
        module.assert_recording_url_safe(
            "http://169.254.169.254/latest/meta-data/",
            user_supplied=True,
        )


def test_assert_recording_url_safe_rejects_non_allowlisted_host(monkeypatch):
    monkeypatch.setattr(
        module.settings,
        "RECORDING_URL_ALLOWED_HOST_SUFFIXES",
        ["exotel.com"],
        raising=False,
    )
    with pytest.raises(ExotelInvalidContentError, match="not allowlisted"):
        module.assert_recording_url_safe(
            "https://evil.example/recording.mp3",
            user_supplied=True,
        )


def test_download_recording_url_rejects_credentials_for_user_supplied_urls():
    with pytest.raises(ExotelInvalidContentError, match="must not be fetched with credentials"):
        module.download_recording_url(
            "https://api.exotel.com/v1/Accounts/recording.mp3",
            auth=("user", "pass"),
            user_supplied=True,
        )


def test_download_public_recording_fetches_allowlisted_host(monkeypatch):
    monkeypatch.setattr(
        module.settings,
        "RECORDING_URL_ALLOWED_HOST_SUFFIXES",
        ["exotel.com"],
        raising=False,
    )

    response = httpx.Response(
        200,
        headers={"content-type": "audio/mpeg"},
        content=b"audio-bytes",
        request=httpx.Request("GET", "https://api.exotel.com/recording.mp3"),
    )
    mock_client = MagicMock()
    mock_client.get.return_value = response
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False

    with patch.object(module.socket, "getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [(None, None, None, None, ("52.0.0.1", 0))]
        with patch.object(module.httpx, "Client", return_value=mock_client):
            body, content_type = module.download_public_recording(
                "https://api.exotel.com/recording.mp3"
            )

    assert body == b"audio-bytes"
    assert content_type == "audio/mpeg"
    mock_client.get.assert_called_once_with(
        "https://api.exotel.com/recording.mp3",
        auth=None,
    )
