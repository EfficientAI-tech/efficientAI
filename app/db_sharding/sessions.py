"""Context managers for catalog and row-shard sessions."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.db_sharding.pool_manager import db_pool_manager, open_row_shard_session
from app.db_sharding.pool_manager import open_catalog_session


class ShardingEntitlementError(RuntimeError):
    """Sharding pools are configured but deployment entitlement is missing."""


@contextmanager
def catalog_session() -> Iterator[Session]:
    db = open_catalog_session()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def row_shard_session(
    call_import_id: UUID | str,
    row_index: int,
) -> Iterator[Tuple[Session, str]]:
    db, shard_id = open_row_shard_session(call_import_id, row_index)
    try:
        yield db, shard_id
    finally:
        db.close()


def is_sharding_enabled() -> bool:
    if not db_pool_manager.sharding_enabled:
        return False

    from app.core.license import is_feature_enabled
    from app.core.usage_entitlement import deployment_has_entitlement

    if not deployment_has_entitlement():
        message = (
            "DB_SHARDING_ENABLED is true but no deployment-wide enterprise "
            "license is present. Refusing catalog fallback to avoid split storage."
        )
        logger.error(message)
        raise ShardingEntitlementError(message)

    if not is_feature_enabled("db_sharding"):
        message = (
            "DB_SHARDING_ENABLED is true but db_sharding is not enabled "
            "by the enterprise license. Refusing catalog fallback to avoid split storage."
        )
        logger.error(message)
        raise ShardingEntitlementError(message)

    return True
