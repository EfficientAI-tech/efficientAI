"""Bounded reads for multipart uploads."""

from __future__ import annotations

from fastapi import UploadFile

DEFAULT_UPLOAD_CHUNK_SIZE = 64 * 1024


class UploadTooLargeError(Exception):
    """Raised when an upload exceeds the configured byte limit."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"Upload exceeds {max_bytes} bytes")


async def read_upload_with_limit(
    file: UploadFile,
    max_bytes: int,
    *,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
) -> bytes:
    """Read an upload in chunks, rejecting payloads larger than ``max_bytes``.

    Stops reading as soon as ``max_bytes + 1`` bytes are observed so callers
    never buffer an unbounded request body in memory.
    """
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")

    chunks: list[bytes] = []
    total = 0
    hard_limit = max_bytes + 1

    while total < hard_limit:
        to_read = min(chunk_size, hard_limit - total)
        chunk = await file.read(to_read)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(max_bytes)

    return b"".join(chunks)
