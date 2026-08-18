from unittest.mock import patch
from uuid import UUID

from app.services.observability.recording_archive import (
    archive_observability_recording_to_s3,
    resolve_observability_recording_url,
)


def test_resolve_observability_recording_url_prefers_retell_recording_url():
    call_data = {"recording_url": "https://cdn.retell.ai/recording.wav"}
    assert resolve_observability_recording_url(call_data, "retell") == "https://cdn.retell.ai/recording.wav"


def test_resolve_observability_recording_url_falls_back_to_retell_multichannel():
    call_data = {"recording_multi_channel_url": "https://cdn.retell.ai/multi.wav"}
    assert resolve_observability_recording_url(call_data, "retell") == "https://cdn.retell.ai/multi.wav"


@patch("app.services.observability.recording_archive.s3_service")
@patch("app.services.observability.recording_archive._download_recording_bytes")
def test_archive_observability_recording_to_s3_sets_key(mock_download, mock_s3_service):
    mock_s3_service.is_enabled.return_value = True
    mock_s3_service.prefix = "efficientai/"
    mock_download.return_value = (b"audio-bytes", "audio/mpeg")

    call_data = {
        "call_status": "ended",
        "recording_url": "https://cdn.retell.ai/recording.mp3",
    }
    archived = archive_observability_recording_to_s3(
        call_data=call_data,
        provider_platform="retell",
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        call_short_id="123456",
    )

    assert archived["recording_s3_key"].startswith("efficientai/organizations/")
    assert archived["recording_source"] == "provider_archive"
    mock_s3_service.upload_file_by_key.assert_called_once()
