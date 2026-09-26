"""Tests for post-call telephony recording finalize Celery task."""

from unittest.mock import MagicMock, patch

from app.workers.tasks.finalize_telephony_recording import finalize_telephony_recording_task


@patch("app.workers.tasks.finalize_telephony_recording.persist_telephony_call_artifacts")
@patch("app.workers.tasks.finalize_telephony_recording.merge_and_upload_audio")
@patch("app.workers.tasks.finalize_telephony_recording.SessionLocal")
def test_finalize_telephony_recording_task_wires_merge_persist(
    mock_session_local,
    mock_merge,
    mock_persist,
):
    db = MagicMock()
    mock_session_local.return_value = db
    mock_merge.return_value = ("org/eval/audio.wav", 42.5)

    result = finalize_telephony_recording_task.run(
        call_short_id="123456",
        user_audio_path="/tmp/user.wav",
        bot_audio_path="/tmp/bot.wav",
        call_start_time=1000.0,
        organization_id="org-1",
        evaluator_id="eval-1",
        result_id="res-1",
        conversation_turns=[{"speaker": "user", "text": "hi", "start": 0, "end": 1}],
        transcript_text="user: hi",
        duration=40.0,
    )

    mock_merge.assert_called_once_with(
        user_audio_path="/tmp/user.wav",
        bot_audio_path="/tmp/bot.wav",
        call_start_time=1000.0,
        organization_id="org-1",
        evaluator_id="eval-1",
        result_id="res-1",
    )
    mock_persist.assert_called_once_with(
        db,
        call_short_id="123456",
        conversation_turns=[{"speaker": "user", "text": "hi", "start": 0, "end": 1}],
        transcript_text="user: hi",
        s3_key="org/eval/audio.wav",
        duration=42.5,
        trace_turns=None,
    )
    assert result["status"] == "ok"
    assert result["s3_key"] == "org/eval/audio.wav"


def test_get_audio_recorder_class_is_cached():
    import app.services.voice_agent.audio_recorder as module

    module._audio_recorder_class = None
    first = module.get_audio_recorder_class()
    second = module.get_audio_recorder_class()
    assert first is second
