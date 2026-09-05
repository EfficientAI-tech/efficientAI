"""Tests for bounded multipart upload reads."""

from __future__ import annotations

import io

import pytest
from starlette.datastructures import UploadFile

from app.utils.upload_limits import UploadTooLargeError, read_upload_with_limit


def _upload_file(data: bytes, *, filename: str = "ambient.wav") -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(data))


@pytest.mark.asyncio
async def test_read_upload_with_limit_returns_full_payload_under_cap():
    data = b"x" * 1024
    payload = await read_upload_with_limit(_upload_file(data), max_bytes=2048, chunk_size=256)
    assert payload == data


@pytest.mark.asyncio
async def test_read_upload_with_limit_accepts_exact_cap():
    data = b"x" * 512
    payload = await read_upload_with_limit(_upload_file(data), max_bytes=512, chunk_size=64)
    assert payload == data


@pytest.mark.asyncio
async def test_read_upload_with_limit_rejects_one_byte_over_cap():
    data = b"x" * (1024 + 1)
    with pytest.raises(UploadTooLargeError) as exc_info:
        await read_upload_with_limit(_upload_file(data), max_bytes=1024, chunk_size=128)
    assert exc_info.value.max_bytes == 1024


@pytest.mark.asyncio
async def test_read_upload_with_limit_stops_reading_after_rejecting_oversized_payload():
    data = b"x" * (1024 + 500)
    upload = _upload_file(data)

    with pytest.raises(UploadTooLargeError):
        await read_upload_with_limit(upload, max_bytes=1024, chunk_size=128)

    remaining = await upload.read()
    assert remaining == b"x" * 499


@pytest.mark.asyncio
async def test_read_upload_with_limit_allows_empty_upload():
    payload = await read_upload_with_limit(_upload_file(b""), max_bytes=1024)
    assert payload == b""
