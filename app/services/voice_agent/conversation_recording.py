"""Shared conversation recording for playground and telephony voice pipelines."""

from __future__ import annotations

import io
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

from loguru import logger

from app.services.storage.s3_service import s3_service

_track_tap_class_cache: dict[str, type] = {}


@dataclass
class RecordingTimeline:
    """Shared wall-clock origin for dual-track conversation recording."""

    start_time: float | None = None

    def mark_started(self) -> None:
        if self.start_time is None:
            self.start_time = time.time()

    @property
    def effective_start(self) -> float:
        return self.start_time if self.start_time is not None else time.time()


@dataclass
class ConversationRecordingCapture:
    """Accumulates user/bot audio from early input and late output wall-clock taps."""

    user_buffer: bytearray = field(default_factory=bytearray)
    bot_buffer: bytearray = field(default_factory=bytearray)
    sample_rate: int = 0

    @property
    def user_audio(self) -> bytes:
        return bytes(self.user_buffer)

    @property
    def bot_audio(self) -> bytes:
        return bytes(self.bot_buffer)

    def has_audio(self) -> bool:
        return len(self.user_audio) > 100 or len(self.bot_audio) > 100


def _pad_and_append_pcm(
    buffer: bytearray,
    *,
    pcm: bytes,
    timeline: RecordingTimeline,
    sample_rate: int,
    total_samples_written: int,
) -> int:
    """Insert wall-clock silence then append mono PCM; returns updated sample count."""
    if not pcm:
        return total_samples_written

    timeline.mark_started()
    elapsed = time.time() - timeline.effective_start
    expected_samples = int(elapsed * sample_rate)
    if expected_samples > total_samples_written:
        pad_samples = expected_samples - total_samples_written
        if pad_samples <= sample_rate * 30:
            buffer.extend(b"\x00" * (pad_samples * 2))
            total_samples_written += pad_samples

    num_samples = len(pcm) // 2
    buffer.extend(pcm)
    return total_samples_written + num_samples


def create_wall_clock_track_tap(
    capture: ConversationRecordingCapture,
    timeline: RecordingTimeline,
    *,
    track: Literal["user", "bot"],
    sample_rate: int,
):
    """
    Return a FrameProcessor that records one leg on a shared wall-clock timeline.

    User audio must be tapped immediately after transport.input(). Bot audio must
    be tapped after transport.output() so only audio actually sent to the client
    is recorded (interrupted / unplayed TTS is excluded).
    """
    cache_key = f"{track}:v3"
    if cache_key not in _track_tap_class_cache:
        from efficientai.audio.utils import create_stream_resampler
        from efficientai.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
        from efficientai.processors.frame_processor import FrameProcessor

        class _WallClockTrackTap(FrameProcessor):
            def __init__(
                self,
                capture: ConversationRecordingCapture,
                timeline: RecordingTimeline,
                *,
                track_name: Literal["user", "bot"],
                target_sample_rate: int,
            ):
                super().__init__()
                self._capture = capture
                self._timeline = timeline
                self._track_name = track_name
                self._target_sample_rate = target_sample_rate
                self._resampler = create_stream_resampler()
                self._total_samples_written = 0

            @property
            def _buffer(self) -> bytearray:
                return (
                    self._capture.user_buffer
                    if self._track_name == "user"
                    else self._capture.bot_buffer
                )

            async def _append_pcm(self, pcm: bytes) -> None:
                if not pcm:
                    return
                self._capture.sample_rate = self._target_sample_rate
                self._total_samples_written = _pad_and_append_pcm(
                    self._buffer,
                    pcm=pcm,
                    timeline=self._timeline,
                    sample_rate=self._target_sample_rate,
                    total_samples_written=self._total_samples_written,
                )

            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)

                if self._track_name == "user" and isinstance(frame, InputAudioRawFrame):
                    resampled = await self._resampler.resample(
                        frame.audio,
                        frame.sample_rate,
                        self._target_sample_rate,
                    )
                    await self._append_pcm(resampled)
                elif self._track_name == "bot" and isinstance(frame, OutputAudioRawFrame):
                    resampled = await self._resampler.resample(
                        frame.audio,
                        frame.sample_rate,
                        self._target_sample_rate,
                    )
                    await self._append_pcm(resampled)

                await self.push_frame(frame, direction)

        _track_tap_class_cache[cache_key] = _WallClockTrackTap

    tap_cls = _track_tap_class_cache[cache_key]
    return tap_cls(
        capture,
        timeline,
        track_name=track,
        target_sample_rate=sample_rate,
    )


