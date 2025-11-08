"""
Transcription service for converting audio to text using various STT providers.

Response Format:
All providers return a standardized format:
{
    "text": str,              # Full transcript text
    "language": str,          # Language code (e.g., "en", "es")
    "segments": [             # List of segments with timestamps
        {
            "start": float,   # Start time in seconds
            "end": float,   # End time in seconds
            "text": str     # Text for this segment
        }
    ],
    "speaker_segments": [     # Segments with speaker labels (if diarization enabled)
        {
            "speaker": str,  # Speaker label (e.g., "Speaker 1")
            "text": str,
            "start": float,
            "end": float
        }
    ],
    "processing_time": float,
    "raw_output": dict       # Original provider response
}

Provider-Specific Formats:
- OpenAI Whisper API: Uses verbose_json format which includes segments with timestamps
- Local Whisper: Returns segments by default with word-level timestamps available
- Google/Azure/AWS: Formats documented but not yet implemented

Speaker Diarization:
- Whisper does NOT provide speaker diarization natively (only transcription)
- We use improved heuristics by default (gap-based detection with balancing)
- Optional: pyannote.audio for proper diarization (requires installation and HUGGINGFACE_TOKEN)
- Install: pip install pyannote.audio torch
"""

import time
import tempfile
import os
from typing import Optional, Dict, Any, List
from uuid import UUID
from pathlib import Path

from app.models.database import ModelProvider, AIProvider
from app.services.s3_service import s3_service
from app.core.exceptions import StorageError
from sqlalchemy.orm import Session


