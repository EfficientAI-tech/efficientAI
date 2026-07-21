"""Tests for progress counter flush ordering (PR #104 P1 fix)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import redis

from app.services.call_imports import progress_counters


def test_flush_eval_skips_catalog_when_redis_decrement_fails():
    db = MagicMock()
    evaluation_id = uuid4()
    evaluation = MagicMock(completed_rows=0, failed_rows=0)

    with patch.object(
        progress_counters,
        "read_eval_progress",
        return_value=(3, 1),
    ):
        with patch.object(progress_counters, "_client") as client_factory:
            client = MagicMock()
            client.hincrby.side_effect = redis.RedisError("down")
            client_factory.return_value = client
            db.query.return_value.filter.return_value.first.return_value = evaluation

            progress_counters.flush_eval_progress_to_catalog(db, evaluation_id)

    db.flush.assert_not_called()


def test_flush_eval_restores_redis_when_catalog_flush_fails():
    db = MagicMock()
    evaluation_id = uuid4()
    db.query.return_value.filter.return_value.first.return_value = None

    with patch.object(
        progress_counters,
        "read_eval_progress",
        return_value=(2, 0),
    ):
        with patch.object(progress_counters, "_client") as client_factory:
            client = MagicMock()
            client_factory.return_value = client
            with patch.object(progress_counters, "record_eval_row_terminal") as restore:
                progress_counters.flush_eval_progress_to_catalog(db, evaluation_id)

    restore.assert_called_once_with(evaluation_id, completed_delta=2, failed_delta=0)


def test_engine_role_uses_parsed_url_comparison():
    from app.core.migrations import _engine_role_for_url

    catalog = "postgresql://user:pass@localhost:5432/efficientai_catalog"
    normalized = "postgresql+psycopg2://user:pass@localhost:5432/efficientai_catalog"

    class _Settings:
        DB_SHARDING_ENABLED = True
        DB_CATALOG_URL = catalog
        DATABASE_URL = catalog

    with patch("app.config.settings", _Settings()):
        assert _engine_role_for_url(normalized) == "catalog"
        assert _engine_role_for_url(
            "postgresql://user:pass@localhost:5432/efficientai_data_01"
        ) == "shard"