def write_mono_wav(path: str, pcm: bytes, sample_rate: int) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _upload_mono_track_wav(
    pcm: bytes,
    *,
    sample_rate: int,
    organization_id: str | None,
    evaluator_id: str | None,
    meaningful_id: str,
) -> str:
    file_id = uuid.uuid4()
    return s3_service.upload_file(
        file_content=build_mono_wav_bytes(pcm, sample_rate=sample_rate),
        file_id=file_id,
        file_format="wav",
        organization_id=organization_id,
        evaluator_id=evaluator_id,
        meaningful_id=meaningful_id,
    )


def upload_conversation_recording(
    capture: ConversationRecordingCapture,
    *,
    call_start_time: float,
    organization_id: str | None = None,
    evaluator_id: str | None = None,
    result_id: str | None = None,
    prefer_stereo: bool = True,
    align_mode: Literal["wall_clock", "telephony"] = "wall_clock",
) -> Tuple[Optional[str], Optional[float], dict]:
    """
    Build stereo (and optional mono) artifacts from wall-clock tracks and upload to S3.

    Uses wall-clock interleaving by default (no extra telephony playback delay). Pass
    align_mode=\"telephony\" for legacy cross-correlation merge with bot delay padding.

    Returns (primary_s3_key, duration_seconds, metadata).
    """
    if not capture.has_audio():
        logger.warning("Conversation recording too small, skipping upload")
        return None, None, {}

    sample_rate = capture.sample_rate or 24000
    user_audio = capture.user_audio
    bot_audio = capture.bot_audio

    metadata: dict = {
        "recording_format": "stereo" if prefer_stereo else "mono",
        "recording_source": "pipeline",
        "sample_rate": sample_rate,
        "user_track_bytes": len(user_audio),
        "bot_track_bytes": len(bot_audio),
        "align_mode": align_mode,
    }

    duration = max(len(user_audio), len(bot_audio)) / (2 * sample_rate) if sample_rate else 0.0
    if duration <= 0:
        duration = time.time() - call_start_time

    stereo_key = None
    mono_key = None
    analysis = None

    if len(user_audio) > 100 and len(bot_audio) > 100:
        if align_mode == "telephony":
            from app.services.voice_agent.utils.telephony_audio_align import (
                merge_telephony_tracks_to_mono,
                merge_telephony_tracks_to_stereo,
            )
        else:
            from app.services.voice_agent.utils.telephony_audio_align import (
                merge_wall_clock_tracks_to_mono,
                merge_wall_clock_tracks_to_stereo,
            )

        import os

        user_fd, user_path = tempfile.mkstemp(suffix=".wav")
        bot_fd, bot_path = tempfile.mkstemp(suffix=".wav")
        stereo_fd, stereo_path = tempfile.mkstemp(suffix=".wav")
        mono_fd, mono_path = tempfile.mkstemp(suffix=".wav")
        os.close(user_fd)
        os.close(bot_fd)
        os.close(stereo_fd)
        os.close(mono_fd)
        try:
            write_mono_wav(user_path, user_audio, sample_rate)
            write_mono_wav(bot_path, bot_audio, sample_rate)

            file_id = uuid.uuid4()
            ts_suffix = f"{int(time.time())}-{file_id.hex[:8]}"
            user_key = _upload_mono_track_wav(
                user_audio,
                sample_rate=sample_rate,
                organization_id=organization_id,
                evaluator_id=evaluator_id,
                meaningful_id=f"user-{result_id}" if result_id else f"user-{ts_suffix}",
            )
            bot_key = _upload_mono_track_wav(
                bot_audio,
                sample_rate=sample_rate,
                organization_id=organization_id,
                evaluator_id=evaluator_id,
                meaningful_id=f"bot-{result_id}" if result_id else f"bot-{ts_suffix}",
            )
            metadata["user_recording_s3_key"] = user_key
            metadata["bot_recording_s3_key"] = bot_key
            logger.info(
                "Uploaded raw conversation tracks: user={} bot={} ({} Hz)",
                user_key,
                bot_key,
                sample_rate,
            )

            if prefer_stereo:
                stereo_merge = (
                    merge_telephony_tracks_to_stereo
                    if align_mode == "telephony"
                    else merge_wall_clock_tracks_to_stereo
                )
                analysis, stereo_duration = stereo_merge(
                    user_path,
                    bot_path,
                    output_path=stereo_path,
                )
                duration = max(duration, stereo_duration)
                with open(stereo_path, "rb") as f:
                    stereo_bytes = f.read()
                file_id = uuid.uuid4()
                meaningful_id = result_id if result_id else f"{int(time.time())}-{file_id.hex[:8]}"
                stereo_key = s3_service.upload_file(
                    file_content=stereo_bytes,
                    file_id=file_id,
                    file_format="wav",
                    organization_id=organization_id,
                    evaluator_id=evaluator_id,
                    meaningful_id=meaningful_id,
                )
                metadata["stereo_recording_s3_key"] = stereo_key
                logger.info(
                    "Uploaded aligned stereo conversation recording: {} "
                    "(strategy={} corr_peak={:.3f}, {} Hz)",
                    stereo_key,
                    analysis.strategy.value,
                    analysis.correlation_peak,
                    sample_rate,
                )

            mono_merge = (
                merge_telephony_tracks_to_mono
                if align_mode == "telephony"
                else merge_wall_clock_tracks_to_mono
            )
            analysis, mono_duration = mono_merge(
                user_path,
                bot_path,
                output_path=mono_path,
            )
            duration = max(duration, mono_duration)
            metadata["merge_strategy"] = analysis.strategy.value
            metadata["merge_reason"] = analysis.reason
            metadata["merge_correlation_peak"] = analysis.correlation_peak

            with open(mono_path, "rb") as f:
                mono_bytes = f.read()
            file_id = uuid.uuid4()
            meaningful_id = (
                f"mono-{result_id}" if result_id else f"{int(time.time())}-{file_id.hex[:8]}"
            )
            mono_key = s3_service.upload_file(
                file_content=mono_bytes,
                file_id=file_id,
                file_format="wav",
                organization_id=organization_id,
                evaluator_id=evaluator_id,
                meaningful_id=meaningful_id,
            )
            metadata["mono_recording_s3_key"] = mono_key
        finally:
            for path in (user_path, bot_path, stereo_path, mono_path):
                if os.path.exists(path):
                    os.unlink(path)
    elif prefer_stereo and len(user_audio) > 100:
        file_id = uuid.uuid4()
        ts_suffix = f"{int(time.time())}-{file_id.hex[:8]}"
        user_key = _upload_mono_track_wav(
            user_audio,
            sample_rate=sample_rate,
            organization_id=organization_id,
            evaluator_id=evaluator_id,
            meaningful_id=f"user-{result_id}" if result_id else f"user-{ts_suffix}",
        )
        metadata["user_recording_s3_key"] = user_key
        stereo_key = user_key
        metadata["stereo_recording_s3_key"] = stereo_key
    elif prefer_stereo and len(bot_audio) > 100:
        file_id = uuid.uuid4()
        ts_suffix = f"{int(time.time())}-{file_id.hex[:8]}"
        bot_key = _upload_mono_track_wav(
            bot_audio,
            sample_rate=sample_rate,
            organization_id=organization_id,
            evaluator_id=evaluator_id,
            meaningful_id=f"bot-{result_id}" if result_id else f"bot-{ts_suffix}",
        )
        metadata["bot_recording_s3_key"] = bot_key
        stereo_key = bot_key
        metadata["stereo_recording_s3_key"] = stereo_key
    elif len(user_audio) > 100:
        file_id = uuid.uuid4()
        ts_suffix = f"{int(time.time())}-{file_id.hex[:8]}"
        user_key = _upload_mono_track_wav(
            user_audio,
            sample_rate=sample_rate,
            organization_id=organization_id,
            evaluator_id=evaluator_id,
            meaningful_id=f"user-{result_id}" if result_id else f"user-{ts_suffix}",
        )
        metadata["user_recording_s3_key"] = user_key
        mono_key = user_key
    elif len(bot_audio) > 100:
        file_id = uuid.uuid4()
        ts_suffix = f"{int(time.time())}-{file_id.hex[:8]}"
        bot_key = _upload_mono_track_wav(
            bot_audio,
            sample_rate=sample_rate,
            organization_id=organization_id,
            evaluator_id=evaluator_id,
            meaningful_id=f"bot-{result_id}" if result_id else f"bot-{ts_suffix}",
        )
        metadata["bot_recording_s3_key"] = bot_key
        mono_key = bot_key

    primary_key = stereo_key if prefer_stereo and stereo_key else mono_key
    if stereo_key:
        metadata["recording_format"] = "stereo"
    elif mono_key:
        metadata["recording_format"] = "mono"

    return primary_key, duration, metadata


def build_mono_wav_bytes(pcm: bytes, *, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    buffer.seek(0)
    return buffer.read()
