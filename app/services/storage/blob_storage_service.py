"""Provider facade for cloud blob storage (S3 or GCS)."""

from typing import List, Optional
import uuid

from app.config import settings
from app.services.storage.s3_service import S3Service


class BlobStorageService:
    """Delegates blob operations to the configured storage backend."""

    def __init__(self):
        self._s3 = S3Service()
        self._gcs = None

    def _get_gcs(self):
        if self._gcs is None:
            from app.services.storage.gcs_service import GcsService

            self._gcs = GcsService()
        return self._gcs

    @property
    def provider_name(self) -> str:
        """Return the active provider identifier."""
        return settings.BLOB_STORAGE_PROVIDER

    def _backend(self):
        provider = settings.BLOB_STORAGE_PROVIDER
        if provider == "gcs":
            return self._get_gcs()
        return self._s3

    @property
    def prefix(self) -> str:
        return self._backend().prefix

    def reset_connection(self):
        """Reset lazy initialization on all backends (for connection tests)."""
        self._s3.reset_connection()
        if self._gcs is not None:
            self._gcs.reset_connection()

    def is_enabled(self) -> bool:
        return self._backend().is_enabled()

    def get_status_message(self) -> Optional[str]:
        return self._backend().get_status_message()

    def upload_file(
        self,
        file_content: bytes,
        file_id: uuid.UUID,
        file_format: str,
        organization_id: Optional[str] = None,
        evaluator_id: Optional[str] = None,
        meaningful_id: Optional[str] = None,
    ) -> str:
        return self._backend().upload_file(
            file_content,
            file_id,
            file_format,
            organization_id,
            evaluator_id,
            meaningful_id,
        )

    def upload_file_by_key(
        self, file_content: bytes, key: str, content_type: str = "audio/mpeg"
    ) -> str:
        return self._backend().upload_file_by_key(file_content, key, content_type)

    def download_file(self, file_id: uuid.UUID, file_format: str) -> bytes:
        return self._backend().download_file(file_id, file_format)

    def download_file_by_key(self, key: str) -> bytes:
        return self._backend().download_file_by_key(key)

    def delete_file(self, file_id: uuid.UUID, file_format: str) -> bool:
        return self._backend().delete_file(file_id, file_format)

    def delete_file_by_key(self, key: str) -> bool:
        return self._backend().delete_file_by_key(key)

    def delete_keys(self, keys: List[str]) -> tuple[int, List[dict]]:
        return self._backend().delete_keys(keys)

    def delete_keys_by_prefix(self, prefix: str) -> tuple[int, List[dict]]:
        return self._backend().delete_keys_by_prefix(prefix)

    def file_exists(self, file_id: uuid.UUID, file_format: str) -> bool:
        return self._backend().file_exists(file_id, file_format)

    def list_audio_files(
        self,
        prefix: Optional[str] = None,
        max_keys: int = 1000,
        organization_id: Optional[str] = None,
    ) -> List[dict]:
        return self._backend().list_audio_files(prefix, max_keys, organization_id)

    def get_organization_root_prefix(self, organization_id: str) -> str:
        return self._backend().get_organization_root_prefix(organization_id)

    def browse_folder(
        self,
        organization_id: str,
        path: str = "",
        max_keys: int = 1000,
    ) -> dict:
        return self._backend().browse_folder(organization_id, path, max_keys)

    def generate_presigned_url(
        self, file_id: uuid.UUID, file_format: str, expiration: int = 3600
    ) -> str:
        return self._backend().generate_presigned_url(file_id, file_format, expiration)

    def generate_presigned_url_by_key(self, key: str, expiration: int = 3600) -> str:
        return self._backend().generate_presigned_url_by_key(key, expiration)


blob_storage_service = BlobStorageService()
