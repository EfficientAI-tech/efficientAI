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
- We use pyannote.audio (speaker-diarization-3.1) for accurate ML-based diarization
- Whisper provides word-level timestamps, pyannote identifies speakers, then we align
- Requires: pyannote.audio installed + diarization.huggingface_token in config.yml
- Falls back to unreliable gap-based heuristics if pyannote is unavailable
"""

import time
import tempfile
import os
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
from pathlib import Path

from app.models.database import ModelProvider, AIProvider
from app.services.s3_service import s3_service
from app.core.exceptions import StorageError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Service for transcribing audio files using various STT providers."""

    def __init__(self):
        """Initialize transcription service."""
        self._pyannote_pipeline = None

    def _get_ai_provider(self, provider: ModelProvider, db: Session, organization_id: UUID) -> Optional[AIProvider]:
        """Get AI provider configuration from database."""
        from sqlalchemy import func
        
        # Handle both string and enum comparisons (database might have uppercase or lowercase)
        provider_value = provider.value if hasattr(provider, 'value') else provider
        
        # Try exact match first
        ai_provider = db.query(AIProvider).filter(
            AIProvider.provider == provider_value,
            AIProvider.organization_id == organization_id,
            AIProvider.is_active == True
        ).first()
        
        # If not found, try case-insensitive match
        if not ai_provider:
            ai_provider = db.query(AIProvider).filter(
                func.lower(AIProvider.provider) == provider_value.lower(),
                AIProvider.organization_id == organization_id,
                AIProvider.is_active == True
            ).first()
        
        return ai_provider

    def _download_audio_to_temp(self, audio_file_key: str, db: Optional[Session] = None) -> str:
        """
        Download audio from S3 to temporary file, or use local file if S3 is not available.
        
        Args:
            audio_file_key: S3 key or local file path
            db: Optional database session to look up local file paths
            
        Returns:
            Path to temporary file (or original file if local)
        """
        import os
        
        # First, try S3 if enabled
        if s3_service.is_enabled():
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
                # If S3 download fails, fall through to local file check
                logger.warning(f"S3 download failed for {audio_file_key}: {e}, trying local file...")
        
        # Fallback: Try to find local file
        # Check if it's already a local file path
        if os.path.exists(audio_file_key):
            # It's a local file path, return it directly
            return audio_file_key
        
        # Try to look up in database if db session is provided
        if db:
            try:
                from app.models.database import AudioFile
                # Try to find by S3 key or file path
                audio_file = db.query(AudioFile).filter(
                    (AudioFile.file_path == audio_file_key) | 
                    (AudioFile.file_path.like(f"%{audio_file_key}%"))
                ).first()
                
                if audio_file and os.path.exists(audio_file.file_path):
                    return audio_file.file_path
            except Exception as e:
                logger.warning(f"Database lookup failed for {audio_file_key}: {e}")
        
        # If all else fails, raise error
        raise StorageError(f"Failed to download audio file: S3 is not enabled and local file not found for key: {audio_file_key}")

    def _transcribe_with_openai(self, audio_file_path: str, model: str, api_key: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Transcribe audio using OpenAI Whisper API with word-level timestamps."""
        try:
            from openai import OpenAI
            
            client = OpenAI(api_key=api_key)
            
            with open(audio_file_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"]
                )
            
            result = {
                "text": transcript.text if hasattr(transcript, 'text') else str(transcript),
                "language": getattr(transcript, 'language', language) if language else getattr(transcript, 'language', 'en'),
                "segments": [],
                "words": []
            }
            
            # Extract segments
            if hasattr(transcript, 'segments') and transcript.segments:
                for seg in transcript.segments:
                    result["segments"].append({
                        "start": getattr(seg, 'start', 0),
                        "end": getattr(seg, 'end', 0),
                        "text": getattr(seg, 'text', '')
                    })
                logger.info(f"OpenAI transcription returned {len(result['segments'])} segments")
            elif isinstance(transcript, dict) and 'segments' in transcript:
                for seg in transcript['segments']:
                    result["segments"].append({
                        "start": seg.get('start', 0),
                        "end": seg.get('end', 0),
                        "text": seg.get('text', '')
                    })
                logger.info(f"OpenAI transcription returned {len(result['segments'])} segments (dict format)")
            
            # Extract word-level timestamps (critical for pyannote alignment)
            if hasattr(transcript, 'words') and transcript.words:
                first_word = transcript.words[0]
                # Log the raw object to diagnose timestamp extraction
                logger.info(
                    f"OpenAI word sample: repr={repr(first_word)}, "
                    f"type={type(first_word).__name__}, "
                    f"dir={[a for a in dir(first_word) if not a.startswith('_')]}"
                )
                for w in transcript.words:
                    # Handle both object attributes and dict-like access
                    if isinstance(w, dict):
                        word_text = w.get('word', '')
                        word_start = w.get('start', 0) or 0
                        word_end = w.get('end', 0) or 0
                    else:
                        word_text = getattr(w, 'word', '') or ''
                        word_start = getattr(w, 'start', None)
                        word_end = getattr(w, 'end', None)
                        # Some SDK versions may use 'start_time'/'end_time'
                        if word_start is None:
                            word_start = getattr(w, 'start_time', 0) or 0
                        if word_end is None:
                            word_end = getattr(w, 'end_time', 0) or 0
                        word_start = float(word_start) if word_start else 0.0
                        word_end = float(word_end) if word_end else 0.0
                    result["words"].append({
                        "word": word_text,
                        "start": word_start,
                        "end": word_end
                    })
                # Log first few words with their timestamps
                sample_words = result["words"][:5]
                logger.info(f"OpenAI transcription: {len(result['words'])} words. First 5: {sample_words}")
            elif isinstance(transcript, dict) and 'words' in transcript:
                for w in transcript['words']:
                    result["words"].append({
                        "word": w.get('word', ''),
                        "start": w.get('start', 0) or 0,
                        "end": w.get('end', 0) or 0
                    })
                logger.info(f"OpenAI transcription returned {len(result['words'])} words (dict format)")
            
            # Fallback: create segments from full text if none returned
            if not result["segments"] and result["text"]:
                logger.warning("OpenAI transcription returned no segments, creating segments from full text")
                import re
                sentences = re.split(r'[.!?]+\s+', result["text"].strip())
                sentences = [s.strip() for s in sentences if s.strip()]
                
                if sentences:
                    total_words = len(result["text"].split())
                    estimated_duration = max(1.0, (total_words / 150.0) * 60.0)
                    
                    current_time = 0.0
                    for sentence in sentences:
                        sentence_words = len(sentence.split())
                        sentence_duration = max(0.5, (sentence_words / 150.0) * 60.0)
                        result["segments"].append({
                            "start": current_time,
                            "end": current_time + sentence_duration,
                            "text": sentence
                        })
                        current_time += sentence_duration
                    logger.info(f"Created {len(result['segments'])} segments from full text")
                else:
                    word_count = len(result["text"].split())
                    estimated_duration = max(1.0, (word_count / 150.0) * 60.0)
                    result["segments"] = [{
                        "start": 0.0,
                        "end": estimated_duration,
                        "text": result["text"]
                    }]
            
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

    def _get_pyannote_pipeline(self):
        """Load and cache the pyannote diarization pipeline."""
        if self._pyannote_pipeline is not None:
            return self._pyannote_pipeline

        # Compatibility shim: list_audio_backends was removed in torchaudio 2.4+
        import torchaudio
        if not hasattr(torchaudio, 'list_audio_backends'):
            torchaudio.list_audio_backends = lambda: ["ffmpeg"]

        from pyannote.audio import Pipeline
        from app.config import settings

        hf_token = settings.HUGGINGFACE_TOKEN
        if not hf_token:
            raise RuntimeError(
                "HUGGINGFACE_TOKEN not configured. Set it under 'diarization.huggingface_token' "
                "in config.yml. Required for pyannote speaker diarization."
            )

        logger.info("Loading pyannote speaker-diarization-3.1 pipeline (first call, will be cached)...")
        self._pyannote_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token
        )
        logger.info("Pyannote pipeline loaded successfully")
        return self._pyannote_pipeline

    def _detect_speakers_with_pyannote(
        self, audio_file_path: str, segments: List[Dict[str, Any]],
        words: Optional[List[Dict[str, Any]]] = None,
        num_speakers: Optional[int] = 2,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Use pyannote.audio for ML-based speaker diarization, aligned with
        Whisper word timestamps for accurate speaker-text mapping.

        Args:
            num_speakers: If set, forces pyannote to produce exactly this many
                speaker clusters. Defaults to 2 (agent + customer), which greatly
                improves accuracy on mono phone recordings.
            min_speakers: Optional lower bound on speaker count.
            max_speakers: Optional upper bound on speaker count.

        Raises exceptions on failure so the caller can handle fallback and logging.
        """
        pipeline = self._get_pyannote_pipeline()

        # Build pipeline kwargs for speaker count hints
        pipeline_kwargs = {}
        if num_speakers is not None:
            pipeline_kwargs["num_speakers"] = num_speakers
        if min_speakers is not None:
            pipeline_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            pipeline_kwargs["max_speakers"] = max_speakers

        logger.info(
            f"Running pyannote diarization on {audio_file_path} "
            f"(speaker hints: {pipeline_kwargs or 'auto'})"
        )
        raw_output = pipeline(audio_file_path, **pipeline_kwargs)

        # Handle different return types across pyannote versions:
        # - Older versions: Annotation directly (has itertracks)
        # - Newer versions: DiarizeOutput with .speaker_diarization attribute
        if hasattr(raw_output, 'itertracks'):
            annotation = raw_output
        elif hasattr(raw_output, 'speaker_diarization'):
            annotation = raw_output.speaker_diarization
        elif hasattr(raw_output, 'annotation'):
            annotation = raw_output.annotation
        elif isinstance(raw_output, tuple):
            annotation = raw_output[0]
        else:
            attrs = [a for a in dir(raw_output) if not a.startswith('_')]
            raise TypeError(
                f"Unexpected pyannote output type: {type(raw_output).__name__}. "
                f"Available attributes: {attrs}"
            )

        # Collect diarization turns as a sorted list for fast lookup
        diar_turns = []
        raw_labels = set()
        for turn, _, speaker_label in annotation.itertracks(yield_label=True):
            diar_turns.append((turn.start, turn.end, speaker_label))
            raw_labels.add(speaker_label)

        if not diar_turns:
            logger.warning("Pyannote returned no speaker turns")
            return []

        # Normalize labels: SPEAKER_00 -> "Speaker 1", SPEAKER_01 -> "Speaker 2", etc.
        sorted_labels = sorted(raw_labels)
        label_map = {lbl: f"Speaker {i + 1}" for i, lbl in enumerate(sorted_labels)}
        # Log speaker distribution
        speaker_counts = {}
        for _, _, lbl in diar_turns:
            speaker_counts[label_map[lbl]] = speaker_counts.get(label_map[lbl], 0) + 1
        logger.info(f"Pyannote detected {len(sorted_labels)} speakers, {len(diar_turns)} turns. Distribution: {speaker_counts}")
        for i, (t_start, t_end, lbl) in enumerate(diar_turns):
            logger.info(f"  Turn {i}: {label_map[lbl]} [{t_start:.2f}s - {t_end:.2f}s]")

        def find_speaker(midpoint: float) -> str:
            """Find which speaker is active at a given timestamp."""
            for t_start, t_end, lbl in diar_turns:
                if t_start <= midpoint <= t_end:
                    return label_map[lbl]
            # No exact match -- find the closest turn
            min_dist = float('inf')
            closest_label = label_map[diar_turns[0][2]]
            for t_start, t_end, lbl in diar_turns:
                dist = min(abs(midpoint - t_start), abs(midpoint - t_end))
                if dist < min_dist:
                    min_dist = dist
                    closest_label = label_map[lbl]
            return closest_label

        # Prefer word-level alignment when words with timestamps are available
        if words and len(words) > 0:
            logger.info(
                f"Aligning {len(words)} words with pyannote speaker turns "
                f"(sample: {words[:3]})"
            )
            # Debug: log speaker assignment for first 10 words
            for i, w in enumerate(words[:10]):
                mid = (w.get("start", 0) + w.get("end", 0)) / 2.0
                spk = find_speaker(mid)
                logger.info(f"  Word {i}: '{w.get('word', '')}' mid={mid:.3f}s -> {spk}")

            speaker_segments = []
            current_speaker = None
            current_words: List[str] = []
            current_start = 0.0
            current_end = 0.0

            for w in words:
                word_text = w.get("word", "").strip()
                w_start = w.get("start", 0)
                w_end = w.get("end", 0)
                if not word_text:
                    continue

                midpoint = (w_start + w_end) / 2.0
                speaker = find_speaker(midpoint)

                if speaker != current_speaker:
                    if current_words and current_speaker:
                        speaker_segments.append({
                            "speaker": current_speaker,
                            "text": " ".join(current_words).strip(),
                            "start": round(current_start, 3),
                            "end": round(current_end, 3)
                        })
                    current_speaker = speaker
                    current_words = [word_text]
                    current_start = w_start
                    current_end = w_end
                else:
                    current_words.append(word_text)
                    current_end = w_end

            if current_words and current_speaker:
                speaker_segments.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_words).strip(),
                    "start": round(current_start, 3),
                    "end": round(current_end, 3)
                })

            logger.info(f"Word-level alignment produced {len(speaker_segments)} speaker segments")
            return speaker_segments

        # Fallback: align at segment level when word timestamps are not available
        logger.info(f"No word timestamps available, aligning {len(segments)} segments with pyannote turns")
        speaker_segments = []
        for seg in segments:
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", 0)
            seg_text = seg.get("text", "").strip()
            if not seg_text:
                continue

            midpoint = (seg_start + seg_end) / 2.0
            speaker = find_speaker(midpoint)

            speaker_segments.append({
                "speaker": speaker,
                "text": seg_text,
                "start": round(seg_start, 3),
                "end": round(seg_end, 3)
            })

        logger.info(f"Segment-level alignment produced {len(speaker_segments)} speaker segments")
        return speaker_segments

    def _detect_speakers_heuristic(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Heuristic-based speaker diarization fallback. Uses gap-based detection
        which is unreliable -- pyannote.audio should be used for accurate results.
        """
        logger.warning(
            "Using heuristic speaker diarization (unreliable). For accurate results, "
            "install pyannote.audio and configure diarization.huggingface_token in config.yml"
        )
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
            temp_file_path = self._download_audio_to_temp(audio_file_key, db=db)
            
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
            
            # Apply speaker diarization if enabled
            speaker_segments = None
            if enable_speaker_diarization:
                segments = result.get("segments", [])
                
                # If no segments from transcription, create a single segment from the full text
                if not segments and result.get("text"):
                    logger.warning("No segments returned from transcription, creating single segment from full text")
                    # Create a single segment with the full transcription
                    # We'll estimate duration if available, otherwise use a default
                    estimated_duration = 0.0
                    if hasattr(result, 'duration') and result.get('duration'):
                        estimated_duration = result.get('duration')
                    elif audio_file_path and os.path.exists(audio_file_path):
                        try:
                            import librosa
                            duration = librosa.get_duration(path=audio_file_path)
                            estimated_duration = duration
                        except:
                            pass
                    
                    segments = [{
                        "start": 0.0,
                        "end": estimated_duration if estimated_duration > 0 else 10.0,  # Default to 10s if unknown
                        "text": result.get("text", "")
                    }]
                
                if segments:
                    words = result.get("words", [])
                    # Check if words actually have valid timestamps
                    valid_word_count = sum(1 for w in words if w.get("start", 0) > 0 or w.get("end", 0) > 0)
                    if words and valid_word_count == 0:
                        logger.warning(
                            f"All {len(words)} words have zero timestamps, will use segment-level alignment"
                        )
                        words = []
                    elif words:
                        logger.info(f"{valid_word_count}/{len(words)} words have valid timestamps")

                    diarization_method = "unknown"
                    try:
                        from app.config import settings as app_settings
                        num_spk = getattr(app_settings, 'DIARIZATION_NUM_SPEAKERS', 2)
                        speaker_segments = self._detect_speakers_with_pyannote(
                            temp_file_path, segments, words, num_speakers=num_spk
                        )
                        if speaker_segments:
                            alignment = "word-level" if words else "segment-level"
                            diarization_method = f"pyannote.audio ({alignment})"
                        else:
                            logger.info("Pyannote returned no speaker segments, falling back to heuristic")
                            speaker_segments = self._detect_speakers_heuristic(segments)
                            diarization_method = "heuristic (pyannote returned empty)"
                    except Exception as e:
                        logger.warning(f"Pyannote diarization failed: {str(e)}, falling back to heuristic")
                        speaker_segments = self._detect_speakers_heuristic(segments)
                        diarization_method = f"heuristic (pyannote failed: {type(e).__name__})"
                    logger.info(f"Speaker diarization method used: {diarization_method}")
                else:
                    logger.warning("No segments available for speaker diarization")
            
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

