import os
import tempfile
import subprocess
import time
import uuid
from loguru import logger
from app.services.s3_service import s3_service


def merge_and_upload_audio(
    user_audio_path: str,
    bot_audio_path: str,
    call_start_time: float,
    organization_id: str = None,
    evaluator_id: str = None,
    result_id: str = None,
):
    """
    Merge user and bot audio recordings, upload the combined wav to S3,
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

                logger.info(f"Merging audio files to {merged_path}...")
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    user_audio_path,
                    "-i",
                    bot_audio_path,
                    "-filter_complex",
                    "amix=inputs=2:duration=longest:dropout_transition=2:normalize=0",
                    "-ar",
                    "24000",
                    merged_path,
                ]

                process = subprocess.run(cmd, capture_output=True, text=True)

                if process.returncode == 0 and os.path.exists(merged_path):
                    logger.info("Audio merged successfully. Uploading to S3...")
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
                    duration_result = time.time() - call_start_time
                    os.unlink(merged_path)
                else:
                    logger.warning("Audio merge completed but output file not found or FFmpeg failed")
                    if process.stderr:
                        logger.error(f"FFmpeg merge failed: {process.stderr}")
            else:
                logger.warning("Recorded audio files are too small, skipping merge/upload.")
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

