"""Tests for call-import bulk operation helpers."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.schemas import CallImportTranscribeRequest
from app.services.call_imports.bulk_ops import select_rows_for_transcription


class _FakeCallImport:
    def __init__(self, import_id):
        self.id = import_id


class _FakeRow:
    def __init__(self, *, row_id, recording_s3_key, diarised_transcript=""):
        self.id = row_id
        self.row_index = 0
        self.recording_s3_key = recording_s3_key
        self.diarised_transcript = diarised_transcript
        self.diarised_transcript_status = None
        self.diarised_transcript_error = None
        self.celery_task_id = None


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def options(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


def test_select_rows_for_transcription_skips_without_recording():
    import_id = uuid4()
    row_with = _FakeRow(row_id=uuid4(), recording_s3_key="org/x/rec.mp3")
    row_without = _FakeRow(row_id=uuid4(), recording_s3_key="")
    db = _FakeSession([row_with, row_without])
    payload = CallImportTranscribeRequest(
        mode="llm_only",
        diarization_llm_provider="openai",
        diarization_llm_model="gpt-4o-mini",
    )

    with patch(
        "app.db_sharding.scatter_gather.load_call_import_rows_for_transcription",
        return_value=[row_with, row_without],
    ):
        selected, skip_counts = select_rows_for_transcription(
            db,  # type: ignore[arg-type]
            _FakeCallImport(import_id),  # type: ignore[arg-type]
            payload,
        )

    assert len(selected) == 1
    assert selected[0].id == row_with.id
    assert skip_counts.get("no_recording") == 1


def test_store_row_diarization_params_batch_uses_pipeline(monkeypatch):
    from app.workers.concurrency import diarization_dispatch

    calls = {"setex": 0, "pipeline": 0}

    class _FakePipeline:
        def __init__(self, client):
            self._client = client

        def setex(self, key, ttl, value):
            calls["setex"] += 1
            return self

        def execute(self):
            return [True, True]

    class _FakeRedis:
        def pipeline(self, transaction=False):
            calls["pipeline"] += 1
            return _FakePipeline(self)

    monkeypatch.setattr(diarization_dispatch, "_get_redis", lambda: _FakeRedis())

    stored, failed = diarization_dispatch.store_row_diarization_params_batch(
        [uuid4(), uuid4()],
        {"mode": "stt_llm", "overwrite_existing": False},
    )

    assert calls["pipeline"] == 1
    assert calls["setex"] == 2
    assert len(stored) == 2
    assert failed == []
