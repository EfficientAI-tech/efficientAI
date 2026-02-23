"""Data source routes for S3."""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import Optional
from pydantic import BaseModel
import io

from app.dependencies import get_api_key, get_organization_id
from app.models.schemas import MessageResponse, S3ListFilesResponse, S3FileInfo, S3BrowseResponse, S3FolderInfo
from app.services.s3_service import s3_service
from app.core.exceptions import StorageError
from uuid import UUID

router = APIRouter(prefix="/data-sources/s3", tags=["Data Sources"])


class S3StatusResponse(BaseModel):
    """Schema for S3 status response."""
    enabled: bool
    error: Optional[str] = None


@router.get("/status", response_model=S3StatusResponse, operation_id="getS3Status")
async def get_s3_status(api_key: str = Depends(get_api_key)):
    """Get S3 connection status and configuration info."""
    enabled = s3_service.is_enabled()
    error = s3_service.get_status_message()
    return {
        "enabled": enabled,
        "error": error
    }


@router.post("/test", response_model=MessageResponse, operation_id="testS3Connection")
async def test_s3_connection(api_key: str = Depends(get_api_key)):
    """Test S3 connection with current credentials."""
    s3_service.s3_client = None
    s3_service._initialization_error = None
    
    enabled = s3_service.is_enabled()
    if not enabled:
        error = s3_service.get_status_message() or "S3 is not enabled or not configured."
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"S3 connection test failed: {error}",
        )
    
    return {"message": "S3 connection successful"}


@router.get("/files", response_model=S3ListFilesResponse, operation_id="listS3Files")
async def list_s3_files(
    prefix: Optional[str] = None,
    max_keys: int = 1000,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
):
    """List all files in the organization's S3 namespace (recursive)."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        files = s3_service.list_audio_files(
            prefix=prefix,
            max_keys=max_keys,
            organization_id=str(organization_id),
        )
        file_list = [
            S3FileInfo(
                key=f["key"],
                filename=f["filename"],
                size=f["size"],
                last_modified=f["last_modified"]
            )
            for f in files
        ]
        return {
            "files": file_list,
            "total": len(file_list),
            "prefix": prefix,
        }
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list files from S3: {str(e)}",
        )


@router.get("/browse", response_model=S3BrowseResponse, operation_id="browseS3")
async def browse_s3(
    path: str = "",
    max_keys: int = 1000,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
):
    """Browse folders and files within the organization's S3 namespace."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        result = s3_service.browse_folder(
            organization_id=str(organization_id),
            path=path,
            max_keys=max_keys,
        )
        return S3BrowseResponse(
            folders=[S3FolderInfo(name=f["name"], path=f["path"]) for f in result["folders"]],
            files=[
                S3FileInfo(
                    key=f["key"],
                    filename=f["filename"],
                    size=f["size"],
                    last_modified=f["last_modified"],
                )
                for f in result["files"]
            ],
            current_path=result["current_path"],
            organization_id=result["organization_id"],
        )
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to browse S3: {str(e)}",
        )


@router.post("/upload", response_model=MessageResponse, operation_id="uploadToS3")
async def upload_to_s3(
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
):
    """Upload a file to the organization's S3 folder."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        file_content = await file.read()
        
        from uuid import uuid4
        import re
        file_id = uuid4()
        upload_filename = filename if filename else file.filename
        if not upload_filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required.",
            )
        
        file_format = upload_filename.rsplit(".", 1)[-1].lower() if "." in upload_filename else ""
        if not file_format:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must have an extension.",
            )
        
        name_without_ext = upload_filename.rsplit(".", 1)[0] if "." in upload_filename else upload_filename
        sanitized_name = re.sub(r'[^a-zA-Z0-9_\-]', '-', name_without_ext).strip('-')
        sanitized_name = re.sub(r'-+', '-', sanitized_name)
        short_id = str(file_id)[:8]
        meaningful_id = f"{sanitized_name}_{short_id}" if sanitized_name else str(file_id)
        
        key = s3_service.upload_file(
            file_content,
            file_id,
            file_format,
            organization_id=str(organization_id),
            meaningful_id=meaningful_id,
        )
        
        return {"message": f"File '{upload_filename}' uploaded successfully to S3."}
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file to S3: {str(e)}",
        )

@router.get("/files/{file_key:path}/download", operation_id="downloadFromS3")
async def download_from_s3(file_key: str, api_key: str = Depends(get_api_key)):
    """Download a file from the S3 bucket."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        file_bytes = s3_service.download_file_by_key(file_key)
        filename = file_key.split("/")[-1]
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
    except StorageError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in S3.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file from S3: {str(e)}",
        )


class PresignedUrlResponse(BaseModel):
    """Schema for presigned URL response."""
    url: str
    expires_in: int


@router.get("/files/{file_key:path}/presigned-url", response_model=PresignedUrlResponse, operation_id="getS3PresignedUrl")
async def get_s3_presigned_url(
    file_key: str,
    expiration: int = 3600,
    api_key: str = Depends(get_api_key),
):
    """Get presigned URL for S3 file playback/access."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        import urllib.parse
        decoded_key = urllib.parse.unquote(file_key)
        url = s3_service.generate_presigned_url_by_key(decoded_key, expiration=expiration)
        return PresignedUrlResponse(url=url, expires_in=expiration)
    except StorageError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in S3.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate presigned URL: {str(e)}",
        )


@router.delete("/files/{file_key:path}", response_model=MessageResponse, operation_id="deleteFromS3")
async def delete_from_s3(file_key: str, api_key: str = Depends(get_api_key)):
    """Delete a file from the S3 bucket."""
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        s3_service.delete_file_by_key(file_key)
        return {"message": "File deleted successfully from S3."}
    except StorageError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in S3.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file from S3: {str(e)}",
        )