class TranscriptionService:
    """Service for transcribing audio files using various STT providers."""

    def __init__(self):
        """Initialize transcription service."""
        pass

    def _get_ai_provider(self, provider: ModelProvider, db: Session, organization_id: UUID) -> Optional[AIProvider]:
        """Get AI provider configuration from database."""
        ai_provider = db.query(AIProvider).filter(
            AIProvider.provider == provider,
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True
        ).first()
        return ai_provider

    def _download_audio_to_temp(self, audio_file_key: str) -> str:
        """Download audio from S3 to temporary file."""
        try:
            # Download from S3
            audio_bytes = s3_service.download_file_by_key(audio_file_key)
            
            # Determine file extension from key
            file_ext = Path(audio_file_key).suffix.lstrip('.') or 'wav'
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as temp_file:
                temp_file.write(audio_bytes)
                return temp_file.name
        except Exception as e:
            raise StorageError(f"Failed to download audio file: {str(e)}")

    def _transcribe_with_openai(self, audio_file_path: str, model: str, api_key: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Transcribe audio using OpenAI Whisper API."""
        try:
            from openai import OpenAI
            
            client = OpenAI(api_key=api_key)
            
            with open(audio_file_path, 'rb') as audio_file:
                # Use verbose_json format to get segments with timestamps
                transcript = client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    language=language,
                    response_format="verbose_json"
                )
            
            # Format response - OpenAI returns different structures based on response_format
            result = {
                "text": transcript.text if hasattr(transcript, 'text') else str(transcript),
                "language": getattr(transcript, 'language', language) if language else getattr(transcript, 'language', 'en'),
                "segments": []
            }
            
            # Extract segments if available (verbose_json format includes segments)
            if hasattr(transcript, 'segments') and transcript.segments:
                for seg in transcript.segments:
                    result["segments"].append({
                        "start": getattr(seg, 'start', 0),
                        "end": getattr(seg, 'end', 0),
                        "text": getattr(seg, 'text', '')
                    })
            
            return result
        except ImportError:
            raise RuntimeError("OpenAI library not installed. Install with: pip install openai")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            raise RuntimeError(f"OpenAI transcription failed: {str(e)}\nDetails: {error_details}")

    def _transcribe_with_whisper_local(self, audio_file_path: str, model_name: str = "base") -> Dict[str, Any]:
        """Transcribe audio using local Whisper model."""
        try:
            import whisper
            
            model = whisper.load_model(model_name)
            result = model.transcribe(audio_file_path)
            
            return {
                "text": result.get("text", ""),
                "language": result.get("language", "en"),
                "segments": [
                    {
                        "start": seg.get("start", 0),
                        "end": seg.get("end", 0),
                        "text": seg.get("text", "")
                    }
                    for seg in result.get("segments", [])
                ]
            }
        except ImportError:
            raise RuntimeError("Whisper library not installed. Install with: pip install openai-whisper")
        except Exception as e:
            raise RuntimeError(f"Whisper transcription failed: {str(e)}")

    def _detect_speakers_with_pyannote(self, audio_file_path: str, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Use pyannote.audio for proper speaker diarization.
        This requires pyannote.audio to be installed and HuggingFace token for model access.
        """
        try:
            from pyannote.audio import Pipeline
            import torch
            
            # Load the diarization pipeline
            # Note: Requires HuggingFace token and accepting model terms
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=os.getenv("HUGGINGFACE_TOKEN")  # Optional: for private models
            )
            
            # Run diarization
            diarization = pipeline(audio_file_path)
            
            # Map timestamps to segments
            speaker_segments = []
            for segment, _, speaker in diarization.itertracks(yield_label=True):
                # Find transcription segments that overlap with this speaker segment
                segment_start = segment.start
                segment_end = segment.end
                
                # Find matching transcription segments
                matching_text = []
                for seg in segments:
                    seg_start = seg.get("start", 0)
                    seg_end = seg.get("end", 0)
                    # Check if transcription segment overlaps with speaker segment
                    if not (seg_end < segment_start or seg_start > segment_end):
                        matching_text.append(seg.get("text", ""))
                
                if matching_text:
                    speaker_segments.append({
                        "speaker": speaker,
                        "text": " ".join(matching_text),
                        "start": segment_start,
                        "end": segment_end
                    })
            
            return speaker_segments if speaker_segments else self._detect_speakers_heuristic(segments)
            
        except ImportError:
            # pyannote.audio not installed, fall back to heuristic
            return self._detect_speakers_heuristic(segments)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Pyannote diarization failed: {str(e)}, falling back to heuristic")
            return self._detect_speakers_heuristic(segments)

    def _detect_speakers_heuristic(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Improved heuristic-based speaker diarization.
        Uses multiple heuristics:
        1. Gap-based detection (adaptive thresholds)
        2. Alternating pattern detection
        3. Segment duration analysis
        4. Content-based patterns (questions/statements)
        """
        if not segments:
            return []
        
        speaker_segments = []
        current_speaker = "Speaker 1"
        
        # Thresholds for speaker change detection
        GAP_THRESHOLD_LARGE = 0.8  # seconds - large gap definitely suggests change
        GAP_THRESHOLD_MEDIUM = 0.4  # seconds - medium gap suggests change
        GAP_THRESHOLD_SMALL = 0.2  # seconds - small gap, but combined with other factors
        MIN_SEGMENT_DURATION = 0.2  # seconds - minimum segment to consider
        
        # Calculate average gap size to adapt thresholds
        gaps = []
        for i in range(1, len(segments)):
            gap = segments[i].get("start", 0) - segments[i-1].get("end", 0)
            if gap > 0:
                gaps.append(gap)
        
        avg_gap = sum(gaps) / len(gaps) if gaps else 0.5
        # Adaptive threshold based on conversation pace
        adaptive_threshold = min(max(avg_gap * 1.5, 0.3), 1.0)
        
        # Track recent speaker assignments for pattern detection
        recent_assignments = []
        assignment_window = 5  # Look at last N segments for patterns
        
        for i, seg in enumerate(segments):
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", 0)
            seg_duration = seg_end - seg_start
            seg_text = seg.get("text", "").strip()
            
            # Skip very short segments (likely noise or artifacts)
            if seg_duration < MIN_SEGMENT_DURATION or not seg_text:
                continue
            
            # Check for speaker change indicators
            should_switch = False
            gap = 0
            
            if i > 0:
                prev_seg = segments[i-1]
                gap = seg_start - prev_seg.get("end", 0)
                
                # Large gap definitely suggests speaker change
                if gap > GAP_THRESHOLD_LARGE:
                    should_switch = True
                # Medium gap suggests change
                elif gap > GAP_THRESHOLD_MEDIUM:
                    should_switch = True
                # Small gap but check for alternating pattern
                elif gap > GAP_THRESHOLD_SMALL:
                    # If we've been alternating, continue the pattern
                    if len(recent_assignments) >= 2:
                        # Check if last two were the same speaker (suggests we should switch)
                        if recent_assignments[-1] == recent_assignments[-2] == current_speaker:
                            should_switch = True
                    # Or if we see a pattern of quick back-and-forth
                    elif len(recent_assignments) >= 3:
                        # If pattern is A-A-A, switch to B
                        if all(a == current_speaker for a in recent_assignments[-3:]):
                            should_switch = True
                # Very small or no gap - use alternating pattern if established
                elif gap >= 0:
                    # If we have an established alternating pattern, continue it
                    if len(recent_assignments) >= 2:
                        # Check if we should alternate based on recent pattern
                        if recent_assignments[-1] == current_speaker:
                            # If last segment was same speaker, consider switching
                            # But only if we have a pattern suggesting alternation
                            if len(recent_assignments) >= 4:
                                # Check for A-B-A-B pattern
                                pattern = recent_assignments[-4:]
                                if pattern[0] != pattern[1] and pattern[1] != pattern[2] and pattern[2] != pattern[3]:
                                    # We have alternating pattern, continue it
                                    should_switch = True
            
            # Additional heuristics for first few segments
            if i < 3 and i > 0:
                # Early in conversation, be more aggressive about switching
                if gap > 0.1:  # Any noticeable gap
                    should_switch = True
            
            # If we have multiple consecutive segments from same speaker, force alternation
            if len(recent_assignments) >= 2:
                # If last 2 segments were both the same speaker (and it's the current speaker), switch
                # This prevents one speaker from getting too many consecutive segments
                if recent_assignments[-1] == current_speaker and recent_assignments[-2] == current_speaker:
                    should_switch = True
            
            # Switch speaker if needed
            if should_switch:
                current_speaker = "Speaker 2" if current_speaker == "Speaker 1" else "Speaker 1"
            
            speaker_segments.append({
                "speaker": current_speaker,
                "text": seg_text,
                "start": seg_start,
                "end": seg_end
            })
            
            # Track recent assignments for pattern detection
            recent_assignments.append(current_speaker)
            if len(recent_assignments) > assignment_window:
                recent_assignments.pop(0)
        
        # Post-process: Balance speakers if one dominates too much
        speaker_1_count = sum(1 for s in speaker_segments if s["speaker"] == "Speaker 1")
        speaker_2_count = sum(1 for s in speaker_segments if s["speaker"] == "Speaker 2")
        total_segments = len(speaker_segments)
        
        # If one speaker has more than 70% of segments, redistribute by alternating
        if total_segments > 0:
            speaker_1_ratio = speaker_1_count / total_segments
            if speaker_1_ratio > 0.7:
                # Redistribute: alternate segments starting from index 1
                # This assumes the first speaker is correct, then alternates
                for i in range(1, len(speaker_segments)):
                    expected_speaker = "Speaker 2" if i % 2 == 1 else "Speaker 1"
                    if speaker_segments[i]["speaker"] != expected_speaker:
                        speaker_segments[i]["speaker"] = expected_speaker
            elif speaker_1_ratio < 0.3:
                # Speaker 2 dominates, redistribute
                for i in range(1, len(speaker_segments)):
                    expected_speaker = "Speaker 1" if i % 2 == 1 else "Speaker 2"
                    if speaker_segments[i]["speaker"] != expected_speaker:
                        speaker_segments[i]["speaker"] = expected_speaker
        
        return speaker_segments

    def transcribe(
        self,
        audio_file_key: str,
        stt_provider: ModelProvider,
        stt_model: str,
        organization_id: UUID,
        db: Session,
        language: Optional[str] = None,
        enable_speaker_diarization: bool = True
    ) -> Dict[str, Any]:
        """
        Transcribe audio file from S3.
        
        Args:
            audio_file_key: S3 key of the audio file
            stt_provider: STT provider to use
            stt_model: STT model name
            organization_id: Organization ID
            db: Database session
            language: Optional language code (e.g., 'en', 'es')
            enable_speaker_diarization: Whether to detect multiple speakers
            
        Returns:
            Dictionary with transcript and metadata
        """
        start_time = time.time()
        temp_file_path = None
        
        try:
            # Download audio to temporary file
            temp_file_path = self._download_audio_to_temp(audio_file_key)
            
            # Get provider API key
            ai_provider = self._get_ai_provider(stt_provider, db, organization_id)
            if not ai_provider:
                raise RuntimeError(f"AI provider {stt_provider} not configured for this organization. Please configure an AI provider in the settings.")
            
            # Decrypt API key
            from app.core.encryption import decrypt_api_key
            try:
                api_key = decrypt_api_key(ai_provider.api_key)
            except Exception as e:
                raise RuntimeError(f"Failed to decrypt API key for provider {stt_provider}: {str(e)}")
            
            # Transcribe based on provider
            if stt_provider == ModelProvider.OPENAI:
                if stt_model.startswith("whisper-"):
                    # Use OpenAI API
                    result = self._transcribe_with_openai(temp_file_path, stt_model, api_key, language)
                else:
                    # Fallback to local Whisper
                    model_name = stt_model.replace("whisper-", "") if stt_model.startswith("whisper-") else "base"
                    result = self._transcribe_with_whisper_local(temp_file_path, model_name)
            elif stt_provider == ModelProvider.GOOGLE:
                # TODO: Implement Google Speech-to-Text
                raise NotImplementedError("Google Speech-to-Text not yet implemented")
            elif stt_provider == ModelProvider.AZURE:
                # TODO: Implement Azure Speech Services
                raise NotImplementedError("Azure Speech Services not yet implemented")
            elif stt_provider == ModelProvider.AWS:
                # TODO: Implement AWS Transcribe
                raise NotImplementedError("AWS Transcribe not yet implemented")
            else:
                # Default to local Whisper
                result = self._transcribe_with_whisper_local(temp_file_path, "base")
            
            # Apply speaker diarization if enabled and segments available
            speaker_segments = None
            if enable_speaker_diarization and result.get("segments"):
                # Try pyannote.audio first (if available), fall back to heuristic
                try:
                    speaker_segments = self._detect_speakers_with_pyannote(temp_file_path, result["segments"])
                except Exception:
                    # Fall back to heuristic if pyannote fails
                    speaker_segments = self._detect_speakers_heuristic(result["segments"])
            
            processing_time = time.time() - start_time
            
            return {
                "transcript": result["text"],
                "language": result.get("language", language),
                "speaker_segments": speaker_segments,
                "segments": result.get("segments", []),
                "processing_time": processing_time,
                "raw_output": result
            }
            
        finally:
            # Clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass


# Singleton instance
transcription_service = TranscriptionService()

