"""Audio file management routes."""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4
from typing import List
from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import AudioFile
from app.models.schemas import AudioFileResponse, MessageResponse
from app.services.storage_service import storage_service
from app.services.audio_service import AudioService
from app.core.exceptions import AudioFileNotFoundError, StorageError
from uuid import UUID

router = APIRouter(prefix="/audio", tags=["Audio"])
audio_service = AudioService()


@router.post("/upload", response_model=AudioFileResponse, status_code=201)
def upload_audio_file(
    file: UploadFile = File(...),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Upload an audio file.

    Args:
        file: Audio file to upload
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        Created audio file metadata
    """
    try:
        # Validate and save file
        file_id = uuid4()
        file_path, file_size = storage_service.save_file(file, file_id)

        # Extract metadata
        try:
            metadata = audio_service.extract_metadata(file_path)
        except Exception as e:
            # If metadata extraction fails, still save the file but with minimal metadata
            metadata = {"duration": None, "sample_rate": None, "channels": None}

        # Get file format
        file_ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

        # Create database record
        audio_file = AudioFile(
            id=file_id,
            organization_id=organization_id,
            filename=file.filename,
            file_path=file_path,
            file_size=file_size,
            format=file_ext,
            duration=metadata.get("duration"),
            sample_rate=metadata.get("sample_rate"),
            channels=metadata.get("channels"),
        )
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)

        return audio_file

    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


@router.get("/{audio_id}", response_model=AudioFileResponse)
def get_audio_file(
    audio_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Get audio file metadata.

    Args:
        audio_id: Audio file ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        Audio file metadata
    """
    try:
        file_id = UUID(audio_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audio ID format")

    audio_file = db.query(AudioFile).filter(
        AudioFile.id == file_id,
        AudioFile.organization_id == organization_id
    ).first()
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")

    return audio_file


@router.get("/{audio_id}/download")
def download_audio_file(
    audio_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Download audio file.

    Args:
        audio_id: Audio file ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        File response
    """
    from fastapi.responses import FileResponse
    from pathlib import Path

    try:
        file_id = UUID(audio_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audio ID format")

    audio_file = db.query(AudioFile).filter(
        AudioFile.id == file_id,
        AudioFile.organization_id == organization_id
    ).first()
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")

    file_path = Path(audio_file.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")

    return FileResponse(
        path=file_path,
        filename=audio_file.filename,
        media_type="audio/*",
    )


@router.delete("/{audio_id}", response_model=MessageResponse)
def delete_audio_file(
    audio_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Delete audio file.

    Args:
        audio_id: Audio file ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        Success message
    """
    try:
        file_id = UUID(audio_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid audio ID format")

    audio_file = db.query(AudioFile).filter(
        AudioFile.id == file_id,
        AudioFile.organization_id == organization_id
    ).first()
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Delete file from storage
    try:
        storage_service.delete_file(audio_file.id, audio_file.format)
    except Exception as e:
        # Log the error but continue - file might already be deleted
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to delete file from storage: {str(e)}")

    # Delete database record
    try:
        db.delete(audio_file)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete audio file: {str(e)}")

    return {"message": "Audio file deleted successfully"}


@router.get("", response_model=List[AudioFileResponse])
def list_audio_files(
    skip: int = 0,
    limit: int = 100,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    List all audio files (paginated) for the organization.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session

    Returns:
        List of audio files
    """
    audio_files = db.query(AudioFile).filter(
        AudioFile.organization_id == organization_id
    ).offset(skip).limit(limit).all()
    return audio_files

