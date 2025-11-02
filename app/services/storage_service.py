"""File storage service for handling audio file uploads and storage."""

import os
import uuid
from pathlib import Path
from typing import BinaryIO
from fastapi import UploadFile
from app.config import settings
from app.core.exceptions import StorageError, InvalidAudioFormatError


class StorageService:
    """Service for managing file storage."""

    def __init__(self):
        """Initialize storage service with upload directory."""
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024  # Convert MB to bytes
        self.allowed_formats = settings.ALLOWED_AUDIO_FORMATS

    def validate_file(self, file: UploadFile) -> tuple[str, int]:
        """
        Validate uploaded file.

        Args:
            file: Uploaded file

        Returns:
            Tuple of (file_extension, file_size)

        Raises:
            InvalidAudioFormatError: If file format is not allowed
            StorageError: If file size exceeds limit
        """
        # Get file extension
        filename = file.filename or ""
        file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if file_ext not in self.allowed_formats:
            raise InvalidAudioFormatError(
                f"File format '{file_ext}' not allowed. Allowed formats: {', '.join(self.allowed_formats)}"
            )

        # Note: We can't easily get file size from UploadFile without reading it
        # This will be validated when saving
        return file_ext, 0

    def save_file(self, file: UploadFile, file_id: uuid.UUID) -> tuple[str, int]:
        """
        Save uploaded file to disk.

        Args:
            file: Uploaded file
            file_id: Unique identifier for the file

        Returns:
            Tuple of (file_path, file_size)

        Raises:
            StorageError: If file save fails
        """
        try:
            # Validate file format
            file_ext, _ = self.validate_file(file)

            # Generate unique filename
            filename = f"{file_id}.{file_ext}"
            file_path = self.upload_dir / filename

            # Read file content and save
            content = file.file.read()
            file_size = len(content)

            # Validate file size
            if file_size > self.max_file_size:
                raise StorageError(
                    f"File size ({file_size / 1024 / 1024:.2f} MB) exceeds maximum allowed size "
                    f"({settings.MAX_FILE_SIZE_MB} MB)"
                )

            # Write file to disk
            with open(file_path, "wb") as f:
                f.write(content)

            return str(file_path), file_size

        except Exception as e:
            if isinstance(e, (StorageError, InvalidAudioFormatError)):
                raise
            raise StorageError(f"Failed to save file: {str(e)}")

    def get_file_path(self, file_id: uuid.UUID, file_format: str) -> Path:
        """
        Get file path for a given file ID.

        Args:
            file_id: File identifier
            file_format: File format extension

        Returns:
            Path to the file
        """
        filename = f"{file_id}.{file_format}"
        return self.upload_dir / filename

    def file_exists(self, file_id: uuid.UUID, file_format: str) -> bool:
        """
        Check if file exists.

        Args:
            file_id: File identifier
            file_format: File format extension

        Returns:
            True if file exists, False otherwise
        """
        file_path = self.get_file_path(file_id, file_format)
        return file_path.exists()

    def delete_file(self, file_id: uuid.UUID, file_format: str) -> bool:
        """
        Delete file from storage.

        Args:
            file_id: File identifier
            file_format: File format extension

        Returns:
            True if file was deleted, False if it didn't exist
        """
        file_path = self.get_file_path(file_id, file_format)
        try:
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            raise StorageError(f"Failed to delete file: {str(e)}")


# Singleton instance
storage_service = StorageService()

