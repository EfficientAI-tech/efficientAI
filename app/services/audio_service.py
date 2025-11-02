"""Audio processing service for extracting metadata and handling audio files."""

import librosa
import soundfile as sf
from pathlib import Path
from typing import Optional, Tuple
from app.core.exceptions import AudioFileNotFoundError


class AudioService:
    """Service for audio file processing and metadata extraction."""

    def extract_metadata(self, file_path: str) -> dict:
        """
        Extract metadata from audio file.

        Args:
            file_path: Path to audio file

        Returns:
            Dictionary containing metadata (duration, sample_rate, channels)

        Raises:
            AudioFileNotFoundError: If file doesn't exist
        """
        if not Path(file_path).exists():
            raise AudioFileNotFoundError(f"Audio file not found: {file_path}")

        try:
            # Use librosa to load audio and get metadata
            y, sr = librosa.load(file_path, sr=None)
            duration = librosa.get_duration(y=y, sr=sr)

            # Get number of channels using soundfile
            info = sf.info(file_path)
            channels = info.channels

            return {
                "duration": float(duration),
                "sample_rate": int(sr),
                "channels": channels,
            }
        except Exception as e:
            raise AudioFileNotFoundError(f"Failed to extract metadata: {str(e)}")

    def get_file_info(self, file_path: str) -> dict:
        """
        Get comprehensive file information.

        Args:
            file_path: Path to audio file

        Returns:
            Dictionary with file info
        """
        path = Path(file_path)
        if not path.exists():
            raise AudioFileNotFoundError(f"Audio file not found: {file_path}")

        metadata = self.extract_metadata(file_path)

        return {
            "file_path": file_path,
            "file_size": path.stat().st_size,
            **metadata,
        }

    def is_valid_audio_file(self, file_path: str) -> bool:
        """
        Check if file is a valid audio file.

        Args:
            file_path: Path to audio file

        Returns:
            True if valid, False otherwise
        """
        try:
            self.extract_metadata(file_path)
            return True
        except Exception:
            return False

