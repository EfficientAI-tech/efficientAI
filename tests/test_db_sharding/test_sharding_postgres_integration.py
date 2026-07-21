"""Two-shard Postgres integration for scatter-gather import row reads.

Runs in CI when SHARDING_INTEGRATION_TEST=1 and catalog + shard URLs are set.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

pytestmark = pytest.mark.integration


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        pytest.skip(f"{name} is not set")
    return value


@pytest.fixture(scope="module")
def sharding_postgres_env():
    if os.getenv("SHARDING_INTEGRATION_TEST") != "1":
        pytest.skip("SHARDING_INTEGRATION_TEST is not enabled")

    catalog_url = _require_env("CATALOG_DATABASE_URL")
    shard_01 = _require_env("SHARD_DATABASE_URL_01")
    shard_02 = _require_env("SHARD_DATABASE_URL_02")

    from app.database import Base
    from app.db_sharding.pool_manager import db_pool_manager

    # Register ORM models on Base.metadata before create_all (see init_db()).
    import app.models.database  # noqa: F401

    for url in (catalog_url, shard_01, shard_02):
        engine = create_engine(url, pool_pre_ping=True)
        Base.metadata.create_all(bind=engine)
        engine.dispose()

    db_pool_manager.reset()

    class _Settings:
        DATABASE_URL = catalog_url
        DB_CATALOG_URL = catalog_url
        DB_SHARDING_ENABLED = True
        DB_SHARD_ROW_CHUNK_SIZE = 500
        DB_POOL_SIZE = 2
        DB_MAX_OVERFLOW = 2
        DB_SHARD_ENTRIES = [
            {"id": "data-shard-01", "url": shard_01},
            {"id": "data-shard-02", "url": shard_02},
        ]

    import app.config as config_module

    prior_settings = config_module.settings
    config_module.settings = _Settings()
    db_pool_manager.reset()

    from app.db_sharding.sessions import is_sharding_enabled

    if not is_sharding_enabled():
        config_module.settings = prior_settings
        db_pool_manager.reset()
        pytest.skip("pool manager did not enable sharding")

    yield {
        "catalog_url": catalog_url,
        "shard_01": shard_01,
        "shard_02": shard_02,
    }

    config_module.settings = prior_settings
    db_pool_manager.reset()


def test_import_row_filter_scatter_gather_two_shards(sharding_postgres_env):
    from app.db_sharding.pool_manager import open_catalog_session
    from app.db_sharding.row_ops import bulk_insert_mappings_on_shards, register_shard_slices
    from app.db_sharding.scatter_gather import (
        count_call_import_rows_filtered,
        list_call_import_row_ids_filtered,
    )
    from app.models.database import CallImport, CallImportRow, Organization, Workspace
    from app.models.enums import CallImportRowStatus, CallImportStatus

    org_id = uuid4()
    workspace_id = uuid4()
    call_import_id = uuid4()
    row_a_id = uuid4()
    row_b_id = uuid4()

    catalog = open_catalog_session()
    try:
        org = Organization(id=org_id, name="Sharding CI Org")
        workspace = Workspace(
            id=workspace_id,
            organization=org,
            name="Default",
            slug="default",
            is_default=True,
        )
        catalog.add_all([org, workspace])
        catalog.flush()

        catalog.add(
            CallImport(
                id=call_import_id,
                organization_id=org_id,
                workspace_id=workspace_id,
                total_rows=2,
                status=CallImportStatus.PROCESSING,
            )
        )
        catalog.commit()

        mappings = [
            {
                "id": row_a_id,
                "call_import_id": call_import_id,
                "organization_id": org_id,
                "workspace_id": workspace_id,
                "row_index": 0,
                "conversation_id": "match-alpha",
                "status": CallImportRowStatus.COMPLETED,
                "transcript_status": "idle",
                "diarised_transcript_status": "completed",
            },
            {
                "id": row_b_id,
                "call_import_id": call_import_id,
                "organization_id": org_id,
                "workspace_id": workspace_id,
                "row_index": 1,
                "conversation_id": "other-beta",
                "status": CallImportRowStatus.COMPLETED,
                "transcript_status": "idle",
                "diarised_transcript_status": "pending",
            },
        ]
        inserted, pending_sessions = bulk_insert_mappings_on_shards(
            catalog, call_import_id, mappings, orm_class=CallImportRow
        )
        assert inserted == 2
        assert pending_sessions == []
        register_shard_slices(catalog, call_import_id, 2)
        catalog.commit()

        assert (
            count_call_import_rows_filtered(
                catalog,
                call_import_id,
                search_term="alpha",
            )
            == 1
        )
        assert (
            count_call_import_rows_filtered(
                catalog,
                call_import_id,
                diarised_status_filter="pending",
            )
            == 1
        )
        ids = list_call_import_row_ids_filtered(
            catalog,
            call_import_id,
            search_term="alpha",
        )
        assert ids == [row_a_id]
    finally:
        catalog.close()
