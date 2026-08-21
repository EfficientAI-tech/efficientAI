"""Unit tests for Vapi recording URL helpers."""

from app.services.voice_providers.vapi_recording import (
    extract_vapi_recording_url,
    is_presigned_storage_url,
)


def test_is_presigned_storage_url_detects_r2_query_params():
    assert is_presigned_storage_url(
        "https://example.r2.cloudflarestorage.com/file.wav?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
    )
    assert not is_presigned_storage_url("https://example.r2.cloudflarestorage.com/file.wav")


def test_extract_vapi_recording_url_prefers_presigned_mono():
    call_data = {
        "recordingUrl": "https://raw.example/recording.wav",
        "artifact": {
            "presignedMonoUrl": "https://signed.example/recording.wav?X-Amz-Signature=abc",
            "recordingUrl": "https://raw.example/artifact-recording.wav",
            "recording": {"mono": {"combinedUrl": "https://raw.example/combined.wav"}},
        },
    }
    assert (
        extract_vapi_recording_url(call_data)
        == "https://signed.example/recording.wav?X-Amz-Signature=abc"
    )


def test_extract_vapi_recording_url_falls_back_to_recording_url():
    call_data = {
        "recordingUrl": "https://raw.example/recording.wav",
        "artifact": {"recording": {"mono": {"combinedUrl": "https://raw.example/combined.wav"}}},
    }
    assert extract_vapi_recording_url(call_data) == "https://raw.example/recording.wav"
