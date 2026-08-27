import os
import tempfile
import time
import uuid

from loguru import logger

from app.services.storage.s3_service import s3_service
from app.services.voice_agent.utils.telephony_audio_align import merge_telephony_tracks_to_mono


def merge_and_upload_audio(
    user_audio_path: str,
    bot_audio_path: str,
    call_start_time: float,
    organization_id: str = None,
    evaluator_id: str = None,
    result_id: str = None,
    call_direction: str | None = None,
):
    """
    Merge user and bot telephony recordings with alignment analysis, upload mono WAV to S3,
    and clean up temporary files. Returns (s3_key, duration_seconds).
    """
    s3_key_result = None
    duration_result = None

    try:
        if os.path.exists(user_audio_path) and os.path.exists(bot_audio_path):
            user_size = os.path.getsize(user_audio_path)
            bot_size = os.path.getsize(bot_audio_path)

            if user_size > 100 and bot_size > 100:
                merged_fd, merged_path = tempfile.mkstemp(suffix=".wav")
                os.close(merged_fd)

                logger.info(
                    "Merging telephony tracks user={} bot={} -> {}",
                    user_audio_path,
                    bot_audio_path,
                    merged_path,
                )
                try:
                    _analysis, merged_duration = merge_telephony_tracks_to_mono(
                        user_audio_path,
                        bot_audio_path,
                        output_path=merged_path,
                        call_direction=call_direction,
                    )
                except Exception as merge_exc:
                    logger.error("Telephony aligned merge failed: {}", merge_exc, exc_info=True)
                    merged_path = None
                    merged_duration = None

                if merged_path and os.path.exists(merged_path):
                    logger.info("Telephony audio merged successfully. Uploading to S3...")
                    with open(merged_path, "rb") as f:
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

                    logger.info(f"✅ Conversation audio uploaded to S3: {s3_key}")
                    s3_key_result = s3_key
                    duration_result = merged_duration if merged_duration else time.time() - call_start_time
                    os.unlink(merged_path)
                else:
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
            elif bot_size > 100 and user_size <= 100:
                logger.info("User track empty; uploading bot/outbound track only")
                s3_key_result, duration_result = _upload_single_track(
                    bot_audio_path,
                    call_start_time,
                    organization_id,
                    evaluator_id,
                    result_id,
                )
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
        else:
            logger.warning("Audio files not found, skipping merge/upload.")
    except Exception as e:
        logger.error(f"Error processing recorded audio: {e}")
    finally:
        if os.path.exists(user_audio_path):
            os.unlink(user_audio_path)
        if os.path.exists(bot_audio_path):
            os.unlink(bot_audio_path)

    return s3_key_result, duration_result


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
