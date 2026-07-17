"""Sharded eval-row placement helpers."""

import uuid
from unittest.mock import MagicMock, patch

from app.db_sharding.row_ops import partition_eval_mappings_by_shard


def test_partition_eval_mappings_by_shard_routes_by_source_row_index():
    call_import_id = uuid.uuid4()
    source_a = uuid.uuid4()
    source_b = uuid.uuid4()
    index_by_id = {source_a: 0, source_b: 1200}
    mappings = [
        {
            "evaluation_id": uuid.uuid4(),
            "call_import_row_id": source_a,
            "status": "pending",
        },
        {
            "evaluation_id": uuid.uuid4(),
            "call_import_row_id": source_b,
            "status": "pending",
        },
    ]
    catalog_db = MagicMock()
    router = MagicMock()
    router.shard_id_for_row.side_effect = lambda cid, idx, **_: (
        "s1" if idx < 500 else "s2"
    )
    with patch("app.db_sharding.row_ops.is_sharding_enabled", return_value=True):
        with patch(
            "app.db_sharding.row_ops.router_for_import",
            return_value=(router, None),
        ):
            buckets = partition_eval_mappings_by_shard(
                catalog_db,
                call_import_id,
                mappings,
                index_by_source_id=index_by_id,
            )
    assert len(buckets["s1"]) == 1
    assert len(buckets["s2"]) == 1
    assert buckets["s1"][0]["call_import_row_id"] == source_a
