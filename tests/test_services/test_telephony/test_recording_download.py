"""Tests for recording URL download SSRF guards."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.telephony.exotel_client import (
    CredentialedRecordingThrottledError,
    ExotelAuthError,
    ExotelInvalidContentError,
    ExotelTransientError,
)
from app.services.telephony import recording_download as module


def test_assert_recording_url_safe_rejects_metadata_ip():
    with pytest.raises(ExotelInvalidContentError, match="blocked network address"):
        module.assert_recording_url_safe(
            "http://169.254.169.254/latest/meta-data/",
            user_supplied=True,
        )


def test_assert_recording_url_safe_rejects_public_literal_ip_even_when_trusted():
    with pytest.raises(ExotelInvalidContentError, match="not IP addresses"):
        module.assert_recording_url_safe(
            "https://203.0.113.10/recordings/call.mp3",
            user_supplied=False,
        )


def test_download_recording_url_does_not_send_credentials_to_literal_ip(monkeypatch):
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False

    with patch.object(module.httpx, "Client", return_value=mock_client):
        with pytest.raises(ExotelInvalidContentError, match="not IP addresses"):
            module.download_recording_url(
                "https://203.0.113.10/recordings/call.mp3",
                auth=("plivo-auth-id", "plivo-auth-token"),
                credential_fingerprint="fp-plivo",
            )

    mock_client.get.assert_not_called()


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


def test_download_recording_url_credentialed_rejects_shared_storage_host():
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False

    with patch.object(module.httpx, "Client", return_value=mock_client):
        with pytest.raises(ExotelInvalidContentError, match="not allowlisted"):
            module.download_recording_url(
                "https://evil-bucket.s3.amazonaws.com/recording.mp3",
                auth=("plivo-auth-id", "plivo-auth-token"),
                credential_fingerprint="fp-plivo",
            )

    mock_client.get.assert_not_called()


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


def _mock_authenticated_response(status_code: int, *, text: str = "nope"):
    return httpx.Response(
        status_code,
        headers={"content-type": "audio/mpeg"} if status_code == 200 else {},
        content=b"audio-bytes" if status_code == 200 else text.encode(),
        request=httpx.Request("GET", "https://api.exotel.com/recording.mp3"),
    )


def test_download_recording_url_authenticated_401_is_throttled(monkeypatch):
    monkeypatch.setattr(
        module.settings,
        "RECORDING_URL_ALLOWED_HOST_SUFFIXES",
        ["exotel.com"],
        raising=False,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.telephony_credential_rate_limit.penalize_telephony_credential",
        lambda *_a, **_kw: 15,
    )

    mock_client = MagicMock()
    mock_client.get.return_value = _mock_authenticated_response(401)
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False

    with patch.object(module.socket, "getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [(None, None, None, None, ("52.0.0.1", 0))]
        with patch.object(module.httpx, "Client", return_value=mock_client):
            with pytest.raises(CredentialedRecordingThrottledError, match="401"):
                module.download_recording_url(
                    "https://api.exotel.com/recording.mp3",
                    auth=("user", "pass"),
                    credential_fingerprint="fp-test",
                )


def test_download_recording_url_authenticated_400_is_transient_without_penalty(
    monkeypatch,
):
    monkeypatch.setattr(
        module.settings,
        "RECORDING_URL_ALLOWED_HOST_SUFFIXES",
        ["exotel.com"],
        raising=False,
    )
    penalize = MagicMock(return_value=20)
    monkeypatch.setattr(
        "app.workers.concurrency.telephony_credential_rate_limit.penalize_telephony_credential",
        penalize,
    )

    mock_client = MagicMock()
    mock_client.get.return_value = _mock_authenticated_response(400, text="Bad Request")
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False

    with patch.object(module.socket, "getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [(None, None, None, None, ("52.0.0.1", 0))]
        with patch.object(module.httpx, "Client", return_value=mock_client):
            with pytest.raises(ExotelTransientError, match="400"):
                module.download_recording_url(
                    "https://api.exotel.com/recording.mp3",
                    auth=("user", "pass"),
                    credential_fingerprint="fp-test",
                )

    penalize.assert_not_called()


def test_download_recording_url_public_429_is_transient(monkeypatch):
    monkeypatch.setattr(
        module.settings,
        "RECORDING_URL_ALLOWED_HOST_SUFFIXES",
        ["exotel.com"],
        raising=False,
    )

    mock_client = MagicMock()
    mock_client.get.return_value = _mock_authenticated_response(429, text="Too Many Requests")
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False

    with patch.object(module.socket, "getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [(None, None, None, None, ("52.0.0.1", 0))]
        with patch.object(module.httpx, "Client", return_value=mock_client):
            with pytest.raises(ExotelTransientError, match="429"):
                module.download_public_recording("https://api.exotel.com/recording.mp3")


def test_download_recording_url_public_401_stays_non_retryable(monkeypatch):
    monkeypatch.setattr(
        module.settings,
        "RECORDING_URL_ALLOWED_HOST_SUFFIXES",
        ["exotel.com"],
        raising=False,
    )

    mock_client = MagicMock()
    mock_client.get.return_value = _mock_authenticated_response(401)
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False

    with patch.object(module.socket, "getaddrinfo") as mock_getaddrinfo:
        mock_getaddrinfo.return_value = [(None, None, None, None, ("52.0.0.1", 0))]
        with patch.object(module.httpx, "Client", return_value=mock_client):
            with pytest.raises(ExotelAuthError, match="401"):
                module.download_public_recording("https://api.exotel.com/recording.mp3")
