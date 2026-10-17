from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event, text

from app.db_sharding.pool_manager import (
    DatabasePoolManager,
    _reset_replication_role_on_checkin,
    postgresql_engine_url,
    process_worker_concurrency,
    shard_pool_limits,
)


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


def _settings(**overrides):
    values = {
        "DATABASE_URL": "postgresql+psycopg2://efficientai:password@localhost:5432/efficientai",
        "DB_SHARDING_ENABLED": True,
        "DB_CATALOG_URL": "postgresql+psycopg2://efficientai:password@localhost:5432/efficientai",
        "DB_POOL_SIZE": 10,
        "DB_MAX_OVERFLOW": 15,
        "DB_SHARD_ROW_CHUNK_SIZE": 500,
        "DB_SHARD_POOL_SIZE": None,
        "DB_SHARD_MAX_OVERFLOW": None,
        "DB_SHARD_ENTRIES": [
            {
                "id": "data-shard-01",
                "url": "postgresql+psycopg2://efficientai:password@localhost:5432/efficientai_data_01",
            },
            {
                "id": "data-shard-02",
                "url": "postgresql+psycopg2://efficientai:password@localhost:5432/efficientai_data_02",
            },
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_shard_pool_shares_catalog_pool_when_concurrency_unknown():
    limits = shard_pool_limits(_settings(), 2)
    assert limits == (5, 7)


def test_shard_pool_fallback_covers_worker_concurrency():
    assert shard_pool_limits(_settings(), 3, concurrency=12) == (8, 8)
    assert shard_pool_limits(_settings(), 3, concurrency=16) == (8, 12)
    assert shard_pool_limits(_settings(), 3, concurrency=28) == (8, 24)


def test_explicit_shard_pool_ignores_concurrency():
    limits = shard_pool_limits(
        _settings(DB_SHARD_POOL_SIZE=20, DB_SHARD_MAX_OVERFLOW=4),
        3,
        concurrency=28,
    )
    assert limits == (20, 4)


def test_process_worker_concurrency_reads_celery_flags():
    assert process_worker_concurrency(["celery", "worker", "--concurrency=16"]) == 16
    assert process_worker_concurrency(["celery", "worker", "-c", "28"]) == 28
    assert process_worker_concurrency(["celery", "worker", "--concurrency", "12"]) == 12
    assert process_worker_concurrency(["eai", "beat", "-c", "config.yml"]) is None


def test_explicit_shard_pool_sizes_bypass_floor(manager, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings",
        _settings(DB_SHARD_POOL_SIZE=20, DB_SHARD_MAX_OVERFLOW=4),
    )
    assert manager.sharding_enabled
    for engine in manager._shard_engines.values():
        assert engine.pool.size() == 20
        assert engine.pool._max_overflow == 4
        assert event.contains(engine, "checkin", _reset_replication_role_on_checkin)
    assert manager.catalog_engine.pool.size() == 10


def test_checkin_resets_replication_role():
    conn = MagicMock()
    _reset_replication_role_on_checkin(conn, None)
    conn.cursor.return_value.execute.assert_called_once_with(
        "SET session_replication_role TO DEFAULT"
    )


def test_checkin_noop_when_connection_is_none():
    _reset_replication_role_on_checkin(None, None)


def test_checkin_rolls_back_before_reset():
    conn = MagicMock()
    _reset_replication_role_on_checkin(conn, None)
    conn.rollback.assert_called_once()
    conn.cursor.return_value.execute.assert_called_once_with(
        "SET session_replication_role TO DEFAULT"
    )
    conn.commit.assert_called_once()


def test_postgresql_engine_url_uses_psycopg2_and_keeps_password():
    parsed = postgresql_engine_url(
        "postgresql://efficientai:password@localhost:5432/efficientai"
    )
    assert parsed.drivername == "postgresql+psycopg2"
    assert parsed.password == "password"
