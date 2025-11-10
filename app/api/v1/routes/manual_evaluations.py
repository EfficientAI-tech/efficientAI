"""Manual evaluations routes for transcribing S3 audio files."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import ManualTranscription, ModelProvider, AudioFile
from app.models.schemas import MessageResponse, S3ListFilesResponse, S3FileInfo
from app.services.transcription_service import transcription_service
from app.services.s3_service import s3_service

router = APIRouter(prefix="/manual-evaluations", tags=["Manual Evaluations"])


class TranscriptionRequest(BaseModel):
    """Request schema for transcription."""
    audio_file_key: str
    stt_provider: ModelProvider
    stt_model: str
    name: Optional[str] = None  # User-friendly name for the transcription
    language: Optional[str] = None
    enable_speaker_diarization: bool = True


class TranscriptionResponse(BaseModel):
    """Response schema for transcription."""
    id: UUID
    name: Optional[str] = None
    audio_file_key: str
    transcript: str
    speaker_segments: Optional[List[dict]] = None
    stt_model: Optional[str] = None
    stt_provider: Optional[ModelProvider] = None
    language: Optional[str] = None
    processing_time: Optional[float] = None
    created_at: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class PresignedUrlResponse(BaseModel):
    """Response schema for presigned URL."""
    url: str
    expires_in: int


@router.get("/audio-files", response_model=S3ListFilesResponse, operation_id="listManualEvaluationAudioFiles")
async def list_audio_files(
    prefix: Optional[str] = None,
    max_keys: int = 1000,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    List audio files from S3 bucket for manual evaluation.
    
    Args:
        prefix: Optional prefix to filter files
        max_keys: Maximum number of files to return
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        List of audio files from S3
    """
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        # Query audio files from database that are stored in S3
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


@router.get("/audio-files/{file_key:path}/presigned-url", response_model=PresignedUrlResponse, operation_id="getAudioPresignedUrl")
async def get_presigned_url(
    file_key: str,
    expiration: int = 3600,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Get presigned URL for audio file playback.
    
    Args:
        file_key: S3 key (path) of the file (URL-encoded)
        expiration: URL expiration time in seconds (default: 1 hour)
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        Presigned URL for audio file
    """
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        from urllib.parse import unquote
        decoded_key = unquote(file_key)
        
        # Verify file belongs to organization
        audio_file = db.query(AudioFile).filter(
            AudioFile.file_path == decoded_key,
            AudioFile.organization_id == organization_id
        ).first()
        
        if not audio_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Audio file not found or access denied",
            )
        
        # Generate presigned URL
        url = s3_service.generate_presigned_url_by_key(decoded_key, expiration=expiration)
        
        return PresignedUrlResponse(url=url, expires_in=expiration)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate presigned URL: {str(e)}",
        )


@router.post("/transcribe", response_model=TranscriptionResponse, status_code=status.HTTP_201_CREATED, operation_id="transcribeAudio")
async def transcribe_audio(
    request: TranscriptionRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Transcribe audio file from S3 using STT model.
    
    Args:
        request: Transcription request with audio file key and STT model info
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        Transcription result
    """
    if not s3_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 is not enabled or not configured.",
        )
    
    try:
        # Verify file belongs to organization
        audio_file = db.query(AudioFile).filter(
            AudioFile.file_path == request.audio_file_key,
            AudioFile.organization_id == organization_id
        ).first()
        
        if not audio_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Audio file not found or access denied",
            )
        
        # Check if transcription already exists
        existing = db.query(ManualTranscription).filter(
            ManualTranscription.audio_file_key == request.audio_file_key,
            ManualTranscription.organization_id == organization_id
        ).first()
        
        # Transcribe audio
        try:
            result = transcription_service.transcribe(
                audio_file_key=request.audio_file_key,
                stt_provider=request.stt_provider,
                stt_model=request.stt_model,
                organization_id=organization_id,
                db=db,
                language=request.language,
                enable_speaker_diarization=request.enable_speaker_diarization
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Transcription failed: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Transcription failed: {str(e)}",
            )
        
        # Generate default name if not provided
        default_name = request.name or f"{request.stt_provider.value} - {request.stt_model} - {request.audio_file_key.split('/')[-1]}"
        
        # Save or update transcription
        if existing:
            existing.name = request.name if request.name else existing.name or default_name
            existing.transcript = result["transcript"]
            existing.speaker_segments = result.get("speaker_segments")
            existing.stt_model = request.stt_model
            existing.stt_provider = request.stt_provider
            existing.language = result.get("language")
            existing.processing_time = result["processing_time"]
            existing.raw_output = result.get("raw_output")
            db.commit()
            db.refresh(existing)
            transcription = existing
        else:
            transcription = ManualTranscription(
                organization_id=organization_id,
                name=default_name,
                audio_file_key=request.audio_file_key,
                transcript=result["transcript"],
                speaker_segments=result.get("speaker_segments"),
                stt_model=request.stt_model,
                stt_provider=request.stt_provider,
                language=result.get("language"),
                processing_time=result["processing_time"],
                raw_output=result.get("raw_output")
            )
            db.add(transcription)
            db.commit()
            db.refresh(transcription)
        
        return TranscriptionResponse(
            id=transcription.id,
            name=transcription.name,
            audio_file_key=transcription.audio_file_key,
            transcript=transcription.transcript,
            speaker_segments=transcription.speaker_segments,
            stt_model=transcription.stt_model,
            stt_provider=transcription.stt_provider,
            language=transcription.language,
            processing_time=transcription.processing_time,
            created_at=transcription.created_at.isoformat(),
            updated_at=transcription.updated_at.isoformat() if transcription.updated_at else None
        )
    except HTTPException:
        raise
    except RuntimeError as e:
        # RuntimeError from transcription service (e.g., provider not configured, decryption failed)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except NotImplementedError as e:
        # Provider not yet implemented
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(e),
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error during transcription: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {str(e)}",
        )


