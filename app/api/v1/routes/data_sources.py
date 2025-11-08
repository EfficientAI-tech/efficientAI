"""Data sources API routes for S3 integration."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from uuid import UUID, uuid4
from typing import Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from app.dependencies import get_db, get_organization_id, get_api_key
from app.models.schemas import (
    S3ConnectionTest,
    S3ConnectionTestResponse,
    S3ListFilesResponse,
    S3UploadResponse,
    MessageResponse,
    AudioFileResponse,
)
from app.services.s3_service import s3_service
from app.services.storage_service import storage_service
from app.services.audio_service import AudioService
from app.models.database import AudioFile
from app.core.exceptions import StorageError
from app.config import settings

router = APIRouter(prefix="/data-sources", tags=["Data Sources"])
audio_service = AudioService()


@router.post("/s3/test-connection", response_model=S3ConnectionTestResponse)
async def test_s3_connection(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
):
    """
    Test S3 connection using existing configuration from config.yml.
    
    Args:
        api_key: Validated API key
        organization_id: Organization ID from API key
    
    Returns:
        Connection test result
    """
    # Check if S3 is enabled in config
    if not settings.S3_ENABLED:
        return S3ConnectionTestResponse(
            success=False,
            message="S3 is not enabled in configuration. Please enable it in config.yml",
        )
    
    # Check if required config is present
    if not settings.S3_BUCKET_NAME:
        return S3ConnectionTestResponse(
            success=False,
            message="S3 bucket name is not configured. Please set S3_BUCKET_NAME in config.yml",
        )
    
    if not settings.S3_ACCESS_KEY_ID or not settings.S3_SECRET_ACCESS_KEY:
        return S3ConnectionTestResponse(
            success=False,
            message="S3 credentials are not configured. Please set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY in config.yml",
        )
    
    try:
        # Reset initialization state to force re-initialization
        # This ensures we test with the latest config
        s3_service.s3_client = None
        s3_service._initialization_error = None
        
        # Use the S3 service to test connection
        s3_service._ensure_initialized()
        
        if not s3_service.is_enabled():
            error_msg = s3_service.get_status_message()
            return S3ConnectionTestResponse(
                success=False,
                message=error_msg or "S3 service is not properly initialized",
            )
        
        # Test connection by checking if bucket exists and is accessible
        s3_service.s3_client.head_bucket(Bucket=s3_service.bucket_name)
        
        # Connection successful - ensure error is cleared
        s3_service._initialization_error = None
        
        return S3ConnectionTestResponse(
            success=True,
            message=f"Successfully connected to S3 bucket '{s3_service.bucket_name}'",
            bucket_name=s3_service.bucket_name,
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            return S3ConnectionTestResponse(
                success=False,
                message=f"Bucket '{s3_service.bucket_name}' does not exist",
            )
        elif error_code == "403":
            return S3ConnectionTestResponse(
                success=False,
                message="Access denied. Check your credentials and bucket permissions in config.yml",
            )
        else:
            return S3ConnectionTestResponse(
                success=False,
                message=f"Failed to connect: {str(e)}",
            )
    except NoCredentialsError:
        return S3ConnectionTestResponse(
            success=False,
            message="Invalid credentials in configuration. Please check config.yml",
        )
    except Exception as e:
        return S3ConnectionTestResponse(
            success=False,
            message=f"Unexpected error: {str(e)}",
        )


@router.get("/s3/files", response_model=S3ListFilesResponse)
async def list_s3_files(
    prefix: Optional[str] = None,
    max_keys: int = 1000,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    List audio files from database (files uploaded to S3).
    
    Args:
        prefix: Optional prefix to filter files (not used, kept for compatibility)
        max_keys: Maximum number of files to return
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        List of files from database
    """
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        # Query audio files from database that are stored in S3 (file_path starts with S3 prefix)
        s3_prefix = s3_service.prefix
        query = db.query(AudioFile).filter(
            AudioFile.organization_id == organization_id
        )
        
        # Filter by S3 prefix if configured
        if s3_prefix:
            query = query.filter(AudioFile.file_path.like(f"{s3_prefix}%"))
        
        # Apply limit
        audio_files = query.order_by(AudioFile.uploaded_at.desc()).limit(max_keys).all()
        
        # Convert to S3FileInfo format
        files = []
        for audio_file in audio_files:
            # Extract key from file_path (which is the S3 key)
            key = audio_file.file_path
            files.append({
                "key": key,
                "filename": audio_file.filename,
                "size": audio_file.file_size,
                "last_modified": audio_file.uploaded_at.isoformat() if audio_file.uploaded_at else "",
            })
        
        return S3ListFilesResponse(
            files=files,
            total=len(files),
            prefix=prefix,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list files: {str(e)}",
        )


