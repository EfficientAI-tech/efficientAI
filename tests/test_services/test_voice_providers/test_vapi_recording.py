"""Unit tests for Vapi recording URL helpers."""

from app.services.voice_providers.vapi_recording import (
    extract_vapi_recording_url,
    is_presigned_storage_url,
    vapi_playback_url_needs_refresh,
    vapi_proxy_request_headers,
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


def test_vapi_proxy_request_headers_skips_r2_without_presign():
    raw_r2 = "https://acct.r2.cloudflarestorage.com/hipaa/rec.wav"
    assert vapi_proxy_request_headers(raw_r2, "secret-key") is None
    signed = raw_r2 + "?X-Amz-Signature=abc"
    assert vapi_proxy_request_headers(signed, "secret-key") is None
    assert vapi_proxy_request_headers("https://api.vapi.ai/recording.wav", "secret-key") == {
        "Authorization": "Bearer secret-key",
    }


def test_vapi_playback_url_needs_refresh_for_private_r2():
    assert vapi_playback_url_needs_refresh(
        "https://x.r2.cloudflarestorage.com/a.wav"
    )
    assert not vapi_playback_url_needs_refresh(
        "https://x.r2.cloudflarestorage.com/a.wav?X-Amz-Signature=abc"
    )


def test_extract_vapi_recording_url_falls_back_to_recording_url():
    call_data = {
        "recordingUrl": "https://raw.example/recording.wav",
        "artifact": {"recording": {"mono": {"combinedUrl": "https://raw.example/combined.wav"}}},
    }
    assert extract_vapi_recording_url(call_data) == "https://raw.example/recording.wav"
