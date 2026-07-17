"""Import row finalize checks when CallImport lives on catalog only."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.workers.tasks.process_call_import_row import _row_or_import_gone


def test_row_or_import_gone_sharded_uses_catalog_for_import_status():
    row_id = uuid4()
    call_import_id = uuid4()
    shard_db = MagicMock()
    catalog_db = MagicMock()

    shard_db.query.return_value.filter.return_value.first.return_value = (row_id,)
    shard_db.query.return_value.filter.return_value.scalar.return_value = (
        call_import_id
    )
    catalog_db.query.return_value.filter.return_value.scalar.return_value = "processing"

    with patch(
        "app.db_sharding.sessions.is_sharding_enabled",
        return_value=True,
    ):
        reason = _row_or_import_gone(
            shard_db,
            row_id,
            catalog_db=catalog_db,
        )

    assert reason is None
