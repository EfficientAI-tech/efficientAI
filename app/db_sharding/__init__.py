"""Platform data-plane sharding: pools, routing, sessions (call-import rows today)."""

from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.router import ShardRouter
from app.db_sharding.sessions import catalog_session, is_sharding_enabled, row_shard_session
from app.db_sharding.live_entity_router import live_entity_shard_id

__all__ = [
    "ShardRouter",
    "catalog_session",
    "db_pool_manager",
    "is_sharding_enabled",
    "live_entity_shard_id",
    "row_shard_session",
]
