"""S3 service for handling audio file storage and retrieval from S3 buckets."""

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Optional, List, BinaryIO
from pathlib import Path
import uuid
from app.config import settings
from app.core.exceptions import StorageError


class S3Service:
    """Service for managing S3 file storage."""

    def __init__(self):
        """Initialize S3 service with configuration."""
        self.s3_client = None
        self._initialization_error = None
    
    @property
    def enabled(self) -> bool:
        """Get S3 enabled status from settings."""
        return settings.S3_ENABLED
    
    @property
    def bucket_name(self) -> Optional[str]:
        """Get S3 bucket name from settings."""
        return settings.S3_BUCKET_NAME
    
    @property
    def region(self) -> str:
        """Get S3 region from settings."""
        return settings.S3_REGION
    
    @property
    def prefix(self) -> str:
        """Get S3 prefix from settings."""
        return settings.S3_PREFIX.rstrip("/") + "/" if settings.S3_PREFIX else ""

    def _ensure_initialized(self):
        """Lazily initialize S3 client if not already initialized."""
        if self.s3_client is not None:
            return
        
        if not self.enabled:
            return
        
        if not self.bucket_name:
            self._initialization_error = "S3 is enabled but bucket_name is not configured"
            return
        
        try:
            # Initialize S3 client
            s3_kwargs = {
                "region_name": self.region,
            }
            
            # Add credentials if provided
            if settings.S3_ACCESS_KEY_ID and settings.S3_SECRET_ACCESS_KEY:
                s3_kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY_ID
                s3_kwargs["aws_secret_access_key"] = settings.S3_SECRET_ACCESS_KEY
            else:
                self._initialization_error = "S3 credentials not configured"
                return
            
            # Add endpoint URL for S3-compatible services (e.g., MinIO, DigitalOcean Spaces)
            if settings.S3_ENDPOINT_URL:
                s3_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
            
            self.s3_client = boto3.client("s3", **s3_kwargs)
            
            # Test connection by checking if bucket exists (non-blocking)
            try:
                self.s3_client.head_bucket(Bucket=self.bucket_name)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "404":
                    self._initialization_error = f"S3 bucket '{self.bucket_name}' does not exist"
                    self.s3_client = None
                elif error_code == "403":
                    self._initialization_error = f"Access denied to S3 bucket '{self.bucket_name}'. Check credentials."
                    self.s3_client = None
                else:
                    self._initialization_error = f"Failed to connect to S3 bucket: {str(e)}"
                    self.s3_client = None
            except NoCredentialsError:
                self._initialization_error = "S3 credentials not found. Check your configuration."
                self.s3_client = None
                
        except Exception as e:
            self._initialization_error = f"Failed to initialize S3 service: {str(e)}"
            self.s3_client = None

    def is_enabled(self) -> bool:
        """Check if S3 is enabled and configured."""
        if not self.enabled:
            return False
        self._ensure_initialized()
        return self.s3_client is not None
    
    def get_status_message(self) -> Optional[str]:
        """Get status message if there's an initialization error."""
        if not self.enabled:
            return None
        self._ensure_initialized()
        return self._initialization_error

    def _get_key(self, file_id: uuid.UUID, file_format: str, organization_id: Optional[str] = None) -> str:
        """Generate S3 key for a file."""
        base_key = f"{file_id}.{file_format}"
        if organization_id:
            # Organize files by organization: prefix/organizations/{org_id}/audio/{file_id}.{format}
            return f"{self.prefix}organizations/{organization_id}/audio/{base_key}"
        return f"{self.prefix}{base_key}"

    def upload_file(self, file_content: bytes, file_id: uuid.UUID, file_format: str, organization_id: Optional[str] = None) -> str:
        """
        Upload file to S3.

        Args:
            file_content: File content as bytes
            file_id: Unique identifier for the file
            file_format: File format extension
            organization_id: Optional organization ID to organize files in folders

        Returns:
            S3 key (path) of the uploaded file

        Raises:
            StorageError: If upload fails
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            key = self._get_key(file_id, file_format, organization_id)
            
            # Determine content type based on file format
            content_type_map = {
                "wav": "audio/wav",
                "mp3": "audio/mpeg",
                "flac": "audio/flac",
                "m4a": "audio/mp4",
            }
            content_type = content_type_map.get(file_format.lower(), "application/octet-stream")

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_content,
                ContentType=content_type,
            )

            return key
        except ClientError as e:
            raise StorageError(f"Failed to upload file to S3: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error uploading file to S3: {str(e)}")

    def download_file(self, file_id: uuid.UUID, file_format: str) -> bytes:
        """
        Download file from S3.

        Args:
            file_id: File identifier
            file_format: File format extension

        Returns:
            File content as bytes

        Raises:
            StorageError: If download fails or file not found
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            key = self._get_key(file_id, file_format)
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                raise StorageError(f"File not found in S3: {key}")
            raise StorageError(f"Failed to download file from S3: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error downloading file from S3: {str(e)}")

    def delete_file(self, file_id: uuid.UUID, file_format: str) -> bool:
        """
        Delete file from S3.

        Args:
            file_id: File identifier
            file_format: File format extension

        Returns:
            True if file was deleted, False if it didn't exist

        Raises:
            StorageError: If delete fails
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            key = self._get_key(file_id, file_format)
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                return False
            raise StorageError(f"Failed to delete file from S3: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error deleting file from S3: {str(e)}")

    def delete_file_by_key(self, key: str) -> bool:
        """
        Delete file from S3 by key.

        Args:
            key: S3 key (path) of the file

        Returns:
            True if file was deleted, False if it didn't exist

        Raises:
            StorageError: If delete fails
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                return False
            raise StorageError(f"Failed to delete file from S3: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error deleting file from S3: {str(e)}")

    def file_exists(self, file_id: uuid.UUID, file_format: str) -> bool:
        """
        Check if file exists in S3.

        Args:
            file_id: File identifier
            file_format: File format extension

        Returns:
            True if file exists, False otherwise
        """
        self._ensure_initialized()
        if not self.is_enabled():
            return False

        try:
            key = self._get_key(file_id, file_format)
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "404":
                return False
            # For other errors, assume file doesn't exist
            return False
        except Exception:
            return False

    def list_audio_files(self, prefix: Optional[str] = None, max_keys: int = 1000, organization_id: Optional[str] = None) -> List[dict]:
        """
        List audio files in S3 bucket.

        Args:
            prefix: Optional prefix to filter files (defaults to configured prefix)
            max_keys: Maximum number of keys to return
            organization_id: Optional organization ID to filter files for a specific organization

        Returns:
            List of file metadata dictionaries with keys: key, size, last_modified

        Raises:
            StorageError: If listing fails
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            if organization_id:
                # List files for specific organization
                search_prefix = f"{self.prefix}organizations/{organization_id}/audio/"
            else:
                search_prefix = prefix if prefix else self.prefix
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=search_prefix,
                MaxKeys=max_keys,
            )

            files = []
            if "Contents" in response:
                for obj in response["Contents"]:
                    # Filter to only audio files
                    key = obj["Key"]
                    if any(key.lower().endswith(f".{fmt}") for fmt in settings.ALLOWED_AUDIO_FORMATS):
                        files.append({
                            "key": key,
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                            "filename": Path(key).name,
                        })

            return files
        except ClientError as e:
            raise StorageError(f"Failed to list files in S3: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error listing files in S3: {str(e)}")

    def download_file_by_key(self, key: str) -> bytes:
        """
        Download file from S3 by key.

        Args:
            key: S3 key (path) of the file

        Returns:
            File content as bytes

        Raises:
            StorageError: If download fails or file not found
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                raise StorageError(f"File not found in S3: {key}")
            raise StorageError(f"Failed to download file from S3: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error downloading file from S3: {str(e)}")

    def generate_presigned_url(self, file_id: uuid.UUID, file_format: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for temporary file access.

        Args:
            file_id: File identifier
            file_format: File format extension
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL string

        Raises:
            StorageError: If URL generation fails
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            key = self._get_key(file_id, file_format)
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            raise StorageError(f"Failed to generate presigned URL: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error generating presigned URL: {str(e)}")

    def generate_presigned_url_by_key(self, key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for temporary file access by key.

        Args:
            key: S3 key (path) of the file
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL string

        Raises:
            StorageError: If URL generation fails
        """
        self._ensure_initialized()
        if not self.is_enabled():
            error_msg = self._initialization_error or "S3 is not enabled or not configured"
            raise StorageError(error_msg)

        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            raise StorageError(f"Failed to generate presigned URL: {str(e)}")
        except Exception as e:
            raise StorageError(f"Unexpected error generating presigned URL: {str(e)}")


# Singleton instance
s3_service = S3Service()