@router.get("/transcriptions", response_model=List[TranscriptionResponse], operation_id="listManualTranscriptions")
async def list_transcriptions(
    skip: int = 0,
    limit: int = 100,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    List manual transcriptions for the organization.
    
    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        List of transcriptions
    """
    try:
        transcriptions = db.query(ManualTranscription).filter(
            ManualTranscription.organization_id == organization_id
        ).order_by(ManualTranscription.created_at.desc()).offset(skip).limit(limit).all()
        
        return [
            TranscriptionResponse(
                id=t.id,
                name=t.name,
                audio_file_key=t.audio_file_key,
                transcript=t.transcript,
                speaker_segments=t.speaker_segments,
                stt_model=t.stt_model,
                stt_provider=t.stt_provider,
                language=t.language,
                processing_time=t.processing_time,
                created_at=t.created_at.isoformat(),
                updated_at=t.updated_at.isoformat() if t.updated_at else None
            )
            for t in transcriptions
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list transcriptions: {str(e)}",
        )


@router.get("/transcriptions/{transcription_id}", response_model=TranscriptionResponse, operation_id="getManualTranscription")
async def get_transcription(
    transcription_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Get transcription by ID.
    
    Args:
        transcription_id: Transcription ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        Transcription details
    """
    try:
        trans_id = UUID(transcription_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid transcription ID format")
    
    transcription = db.query(ManualTranscription).filter(
        ManualTranscription.id == trans_id,
        ManualTranscription.organization_id == organization_id
    ).first()
    
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    return TranscriptionResponse(
        id=transcription.id,
        name=transcription.name,
        audio_file_key=transcription.audio_file_key,
        transcript=transcription.transcript,
        speaker_segments=transcription.speaker_segments,
        stt_model=transcription.stt_model,
        stt_provider=transcription.stt_provider,
        language=transcription.language,
        processing_time=transcription.processing_time,
        created_at=transcription.created_at.isoformat(),
        updated_at=transcription.updated_at.isoformat() if transcription.updated_at else None
    )


@router.delete("/transcriptions/{transcription_id}", response_model=MessageResponse, operation_id="deleteManualTranscription")
async def delete_transcription(
    transcription_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """
    Delete transcription.
    
    Args:
        transcription_id: Transcription ID
        api_key: Validated API key
        organization_id: Organization ID from API key
        db: Database session
    
    Returns:
        Success message
    """
    try:
        trans_id = UUID(transcription_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid transcription ID format")
    
    transcription = db.query(ManualTranscription).filter(
        ManualTranscription.id == trans_id,
        ManualTranscription.organization_id == organization_id
    ).first()
    
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    db.delete(transcription)
    db.commit()
    
    return {"message": "Transcription deleted successfully"}

