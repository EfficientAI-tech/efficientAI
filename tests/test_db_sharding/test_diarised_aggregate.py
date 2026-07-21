"""Tests for sharded diarisation status aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.db_sharding.scatter_gather import aggregate_diarised_transcript_counts


def test_aggregate_diarised_mono_db():
    catalog_db = MagicMock()
    call_import_id = uuid4()
    catalog_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
        ("pending", 2),
        ("completed", 5),
    ]

    with patch("app.db_sharding.scatter_gather.is_sharding_enabled", return_value=False):
        counts = aggregate_diarised_transcript_counts(catalog_db, call_import_id)

    assert counts == {"pending": 2, "completed": 5}
