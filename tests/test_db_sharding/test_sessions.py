"""Tests for sharding session gating."""

from __future__ import annotations

import pytest

from app.db_sharding.pool_manager import DatabasePoolManager
from app.db_sharding.sessions import ShardingEntitlementError, is_sharding_enabled


@pytest.fixture
def manager():
    m = DatabasePoolManager()
    yield m
    m.reset()


def test_is_sharding_enabled_false_when_pools_not_configured(manager, monkeypatch):
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
    monkeypatch.setattr("app.db_sharding.sessions.db_pool_manager", manager)

    assert is_sharding_enabled() is False


def test_is_sharding_enabled_raises_without_deployment_entitlement(manager, monkeypatch):
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
                "DB_SHARD_ENTRIES": [{"id": "data-shard-01", "url": url}],
            },
        )(),
    )
    monkeypatch.setattr("app.db_sharding.sessions.db_pool_manager", manager)
    monkeypatch.setattr(
        "app.core.usage_entitlement.deployment_has_entitlement",
        lambda: False,
    )

    with pytest.raises(ShardingEntitlementError, match="Refusing catalog fallback"):
        is_sharding_enabled()


def test_is_sharding_enabled_true_with_entitlement_and_feature(manager, monkeypatch):
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
                "DB_SHARD_ENTRIES": [{"id": "data-shard-01", "url": url}],
            },
        )(),
    )
    monkeypatch.setattr("app.db_sharding.sessions.db_pool_manager", manager)
    monkeypatch.setattr(
        "app.core.usage_entitlement.deployment_has_entitlement",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.core.license.is_feature_enabled",
        lambda _feature: True,
    )

    assert is_sharding_enabled() is True
