import pytest
from sqlalchemy import create_engine, text

from app.db_sharding.pool_manager import DatabasePoolManager


@pytest.fixture
def manager():
    m = DatabasePoolManager()
    yield m
    m.reset()


def test_legacy_single_engine(manager, monkeypatch):
    url = "sqlite:///:memory:"
    monkeypatch.setattr(
        "app.config.settings",
        type(
            "S",
            (),
            {
                "DATABASE_URL": url,
                "DB_SHARDING_ENABLED": False,
                "DB_POOL_SIZE": 5,
                "DB_MAX_OVERFLOW": 5,
                "DB_CATALOG_URL": None,
                "DB_SHARD_ROW_CHUNK_SIZE": 500,
                "DB_SHARD_ENTRIES": [],
            },
        )(),
    )
    eng = manager.catalog_engine
    assert eng.url.database == ":memory:"
    assert not manager.sharding_enabled
    assert manager.router is None
    assert len(manager.all_engines_for_migrations()) == 1


def test_sharding_two_shards_dedupe_migrations(manager, monkeypatch):
    url = "sqlite:///:memory:"
    monkeypatch.setattr(
        "app.config.settings",
        type(
            "S",
            (),
            {
                "DATABASE_URL": url,
                "DB_SHARDING_ENABLED": True,
                "DB_CATALOG_URL": url,
                "DB_POOL_SIZE": 2,
                "DB_MAX_OVERFLOW": 2,
                "DB_SHARD_ROW_CHUNK_SIZE": 500,
                "DB_SHARD_ENTRIES": [
                    {"id": "data-shard-01", "url": url},
                    {"id": "data-shard-02", "url": url},
                ],
            },
        )(),
    )
    assert manager.sharding_enabled
    assert manager.router is not None
    assert manager.router.shard_count == 2
    engines = manager.all_engines_for_migrations()
    assert len(engines) == 1

    session = manager.shard_session_factory(
        manager.router.shard_id_for_row(
            "00000000-0000-0000-0000-000000000001", 0
        )
    )()
    shard_id = manager.router.shard_id_for_row(
        "00000000-0000-0000-0000-000000000001", 0
    )
    try:
        session.execute(text("SELECT 1"))
        assert shard_id in ("data-shard-01", "data-shard-02")
    finally:
        session.close()