@router.post("/s3/upload", response_model=AudioFileResponse, status_code=status.HTTP_201_CREATED)
async def upload_to_s3(
    file: UploadFile = File(...),
    custom_filename: Optional[str] = Form(None),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Upload an audio file to S3 and create audio file record.
    
    Args:
        file: Audio file to upload
        custom_filename: Optional custom filename for the file
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        Created audio file metadata
    """
    
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured. Please configure S3 in your settings.",
        )
    
    try:
        # Generate unique file ID
        file_id = uuid4()
        
        # Validate file format
        file_ext, _ = storage_service.validate_file(file)
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Validate file size
        if file_size > storage_service.max_file_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size ({file_size / 1024 / 1024:.2f} MB) exceeds maximum allowed size "
                f"({storage_service.max_file_size / 1024 / 1024:.2f} MB)",
            )
        
        # Save to temporary file to extract metadata
        import tempfile
        import os
        temp_file = None
        metadata = {"duration": None, "sample_rate": None, "channels": None}
        
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            # Extract metadata from temporary file
            try:
                metadata = audio_service.extract_metadata(temp_file_path)
            except Exception as e:
                # If metadata extraction fails, continue with None values
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to extract audio metadata: {str(e)}")
                metadata = {"duration": None, "sample_rate": None, "channels": None}
            
            # Upload to S3
            s3_key = s3_service.upload_file(file_content, file_id, file_ext)
            
        finally:
            # Clean up temporary file
            if temp_file and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass
        
        # Determine filename - use custom name if provided, otherwise use original filename or generate one
        if custom_filename:
            # Ensure custom filename has the correct extension
            if not custom_filename.endswith(f".{file_ext}"):
                final_filename = f"{custom_filename}.{file_ext}"
            else:
                final_filename = custom_filename
        else:
            final_filename = file.filename or f"{file_id}.{file_ext}"
        
        # Create audio file record in database
        audio_file = AudioFile(
            id=file_id,
            organization_id=organization_id,
            filename=final_filename,
            format=file_ext,
            file_size=file_size,
            file_path=s3_key,  # Store S3 key as file_path
            duration=metadata.get("duration"),
            sample_rate=metadata.get("sample_rate"),
            channels=metadata.get("channels"),
        )
        
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)
        
        return audio_file
    except HTTPException:
        raise
    except StorageError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file to S3: {str(e)}",
        )


@router.get("/s3/files/{file_key:path}/download")
async def download_from_s3(
    file_key: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
):
    """
    Download a file from S3 by key.
    
    Args:
        file_key: S3 key (path) of the file (URL-encoded)
        api_key: Validated API key
        organization_id: Organization ID from API key
    
    Returns:
        File content
    """
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        # URL decode the file key
        from urllib.parse import unquote
        decoded_key = unquote(file_key)
        
        # Generate presigned URL for direct download by key
        url = s3_service.generate_presigned_url_by_key(decoded_key, expiration=3600)
        
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=url)
    except StorageError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}",
        )


@router.delete("/s3/files/{file_key:path}", response_model=MessageResponse)
async def delete_from_s3(
    file_key: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Delete a file from S3 by key.
    
    Args:
        file_key: S3 key (path) of the file (URL-encoded)
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        Success message
    """
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        # URL decode the file key (FastAPI automatically decodes path parameters)
        # But we need to handle cases where it might be double-encoded
        from urllib.parse import unquote
        decoded_key = unquote(file_key)
        
        # Delete from S3 using the service method
        deleted = s3_service.delete_file_by_key(decoded_key)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in S3")
        
        # Try to find and delete the database record if it exists
        # Extract file ID from key if possible (format: prefix/uuid.ext)
        try:
            # Key format is typically: audio/uuid.ext or just uuid.ext
            key_parts = decoded_key.split("/")
            filename = key_parts[-1]
            if "." in filename:
                file_id_str = filename.split(".")[0]
                try:
                    file_id = UUID(file_id_str)
                    audio_file = db.query(AudioFile).filter(
                        AudioFile.id == file_id,
                        AudioFile.organization_id == organization_id
                    ).first()
                    if audio_file:
                        db.delete(audio_file)
                        db.commit()
                except (ValueError, Exception):
                    # If we can't parse the ID or find the record, just continue
                    pass
        except Exception:
            # If database cleanup fails, that's okay - file is deleted from S3
            pass
        
        return {"message": "File deleted successfully from S3"}
    except HTTPException:
        raise
    except StorageError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {str(e)}",
        )


@router.get("/s3/status", response_model=dict)
async def get_s3_status(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
):
    """
    Get S3 service status and configuration info.
    
    Args:
        api_key: Validated API key
        organization_id: Organization ID from API key
    
    Returns:
        S3 service status
    """
    status_message = s3_service.get_status_message()
    
    return {
        "enabled": s3_service.is_enabled(),
        "error": status_message if status_message else None,
    }

