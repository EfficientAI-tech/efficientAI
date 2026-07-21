"""Sharding-aware bulk call-import operation tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.schemas import CallImportTranscribeRequest
from app.services.call_imports.bulk_ops import (
    execute_bulk_diarization,
    select_rows_for_transcription,
)


def test_select_rows_for_transcription_uses_scatter_gather_loader():
    call_import = SimpleNamespace(id=uuid4())
    row_id = uuid4()
    fake_rows = [
        SimpleNamespace(
            id=row_id,
            row_index=0,
            recording_s3_key="s3-key",
            diarised_transcript=None,
        )
    ]
    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
    )
    fake_db = MagicMock()

    with patch(
        "app.db_sharding.scatter_gather.load_call_import_rows_for_transcription",
        return_value=fake_rows,
    ) as mock_loader:
        selected, skip_counts = select_rows_for_transcription(
            fake_db,
            call_import,
            payload,
            requested_row_ids=[row_id],
        )

    mock_loader.assert_called_once_with(
        fake_db,
        call_import.id,
        requested_row_ids=[row_id],
    )
    assert len(selected) == 1
    assert skip_counts == {}


def test_execute_bulk_diarization_updates_rows_on_shards():
    call_import = SimpleNamespace(id=uuid4())
    row_id = uuid4()
    fake_row = SimpleNamespace(
        id=row_id,
        row_index=0,
        recording_s3_key="s3-key",
        diarised_transcript=None,
    )
    payload = CallImportTranscribeRequest(
        stt_provider="deepgram",
        stt_model="nova-2",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
    )
    fake_db = MagicMock()

    with (
        patch(
            "app.services.call_imports.bulk_ops.select_rows_for_transcription",
            return_value=([fake_row], {}),
        ),
        patch(
            "app.workers.concurrency.diarization_dispatch.build_diarization_params_from_request",
            return_value={"mode": "stt_llm"},
        ),
        patch(
            "app.workers.concurrency.diarization_dispatch.store_row_diarization_params_batch",
            return_value=([row_id], []),
        ),
        patch(
            "app.db_sharding.row_ops.update_call_import_rows_on_shards",
        ) as mock_update,
        patch(
            "app.workers.concurrency.fair_diarization_dispatch.schedule_fair_diarization_dispatch",
        ),
    ):
        result = execute_bulk_diarization(fake_db, call_import, payload)

    assert result.queued == 1
    mock_update.assert_called_once()
    updates = mock_update.call_args.args[2]
    assert updates[0]["id"] == row_id
    assert updates[0]["diarised_transcript_status"] == "pending"
    fake_db.commit.assert_not_called()


def test_count_completed_source_rows_uses_scatter_gather_when_sharding_enabled():
    from app.services.call_imports.bulk_ops import count_completed_source_rows

    call_import_id = uuid4()
    fake_db = MagicMock()

    with (
        patch(
            "app.db_sharding.scatter_gather.is_sharding_enabled",
            return_value=True,
        ),
        patch(
            "app.db_sharding.scatter_gather.count_completed_call_import_rows",
            return_value=42,
        ) as mock_count,
    ):
        total = count_completed_source_rows(fake_db, call_import_id)

    assert total == 42
    mock_count.assert_called_once_with(fake_db, call_import_id)
