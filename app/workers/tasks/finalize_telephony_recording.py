"""Post-call merge/upload/persist for live Vobiz telephony recordings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from app.database import SessionLocal
from app.services.telephony.call_recording_lifecycle import persist_telephony_call_artifacts
from app.services.voice_agent.utils.audio_merge import merge_and_upload_audio
from app.workers.config import celery_app


@celery_app.task(name="finalize_telephony_recording", bind=True, max_retries=2)
def finalize_telephony_recording_task(
    self,
    *,
    call_short_id: str,
    user_audio_path: str,
    bot_audio_path: str,
    call_start_time: float,
    organization_id: Optional[str] = None,
    evaluator_id: Optional[str] = None,
    result_id: Optional[str] = None,
    conversation_turns: Optional[List[Dict[str, Any]]] = None,
    transcript_text: Optional[str] = None,
    duration: Optional[float] = None,
) -> dict:
    """Merge dual-track WAVs, upload to S3, persist CallRecording, queue evaluator."""
    try:
        s3_key, merged_duration, merge_metadata = merge_and_upload_audio(
            user_audio_path=user_audio_path,
            bot_audio_path=bot_audio_path,
            call_start_time=call_start_time,
            organization_id=organization_id,
            evaluator_id=evaluator_id,
            result_id=result_id,
        )
        effective_duration = merged_duration if merged_duration is not None else duration

        db = SessionLocal()
        try:
            persist_telephony_call_artifacts(
                db,
                call_short_id=call_short_id,
                conversation_turns=conversation_turns,
                transcript_text=transcript_text,
                s3_key=s3_key,
                duration=effective_duration,
                recording_metadata=merge_metadata,
            )
        finally:
            db.close()

        return {
            "status": "ok",
            "call_short_id": call_short_id,
            "s3_key": s3_key,
            "duration": effective_duration,
        }
    except Exception as exc:
        logger.error(
            "finalize_telephony_recording failed for call_short_id={}: {}",
            call_short_id,
            exc,
            exc_info=True,
        )
        raise self.retry(exc=exc, countdown=10) from exc
