"""Azure Blob Storage service for handling audio file storage and retrieval."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Tuple

from app.config import settings
from app.core.exceptions import StorageError
from app.services.storage.blob_paths import (
    build_object_key,
    content_type_for_format,
    get_organization_root_prefix,
    normalize_prefix,
)

_AZURE_LIBS: Optional[Tuple[Any, Any, Any, Any, Any]] = None


def _get_azure_libs() -> Tuple[Any, Any, Any, Any, Any]:
    """Import azure-storage-blob lazily so S3/GCS-only installs can start."""
    global _AZURE_LIBS
    if _AZURE_LIBS is None:
        try:
            from azure.core.exceptions import ResourceNotFoundError
            from azure.storage.blob import (
                BlobSasPermissions,
                BlobServiceClient,
                generate_blob_sas,
            )
        except ImportError as exc:
            raise ImportError(
                "azure-storage-blob is required for Azure blob storage. "
                "Install with: pip install 'azure-storage-blob>=12.19.0'"
            ) from exc
        _AZURE_LIBS = (
            BlobServiceClient,
            ResourceNotFoundError,
            generate_blob_sas,
            BlobSasPermissions,
            Exception,
        )
    return _AZURE_LIBS


def _parse_connection_string_value(connection_string: str, key: str) -> Optional[str]:
    """Extract a named value from an Azure storage connection string."""
    pattern = rf"{re.escape(key)}=([^;]+)"
    match = re.search(pattern, connection_string, flags=re.IGNORECASE)
    return match.group(1) if match else None


class AzureBlobService:
    """Service for managing Azure Blob Storage file storage."""

    def __init__(self):
        """Initialize Azure Blob service with configuration."""
        self.blob_service_client = None
        self.container_client = None
        self._initialization_error = None
        self._resolved_account_name: Optional[str] = None
        self._resolved_account_key: Optional[str] = None

    @property
    def enabled(self) -> bool:
        """Get Azure blob storage enabled status from settings."""
        return settings.AZURE_BLOB_ENABLED

    @property
    def bucket_name(self) -> Optional[str]:
        """Container name (alias for consistency with S3/GCS backends)."""
        return settings.AZURE_CONTAINER_NAME

    @property
    def prefix(self) -> str:
        """Get Azure blob prefix from settings."""
        return normalize_prefix(settings.AZURE_PREFIX)

    def _resolve_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        """Resolve account name and key from config or connection string."""
        if settings.AZURE_CONNECTION_STRING:
            account_name = _parse_connection_string_value(
                settings.AZURE_CONNECTION_STRING, "AccountName"
            )
            account_key = _parse_connection_string_value(
                settings.AZURE_CONNECTION_STRING, "AccountKey"
            )
            return account_name, account_key

        return settings.AZURE_ACCOUNT_NAME, settings.AZURE_ACCOUNT_KEY

    def _build_client(self):
        """Create a BlobServiceClient using configured credentials."""
        BlobServiceClient, _, _, _, _ = _get_azure_libs()

        if settings.AZURE_CONNECTION_STRING:
            return BlobServiceClient.from_connection_string(
                settings.AZURE_CONNECTION_STRING
            )

        account_name, account_key = self._resolve_credentials()
        if account_name and account_key:
            account_url = f"https://{account_name}.blob.core.windows.net"
            return BlobServiceClient(account_url=account_url, credential=account_key)

        return None

    def _get_account_key_for_sas(self) -> Optional[str]:
        """Return account key for SAS URL generation."""
        if self._resolved_account_key:
            return self._resolved_account_key

        _, account_key = self._resolve_credentials()
        return account_key

    def _ensure_initialized(self):
        """Lazily initialize Azure Blob client if not already initialized."""
        if self.blob_service_client is not None and self.container_client is not None:
            return

        if not self.enabled:
            return

        if not self.bucket_name:
            self._initialization_error = (
                "Azure Blob Storage is enabled but container_name is not configured"
            )
            return

        account_name, account_key = self._resolve_credentials()
        if not settings.AZURE_CONNECTION_STRING and not (account_name and account_key):
            self._initialization_error = (
                "Azure Blob Storage credentials not configured. "
                "Set azure.connection_string or azure.account_name + azure.account_key."
            )
            return

        try:
            self.blob_service_client = self._build_client()
            if self.blob_service_client is None:
                self._initialization_error = "Failed to build Azure Blob Storage client"
                return

            self._resolved_account_name = (
                account_name
                or getattr(self.blob_service_client, "account_name", None)
            )
            self._resolved_account_key = account_key

            self.container_client = self.blob_service_client.get_container_client(
                self.bucket_name
            )

            if not self.container_client.exists():
                self._initialization_error = (
                    f"Azure container '{self.bucket_name}' does not exist"
                )
                self.blob_service_client = None
                self.container_client = None
                return
        except ImportError as exc:
            self._initialization_error = str(exc)
            self.blob_service_client = None
            self.container_client = None
        except Exception as e:
            self._initialization_error = (
                f"Failed to initialize Azure Blob Storage service: {str(e)}"
            )
            self.blob_service_client = None
            self.container_client = None

    def reset_connection(self):
        """Reset lazy initialization state (for connection tests)."""
        self.blob_service_client = None
        self.container_client = None
        self._initialization_error = None
        self._resolved_account_name = None
        self._resolved_account_key = None

    def is_enabled(self) -> bool:
        """Check if Azure Blob Storage is enabled and configured."""
        if not self.enabled:
            return False
        self._ensure_initialized()
        return (
            self.blob_service_client is not None and self.container_client is not None
        )

    def get_status_message(self) -> Optional[str]:
        """Get status message if there's an initialization error."""
        if not self.enabled:
            return None
        self._ensure_initialized()
        return self._initialization_error

    def _get_key(
        self,
        file_id: uuid.UUID,
        file_format: str,
        organization_id: Optional[str] = None,
        evaluator_id: Optional[str] = None,
        meaningful_id: Optional[str] = None,
    ) -> str:
        """Generate Azure blob name for a file."""
        return build_object_key(
            file_id,
            file_format,
            settings.AZURE_PREFIX,
            organization_id,
            evaluator_id,
            meaningful_id,
        )

    def upload_file(
        self,
        file_content: bytes,
        file_id: uuid.UUID,
        file_format: str,
        organization_id: Optional[str] = None,
        evaluator_id: Optional[str] = None,
        meaningful_id: Optional[str] = None,
    ) -> str:
        """Upload file to Azure Blob Storage."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        try:
            key = self._get_key(
                file_id, file_format, organization_id, evaluator_id, meaningful_id
            )
            content_type = content_type_for_format(file_format)
            return self.upload_file_by_key(file_content, key, content_type=content_type)
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"Unexpected error uploading file to Azure Blob Storage: {str(e)}"
            )

    def upload_file_by_key(
        self, file_content: bytes, key: str, content_type: str = "audio/mpeg"
    ) -> str:
        """Upload file to Azure Blob Storage using an explicit key path."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        try:
            blob_client = self.container_client.get_blob_client(key)
            blob_client.upload_blob(
                file_content, overwrite=True, content_type=content_type
            )
            return key
        except Exception as e:
            raise StorageError(
                f"Failed to upload file to Azure Blob Storage: {str(e)}"
            )

    def download_file(self, file_id: uuid.UUID, file_format: str) -> bytes:
        """Download file from Azure Blob Storage."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        key = self._get_key(file_id, file_format)
        return self.download_file_by_key(key)

    def download_file_by_key(self, key: str) -> bytes:
        """Download file content from Azure Blob Storage using an explicit key path."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        _, ResourceNotFoundError, _, _, _ = _get_azure_libs()

        try:
            blob_client = self.container_client.get_blob_client(key)
            return blob_client.download_blob().readall()
        except ResourceNotFoundError:
            raise StorageError(f"File not found in Azure Blob Storage: {key}")
        except Exception as e:
            raise StorageError(
                f"Failed to download file from Azure Blob Storage: {str(e)}"
            )

    def delete_file(self, file_id: uuid.UUID, file_format: str) -> bool:
        """Delete file from Azure Blob Storage."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        try:
            key = self._get_key(file_id, file_format)
            return self.delete_file_by_key(key)
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"Unexpected error deleting file from Azure Blob Storage: {str(e)}"
            )

    def delete_file_by_key(self, key: str) -> bool:
        """Delete file from Azure Blob Storage by key."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        _, ResourceNotFoundError, _, _, _ = _get_azure_libs()

        try:
            blob_client = self.container_client.get_blob_client(key)
            if not blob_client.exists():
                return False
            blob_client.delete_blob()
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            raise StorageError(
                f"Failed to delete file from Azure Blob Storage: {str(e)}"
            )

    def delete_keys(self, keys: List[str]) -> tuple[int, List[dict]]:
        """Bulk-delete a list of Azure blob keys. Returns (deleted_count, errors)."""
        if not keys:
            return 0, []

        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        deduped = list({k for k in keys if k})
        deleted = 0
        errors: List[dict] = []

        for start in range(0, len(deduped), 256):
            chunk = deduped[start : start + 256]
            try:
                self.container_client.delete_blobs(*chunk)
                deleted += len(chunk)
            except Exception as e:
                msg = str(e)
                for key in chunk:
                    errors.append({"Key": key, "Code": "DeleteError", "Message": msg})

        return deleted, errors

    def delete_keys_by_prefix(self, prefix: str) -> tuple[int, List[dict]]:
        """List and bulk-delete every object whose key starts with ``prefix``."""
        if not prefix:
            return 0, []

        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        keys: List[str] = []
        try:
            for blob in self.container_client.list_blobs(name_starts_with=prefix):
                if blob.name:
                    keys.append(blob.name)
        except Exception as e:
            raise StorageError(
                f"Failed to list Azure blobs under {prefix!r}: {e}"
            )

        if not keys:
            return 0, []

        return self.delete_keys(keys)

    def file_exists(self, file_id: uuid.UUID, file_format: str) -> bool:
        """Check if file exists in Azure Blob Storage."""
        self._ensure_initialized()
        if not self.is_enabled():
            return False

        try:
            key = self._get_key(file_id, file_format)
            return self.container_client.get_blob_client(key).exists()
        except Exception:
            return False

    def list_audio_files(
        self,
        prefix: Optional[str] = None,
        max_keys: int = 1000,
        organization_id: Optional[str] = None,
    ) -> List[dict]:
        """List audio files in Azure container."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        try:
            if organization_id:
                search_prefix = f"{self.prefix}organizations/{organization_id}/audio/"
            else:
                search_prefix = prefix if prefix else self.prefix

            files = []
            for blob in self.container_client.list_blobs(
                name_starts_with=search_prefix
            ):
                if len(files) >= max_keys:
                    break
                key = blob.name
                if any(
                    key.lower().endswith(f".{fmt}")
                    for fmt in settings.ALLOWED_AUDIO_FORMATS
                ):
                    last_modified = blob.last_modified
                    files.append(
                        {
                            "key": key,
                            "size": blob.size or 0,
                            "last_modified": (
                                last_modified.isoformat() if last_modified else ""
                            ),
                            "filename": Path(key).name,
                        }
                    )

            return files
        except Exception as e:
            raise StorageError(
                f"Failed to list files in Azure Blob Storage: {str(e)}"
            )

    def get_organization_root_prefix(self, organization_id: str) -> str:
        """Get the root Azure prefix for a given organization."""
        return get_organization_root_prefix(settings.AZURE_PREFIX, organization_id)

    def browse_folder(
        self,
        organization_id: str,
        path: str = "",
        max_keys: int = 1000,
    ) -> dict:
        """Browse a folder within an organization's Azure namespace."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        org_root = self.get_organization_root_prefix(organization_id)
        full_prefix = f"{org_root}{path}"
        if full_prefix and not full_prefix.endswith("/"):
            full_prefix += "/"

        try:
            folders = []
            files = []
            seen_folders = set()

            for item in self.container_client.walk_blobs(
                name_starts_with=full_prefix, delimiter="/"
            ):
                if len(folders) + len(files) >= max_keys:
                    break

                if hasattr(item, "prefix") and item.prefix:
                    prefix_name = item.prefix
                    if prefix_name not in seen_folders:
                        seen_folders.add(prefix_name)
                        relative = prefix_name[len(org_root) :]
                        folder_name = relative.rstrip("/").rsplit("/", 1)[-1]
                        folders.append({"name": folder_name, "path": relative})
                elif hasattr(item, "name") and item.name:
                    key = item.name
                    if key == full_prefix:
                        continue
                    last_modified = getattr(item, "last_modified", None)
                    files.append(
                        {
                            "key": key,
                            "filename": Path(key).name,
                            "size": getattr(item, "size", 0) or 0,
                            "last_modified": (
                                last_modified.isoformat() if last_modified else ""
                            ),
                        }
                    )

            return {
                "folders": folders,
                "files": files,
                "current_path": path,
                "organization_id": organization_id,
            }
        except Exception as e:
            raise StorageError(
                f"Failed to browse Azure Blob Storage folder: {str(e)}"
            )

    def generate_presigned_url(
        self, file_id: uuid.UUID, file_format: str, expiration: int = 3600
    ) -> str:
        """Generate a SAS URL for temporary file access."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        key = self._get_key(file_id, file_format)
        return self.generate_presigned_url_by_key(key, expiration=expiration)

    def generate_presigned_url_by_key(self, key: str, expiration: int = 3600) -> str:
        """Generate a SAS URL for temporary file access by key."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = (
                self._initialization_error
                or "Azure Blob Storage is not enabled or not configured"
            )
            raise StorageError(error_msg)

        _, _, generate_blob_sas, BlobSasPermissions, _ = _get_azure_libs()

        account_key = self._get_account_key_for_sas()
        account_name = self._resolved_account_name or self._resolve_credentials()[0]
        if not account_key or not account_name:
            raise StorageError(
                "Azure Blob Storage SAS URLs require an account key. "
                "Set azure.connection_string or azure.account_key."
            )

        try:
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.bucket_name,
                blob_name=key,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(UTC) + timedelta(seconds=expiration),
            )
            blob_client = self.container_client.get_blob_client(key)
            return f"{blob_client.url}?{sas_token}"
        except Exception as e:
            raise StorageError(f"Failed to generate SAS URL: {str(e)}")


# Singleton instance
azure_blob_service = AzureBlobService()
