"""Sharded import row filter scatter-gather tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.scatter_gather import (
    SliceCount,
    fetch_call_import_rows_filtered_page,
    fetch_call_import_rows_page,
    merge_rows_by_index,
    plan_slice_page,
)


def test_merge_rows_by_index_sorts():
    rows = [
        SimpleNamespace(row_index=2),
        SimpleNamespace(row_index=0),
        SimpleNamespace(row_index=1),
    ]
    ordered = merge_rows_by_index(rows)
    assert [int(r.row_index) for r in ordered] == [0, 1, 2]


def test_plan_slice_page_skips_a_hole_inside_the_first_slice():
    windows = plan_slice_page(
        [
            SliceCount(0, "s1", 2),
            SliceCount(1, "s2", 100),
        ],
        offset=1,
        limit=2,
    )
    assert [(w.shard_id, w.slice_id, w.local_offset, w.limit) for w in windows] == [
        ("s1", 0, 1, 1),
        ("s2", 1, 0, 1),
    ]


def test_plan_slice_page_past_first_slice_ignores_other_slices():
    windows = plan_slice_page(
        [
            SliceCount(0, "s1", 500),
            SliceCount(1, "s2", 500),
            SliceCount(2, "s3", 45),
        ],
        offset=500,
        limit=100,
    )
    assert [(w.shard_id, w.slice_id, w.local_offset, w.limit) for w in windows] == [
        ("s2", 1, 0, 100),
    ]


def test_page_past_first_slice_does_not_read_other_shard_bodies():
    catalog_db = MagicMock()
    call_import_id = uuid4()
    loaded = SimpleNamespace(row_index=500, id=uuid4())

    with patch(
        "app.db_sharding.scatter_gather.is_sharding_enabled",
        return_value=True,
    ):
        with patch(
            "app.db_sharding.scatter_gather._collect_import_slice_counts",
            return_value=[
                SliceCount(0, "s1", 500),
                SliceCount(1, "s2", 40),
            ],
        ):
            with patch(
                "app.db_sharding.scatter_gather._load_call_import_slice_window",
                return_value=[loaded],
            ) as load_window:
                page = fetch_call_import_rows_page(
                    catalog_db,
                    call_import_id,
                    offset=500,
                    limit=10,
                )

    assert page == [loaded]
    assert load_window.call_count == 1
    assert load_window.call_args.args[0] == "s2"


def test_list_response_does_not_read_transcript_columns():
    from datetime import datetime, timezone

    from app.api.v1.routes.call_imports import _call_import_row_list_response
    from app.models.enums import CallImportRowStatus

    class _Row:
        id = uuid4()
        row_index = 0
        conversation_id = "c-1"
        recording_url = None
        recording_date = None
        transcript_source = "csv"
        transcript_provider = None
        transcript_model = None
        transcript_status = "idle"
        transcript_error = None
        transcribed_at = None
        diarised_transcript_provider = None
        diarised_transcript_model = None
        diarised_transcript_status = "idle"
        diarised_transcript_error = None
        diarised_at = None
        diarised_llm_provider = None
        diarised_llm_model = None
        diarised_speaker_swap = False
        status = CallImportRowStatus.PENDING
        recording_s3_key = None
        recording_content_type = None
        recording_size_bytes = None
        error_message = None
        attempts = 0
        created_at = datetime.now(timezone.utc)
        updated_at = created_at

        @property
        def transcript(self):
            raise AssertionError("list read transcript")

        @property
        def diarised_transcript(self):
            raise AssertionError("list read diarised transcript")

        @property
        def diarised_segments(self):
            raise AssertionError("list read segments")

        @property
        def diarised_prompt(self):
            raise AssertionError("list read prompt")

        @property
        def raw_columns(self):
            raise AssertionError("list read raw columns")

    payload = _call_import_row_list_response(_Row())
    assert payload.transcript is None
    assert payload.diarised_transcript is None
    assert payload.diarised_segments is None
    assert payload.diarised_prompt is None
    assert payload.raw_columns is None
