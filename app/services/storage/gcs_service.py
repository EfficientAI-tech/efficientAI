"""GCS service for handling audio file storage and retrieval from Google Cloud Storage."""

import os
import uuid
from datetime import timedelta
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

_GCS_LIBS: Optional[
    Tuple[Any, Any, Any, Any]
] = None


_GCS_EXCEPTION_LIBS: Optional[Tuple[Any, Any, Any]] = None


def _get_gcs_exception_types() -> Tuple[Any, Any, Any]:
    """Import GCS exception types without requiring google.cloud.storage."""
    global _GCS_EXCEPTION_LIBS
    if _GCS_EXCEPTION_LIBS is None:
        try:
            from google.api_core.exceptions import Forbidden, NotFound
        except ImportError as exc:
            raise ImportError(
                "google-cloud-storage is required for GCS blob storage. "
                "Install with: pip install 'google-cloud-storage>=2.14.0'"
            ) from exc
        try:
            from google.cloud.exceptions import GoogleCloudError
        except ImportError:
            GoogleCloudError = Exception
        _GCS_EXCEPTION_LIBS = (Forbidden, NotFound, GoogleCloudError)
    return _GCS_EXCEPTION_LIBS

def _get_gcs_libs() -> Tuple[Any, Any, Any, Any]:
    """Import google-cloud-storage lazily so S3-only installs can start."""
    global _GCS_LIBS
    if _GCS_LIBS is None:
        try:
            from google.cloud import storage
            Forbidden, NotFound, GoogleCloudError = _get_gcs_exception_types()
        except ImportError as exc:
            raise ImportError(
                "google-cloud-storage is required for GCS blob storage. "
                "Install with: pip install 'google-cloud-storage>=2.14.0'"
            ) from exc
        _GCS_LIBS = (storage, Forbidden, NotFound, GoogleCloudError)
    return _GCS_LIBS


def _resolve_credentials_path() -> Optional[str]:
    """Resolve GCS credentials path from config or env (supports relative paths)."""
    raw = settings.GCS_CREDENTIALS_PATH or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve()
    return str(resolved) if resolved.exists() else str(path)


