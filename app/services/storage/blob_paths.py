"""Shared object key/path helpers for cloud blob storage backends."""

from typing import Optional
import uuid


def normalize_prefix(prefix: str) -> str:
    """Ensure prefix ends with a single trailing slash."""
    return prefix.rstrip("/") + "/" if prefix else ""


def build_object_key(
    file_id: uuid.UUID,
    file_format: str,
    prefix: str,
    organization_id: Optional[str] = None,
    evaluator_id: Optional[str] = None,
    meaningful_id: Optional[str] = None,
) -> str:
    """Generate an object key for a file."""
    file_identifier = meaningful_id if meaningful_id else str(file_id)
    base_key = f"{file_identifier}.{file_format}"
    normalized = normalize_prefix(prefix)

    if organization_id:
        if evaluator_id:
            return (
                f"{normalized}organizations/{organization_id}/evaluators/"
                f"{evaluator_id}/audio/{base_key}"
            )
        return f"{normalized}organizations/{organization_id}/audio/{base_key}"
    return f"{normalized}{base_key}"


def get_organization_root_prefix(prefix: str, organization_id: str) -> str:
    """Get the root object prefix for a given organization."""
    return f"{normalize_prefix(prefix)}organizations/{organization_id}/"


def content_type_for_format(file_format: str) -> str:
    """Map audio file extension to MIME content type."""
    content_type_map = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
    }
    return content_type_map.get(file_format.lower(), "application/octet-stream")
