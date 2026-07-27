"""Tests for live-entity shard routing."""

from uuid import UUID

from app.db_sharding.live_entity_router import live_entity_shard_id


def test_live_entity_shard_id_is_stable():
    workspace_id = UUID("11111111-1111-1111-1111-111111111111")
    entity_id = UUID("22222222-2222-2222-2222-222222222222")
    shard_ids = ["data-shard-01", "data-shard-02", "data-shard-03"]
    first = live_entity_shard_id(workspace_id, entity_id, shard_ids=shard_ids)
    second = live_entity_shard_id(workspace_id, entity_id, shard_ids=shard_ids)
    assert first == second
    assert first in shard_ids


def test_live_entity_shard_id_spreads_across_shards():
    workspace_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    shard_ids = ["data-shard-01", "data-shard-02", "data-shard-03"]
    hits = {
        live_entity_shard_id(workspace_id, UUID(int=i), shard_ids=shard_ids)
        for i in range(100)
    }
    assert len(hits) >= 2
