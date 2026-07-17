"""Context managers for catalog and row-shard sessions."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.db_sharding.pool_manager import db_pool_manager, open_row_shard_session
from app.db_sharding.pool_manager import open_catalog_session


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
    return db_pool_manager.sharding_enabled