class GcsService:
    """Service for managing GCS file storage."""

    def __init__(self):
        """Initialize GCS service with configuration."""
        self.gcs_client = None
        self.bucket = None
        self._initialization_error = None
        self._signing_credentials = None

    @property
    def enabled(self) -> bool:
        """Get GCS enabled status from settings."""
        return settings.GCS_ENABLED

    @property
    def bucket_name(self) -> Optional[str]:
        """Get GCS bucket name from settings."""
        return settings.GCS_BUCKET_NAME

    @property
    def prefix(self) -> str:
        """Get GCS prefix from settings."""
        return normalize_prefix(settings.GCS_PREFIX)

    def _build_client(self):
        """Create a GCS client using configured or default credentials."""
        storage, _, _, _ = _get_gcs_libs()
        creds_path = _resolve_credentials_path()
        if creds_path and Path(creds_path).exists():
            return storage.Client.from_service_account_json(
                creds_path,
                project=settings.GCS_PROJECT_ID,
            )
        if settings.GCS_PROJECT_ID:
            return storage.Client(project=settings.GCS_PROJECT_ID)
        return storage.Client()

    def _get_signing_credentials(self):
        """Return credentials that can sign V4 URLs (service account with private key)."""
        if self._signing_credentials is not None:
            return self._signing_credentials

        creds_path = _resolve_credentials_path()
        if creds_path and Path(creds_path).exists():
            from google.oauth2 import service_account

            self._signing_credentials = service_account.Credentials.from_service_account_file(
                creds_path
            )
            return self._signing_credentials

        if self.gcs_client is not None:
            creds = getattr(self.gcs_client, "_credentials", None)
            if creds is not None and getattr(creds, "signer", None) is not None:
                self._signing_credentials = creds
                return creds

        return None

    def _ensure_initialized(self):
        """Lazily initialize GCS client if not already initialized."""
        if self.gcs_client is not None and self.bucket is not None:
            return

        if not self.enabled:
            return

        if not self.bucket_name:
            self._initialization_error = "GCS is enabled but bucket_name is not configured"
            return

        try:
            self.gcs_client = self._build_client()
            self.bucket = self.gcs_client.bucket(self.bucket_name)

            if not self.bucket.exists():
                self._initialization_error = f"GCS bucket '{self.bucket_name}' does not exist"
                self.gcs_client = None
                self.bucket = None
                return
        except ImportError as exc:
            self._initialization_error = str(exc)
            self.gcs_client = None
            self.bucket = None
            return
        except Exception as e:
            try:
                Forbidden, _, GoogleCloudError = _get_gcs_exception_types()
            except ImportError:
                Forbidden = ()
                GoogleCloudError = ()
            if isinstance(e, Forbidden):
                self._initialization_error = (
                    f"Access denied to GCS bucket '{self.bucket_name}'. Check credentials."
                )
            elif isinstance(e, GoogleCloudError):
                self._initialization_error = f"Failed to connect to GCS bucket: {str(e)}"
            else:
                self._initialization_error = f"Failed to initialize GCS service: {str(e)}"
            self.gcs_client = None
            self.bucket = None

    def reset_connection(self):
        """Reset lazy initialization state (for connection tests)."""
        self.gcs_client = None
        self.bucket = None
        self._initialization_error = None
        self._signing_credentials = None

    def is_enabled(self) -> bool:
        """Check if GCS is enabled and configured."""
        if not self.enabled:
            return False
        self._ensure_initialized()
        return self.gcs_client is not None and self.bucket is not None

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
        """Generate GCS object key for a file."""
        return build_object_key(
            file_id,
            file_format,
            settings.GCS_PREFIX,
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
        """Upload file to GCS."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()
        try:
            key = self._get_key(
                file_id, file_format, organization_id, evaluator_id, meaningful_id
            )
            content_type = content_type_for_format(file_format)
            blob = self.bucket.blob(key)
            blob.upload_from_string(file_content, content_type=content_type)
            return key
        except GoogleCloudError as e:
            raise StorageError(f"Failed to upload file to GCS: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error uploading file to GCS: {str(e)}")

    def upload_file_by_key(
        self, file_content: bytes, key: str, content_type: str = "audio/mpeg"
    ) -> str:
        """Upload file to GCS using an explicit key path."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()

        try:
            blob = self.bucket.blob(key)
            blob.upload_from_string(file_content, content_type=content_type)
            return key
        except GoogleCloudError as e:
            raise StorageError(f"Failed to upload file to GCS: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error uploading file to GCS: {str(e)}")

    def download_file(self, file_id: uuid.UUID, file_format: str) -> bytes:
        """Download file from GCS."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        key = self._get_key(file_id, file_format)
        return self.download_file_by_key(key)

    def download_file_by_key(self, key: str) -> bytes:
        """Download file content from GCS using an explicit key path."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()

        try:
            blob = self.bucket.blob(key)
            return blob.download_as_bytes()
        except NotFound:
            raise StorageError(f"File not found in GCS: {key}")
        except GoogleCloudError as e:
            raise StorageError(f"Failed to download file from GCS: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error downloading file from GCS: {str(e)}")

    def delete_file(self, file_id: uuid.UUID, file_format: str) -> bool:
        """Delete file from GCS."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()

        try:
            key = self._get_key(file_id, file_format)
            return self.delete_file_by_key(key)
        except StorageError:
            raise
        except GoogleCloudError as e:
            raise StorageError(f"Failed to delete file from GCS: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error deleting file from GCS: {str(e)}")

    def delete_file_by_key(self, key: str) -> bool:
        """Delete file from GCS by key."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()

        try:
            blob = self.bucket.blob(key)
            if not blob.exists():
                return False
            blob.delete()
            return True
        except GoogleCloudError as e:
            raise StorageError(f"Failed to delete file from GCS: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error deleting file from GCS: {str(e)}")

    def delete_keys(self, keys: List[str]) -> tuple[int, List[dict]]:
        """Bulk-delete a list of GCS object keys. Returns (deleted_count, errors)."""
        if not keys:
            return 0, []

        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()
        deduped = list({k for k in keys if k})
        deleted = 0
        errors: List[dict] = []

        for key in deduped:
            try:
                blob = self.bucket.blob(key)
                blob.delete()
                deleted += 1
            except NotFound:
                deleted += 1
            except GoogleCloudError as e:
                errors.append({"Key": key, "Code": "DeleteError", "Message": str(e)})
            except Exception as e:
                errors.append({"Key": key, "Code": "DeleteError", "Message": str(e)})

        return deleted, errors

    def delete_keys_by_prefix(self, prefix: str) -> tuple[int, List[dict]]:
        """List and bulk-delete every object whose key starts with ``prefix``."""
        if not prefix:
            return 0, []

        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()
        keys: List[str] = []
        try:
            for blob in self.gcs_client.list_blobs(self.bucket_name, prefix=prefix):
                if blob.name:
                    keys.append(blob.name)
        except GoogleCloudError as e:
            raise StorageError(f"Failed to list GCS objects under {prefix!r}: {e}")

        if not keys:
            return 0, []

        return self.delete_keys(keys)

    def file_exists(self, file_id: uuid.UUID, file_format: str) -> bool:
        """Check if file exists in GCS."""
        self._ensure_initialized()
        if not self.is_enabled():
            return False

        try:
            key = self._get_key(file_id, file_format)
            return self.bucket.blob(key).exists()
        except Exception:
            return False

    def list_audio_files(
        self,
        prefix: Optional[str] = None,
        max_keys: int = 1000,
        organization_id: Optional[str] = None,
    ) -> List[dict]:
        """List audio files in GCS bucket."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()

        try:
            if organization_id:
                search_prefix = f"{self.prefix}organizations/{organization_id}/audio/"
            else:
                search_prefix = prefix if prefix else self.prefix

            files = []
            for blob in self.gcs_client.list_blobs(
                self.bucket_name, prefix=search_prefix, max_results=max_keys
            ):
                key = blob.name
                if any(
                    key.lower().endswith(f".{fmt}")
                    for fmt in settings.ALLOWED_AUDIO_FORMATS
                ):
                    updated = blob.updated or blob.time_created
                    files.append(
                        {
                            "key": key,
                            "size": blob.size or 0,
                            "last_modified": updated.isoformat() if updated else "",
                            "filename": Path(key).name,
                        }
                    )

            return files
        except GoogleCloudError as e:
            raise StorageError(f"Failed to list files in GCS: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error listing files in GCS: {str(e)}")

    def get_organization_root_prefix(self, organization_id: str) -> str:
        """Get the root GCS prefix for a given organization."""
        return get_organization_root_prefix(settings.GCS_PREFIX, organization_id)

    def browse_folder(
        self,
        organization_id: str,
        path: str = "",
        max_keys: int = 1000,
    ) -> dict:
        """Browse a folder within an organization's GCS namespace."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        org_root = self.get_organization_root_prefix(organization_id)
        full_prefix = f"{org_root}{path}"
        if full_prefix and not full_prefix.endswith("/"):
            full_prefix += "/"

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()

        try:
            iterator = self.gcs_client.list_blobs(
                self.bucket_name,
                prefix=full_prefix,
                delimiter="/",
                max_results=max_keys,
            )

            folders = []
            files = []
            for page in iterator.pages:
                for prefix_name in page.prefixes:
                    relative = prefix_name[len(org_root):]
                    folder_name = relative.rstrip("/").rsplit("/", 1)[-1]
                    folders.append({"name": folder_name, "path": relative})

                for blob in page:
                    key = blob.name
                    if key == full_prefix:
                        continue
                    updated = blob.updated or blob.time_created
                    files.append(
                        {
                            "key": key,
                            "filename": Path(key).name,
                            "size": blob.size or 0,
                            "last_modified": updated.isoformat() if updated else "",
                        }
                    )

            return {
                "folders": folders,
                "files": files,
                "current_path": path,
                "organization_id": organization_id,
            }
        except GoogleCloudError as e:
            raise StorageError(f"Failed to browse GCS folder: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error browsing GCS folder: {str(e)}")

    def generate_presigned_url(
        self, file_id: uuid.UUID, file_format: str, expiration: int = 3600
    ) -> str:
        """Generate a signed URL for temporary file access."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        key = self._get_key(file_id, file_format)
        return self.generate_presigned_url_by_key(key, expiration=expiration)

    def generate_presigned_url_by_key(self, key: str, expiration: int = 3600) -> str:
        """Generate a signed URL for temporary file access by key."""
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "GCS is not enabled or not configured"
            raise StorageError(error_msg)

        _, NotFound, GoogleCloudError = _get_gcs_exception_types()

        credentials = self._get_signing_credentials()
        if credentials is None:
            raise StorageError(
                "GCS signed URLs require a service account JSON with a private key. "
                "Set gcs.credentials_path or GOOGLE_APPLICATION_CREDENTIALS."
            )

        try:
            blob = self.bucket.blob(key)
            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expiration),
                method="GET",
                credentials=credentials,
            )
            return url
        except GoogleCloudError as e:
            raise StorageError(f"Failed to generate signed URL: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error generating signed URL: {str(e)}")


# Singleton instance
gcs_service = GcsService()
