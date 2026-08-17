import os
import tempfile
import time
import uuid

from loguru import logger

from app.services.storage.s3_service import s3_service
from app.services.voice_agent.utils.telephony_audio_align import (
    merge_telephony_tracks_to_mono,
    merge_telephony_tracks_to_stereo,
)


def merge_and_upload_audio(
    user_audio_path: str,
    bot_audio_path: str,
    call_start_time: float,
    organization_id: str = None,
    evaluator_id: str = None,
    result_id: str = None,
):
    """
    Merge user and bot telephony recordings with alignment analysis, upload stereo-first
    WAV to S3, and clean up temporary files. Returns (s3_key, duration_seconds, metadata).
    """
    s3_key_result = None
    duration_result = None
    metadata: dict = {"recording_source": "pipeline"}

    try:
        if os.path.exists(user_audio_path) and os.path.exists(bot_audio_path):
            user_size = os.path.getsize(user_audio_path)
            bot_size = os.path.getsize(bot_audio_path)

            if user_size > 100 and bot_size > 100:
                stereo_fd, stereo_path = tempfile.mkstemp(suffix=".wav")
                mono_fd, mono_path = tempfile.mkstemp(suffix=".wav")
                os.close(stereo_fd)
                os.close(mono_fd)

                logger.info(
                    "Merging telephony tracks user={} bot={} -> stereo + mono",
                    user_audio_path,
                    bot_audio_path,
                )
                try:
                    analysis, stereo_duration = merge_telephony_tracks_to_stereo(
                        user_audio_path,
                        bot_audio_path,
                        output_path=stereo_path,
                    )
                    _mono_analysis, mono_duration = merge_telephony_tracks_to_mono(
                        user_audio_path,
                        bot_audio_path,
                        output_path=mono_path,
                    )
                    metadata.update(
                        {
                            "recording_format": "stereo",
                            "merge_strategy": analysis.strategy.value,
                            "merge_reason": analysis.reason,
                            "merge_correlation_peak": analysis.correlation_peak,
                        }
                    )
                except Exception as merge_exc:
                    logger.error("Telephony aligned merge failed: {}", merge_exc, exc_info=True)
                    stereo_path = None
                    mono_path = None
                    stereo_duration = None
                    mono_duration = None

                if stereo_path and os.path.exists(stereo_path):
                    with open(stereo_path, "rb") as f:
                        stereo_content = f.read()
                    file_id = uuid.uuid4()
                    meaningful_id = result_id if result_id else f"{int(time.time())}-{file_id.hex[:8]}"
                    s3_key_result = s3_service.upload_file(
                        file_content=stereo_content,
                        file_id=file_id,
                        file_format="wav",
                        organization_id=organization_id,
                        evaluator_id=evaluator_id,
                        meaningful_id=meaningful_id,
                    )
                    metadata["stereo_recording_s3_key"] = s3_key_result
                    duration_result = stereo_duration if stereo_duration else time.time() - call_start_time
                    logger.info("Telephony stereo audio uploaded to S3: {}", s3_key_result)
                    os.unlink(stereo_path)

                if mono_path and os.path.exists(mono_path):
                    with open(mono_path, "rb") as f:
                        mono_content = f.read()
                    file_id = uuid.uuid4()
                    meaningful_id = (
                        f"mono-{result_id}" if result_id else f"{int(time.time())}-{file_id.hex[:8]}"
                    )
                    mono_key = s3_service.upload_file(
                        file_content=mono_content,
                        file_id=file_id,
                        file_format="wav",
                        organization_id=organization_id,
                        evaluator_id=evaluator_id,
                        meaningful_id=meaningful_id,
                    )
                    metadata["mono_recording_s3_key"] = mono_key
                    if not s3_key_result:
                        s3_key_result = mono_key
                        metadata["recording_format"] = "mono"
                        duration_result = mono_duration if mono_duration else time.time() - call_start_time
                    os.unlink(mono_path)
                elif not s3_key_result:
                    logger.warning("Telephony merge produced no output file")
            elif user_size > 100 and bot_size <= 100:
                logger.info("Bot track empty; uploading inbound user track only")
                s3_key_result, duration_result = _upload_single_track(
                    user_audio_path,
                    call_start_time,
                    organization_id,
                    evaluator_id,
                    result_id,
                )
                metadata["recording_format"] = "mono"
            else:
                logger.warning("Recorded audio files are too small, skipping merge/upload.")
        elif os.path.exists(user_audio_path) and os.path.getsize(user_audio_path) > 100:
            s3_key_result, duration_result = _upload_single_track(
                user_audio_path,
                call_start_time,
                organization_id,
                evaluator_id,
                result_id,
            )
            metadata["recording_format"] = "mono"
        else:
            logger.warning("Audio files not found, skipping merge/upload.")
    except Exception as e:
        logger.error(f"Error processing recorded audio: {e}")
    finally:
        if os.path.exists(user_audio_path):
            os.unlink(user_audio_path)
        if os.path.exists(bot_audio_path):
            os.unlink(bot_audio_path)

    return s3_key_result, duration_result, metadata


def _upload_single_track(
    path: str,
    call_start_time: float,
    organization_id: str,
    evaluator_id: str,
    result_id: str,
):
    with open(path, "rb") as f:
        file_content = f.read()
    file_id = uuid.uuid4()
    meaningful_id = result_id if result_id else f"{int(time.time())}-{file_id.hex[:8]}"
    s3_key = s3_service.upload_file(
        file_content=file_content,
        file_id=file_id,
        file_format="wav",
        organization_id=organization_id,
        evaluator_id=evaluator_id,
        meaningful_id=meaningful_id,
    )
    return s3_key, time.time() - call_start_time
