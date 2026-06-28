"""Storage service package exports."""

from app.services.storage.blob_storage_service import BlobStorageService, blob_storage_service
from app.services.storage.s3_service import S3Service
from app.services.storage.storage_service import StorageService, storage_service

# Backward-compatible alias used throughout the codebase
s3_service = blob_storage_service

__all__ = [
    "BlobStorageService",
    "blob_storage_service",
    "AzureBlobService",
    "azure_blob_service",
    "GcsService",
    "gcs_service",
    "S3Service",
    "s3_service",
    "StorageService",
    "storage_service",
]


def __getattr__(name: str):
    """Lazy-load GCS/Azure exports so S3-only installs can import this package."""
    if name == "GcsService":
        from app.services.storage.gcs_service import GcsService

        return GcsService
    if name == "gcs_service":
        from app.services.storage.gcs_service import gcs_service

        return gcs_service
    if name == "AzureBlobService":
        from app.services.storage.azure_blob_service import AzureBlobService

        return AzureBlobService
    if name == "azure_blob_service":
        from app.services.storage.azure_blob_service import azure_blob_service

        return azure_blob_service
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
