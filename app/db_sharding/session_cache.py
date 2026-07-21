"""Reuse SQLAlchemy shard sessions within a worker task (fair dispatch, scatter reads)."""

from __future__ import annotations

from sqlalchemy.orm import Session


class ShardSessionCache:
    """One open session per shard id for the lifetime of a dispatch/scatter pass."""

    def __init__(self) -> None:
        self._by_shard: dict[str, Session] = {}

    def session_for(self, shard_id: str) -> Session:
        from app.db_sharding.pool_manager import db_pool_manager

        existing = self._by_shard.get(shard_id)
        if existing is not None:
            return existing
        factory = db_pool_manager.shard_session_factory(shard_id)
        session = factory()
        self._by_shard[shard_id] = session
        return session

    def close_all(self) -> None:
        for session in self._by_shard.values():
            session.close()
        self._by_shard.clear()
