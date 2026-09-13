"""Tests for sharded migration scope, gap recovery, and catalog schema verification."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.migrations import (
    MigrationRunner,
    _catalog_migration_gaps,
    _is_catalog_engine_url,
    _migration_applies_to_engine,
    verify_catalog_schema,
)
from app.core.migrations import MIGRATIONS_DIR


@pytest.fixture
def catalog_db():
    engine = create_engine("sqlite:///:memory:")
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    db.execute(
        text(
            """
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL
            )
            """
        )
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_migration_applies_catalog_only_on_catalog_engine():
    catalog_migration = MIGRATIONS_DIR / "086_user_session_epoch.py"
    all_migration = MIGRATIONS_DIR / "088_refresh_token_authenticated_org_ids.py"

    assert _migration_applies_to_engine(
        catalog_migration,
        is_catalog=True,
        sharding_enabled=True,
    )
    assert not _migration_applies_to_engine(
        catalog_migration,
        is_catalog=False,
        sharding_enabled=True,
    )
    assert _migration_applies_to_engine(
        all_migration,
        is_catalog=False,
        sharding_enabled=True,
    )


def test_migration_applies_everything_when_sharding_disabled():
    catalog_migration = MIGRATIONS_DIR / "086_user_session_epoch.py"
    assert _migration_applies_to_engine(
        catalog_migration,
        is_catalog=False,
        sharding_enabled=False,
    )


def test_catalog_migration_gaps_detect_missing_prerequisites():
    applied = {
        "088_refresh_token_authenticated_org_ids",
        "089_refresh_token_authenticated_org_epochs",
        "090_organization_member_session_revocations",
    }
    gaps = _catalog_migration_gaps(applied)
    gap_versions = {path.stem for path in gaps}
    assert "086_user_session_epoch" in gap_versions
    assert "087_organization_member_credentials" in gap_versions


def test_catalog_migration_gaps_empty_when_prerequisites_applied():
    applied = {
        "086_user_session_epoch",
        "087_organization_member_credentials",
        "088_refresh_token_authenticated_org_ids",
    }
    gaps = _catalog_migration_gaps(applied)
    assert gaps == []


def test_pending_includes_catalog_gaps(catalog_db):
    catalog_db.execute(
        text(
            """
            CREATE TABLE schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
            """
        )
    )
    for version in (
        "088_refresh_token_authenticated_org_ids",
        "089_refresh_token_authenticated_org_epochs",
        "090_organization_member_session_revocations",
    ):
        catalog_db.execute(
            text("INSERT INTO schema_migrations (version, description) VALUES (:version, :description)"),
            {"version": version, "description": version},
        )
    catalog_db.commit()

    runner = MigrationRunner(catalog_db, is_catalog=True, sharding_enabled=True)
    pending_versions = {path.stem for path in runner.get_pending_migrations()}
    assert "086_user_session_epoch" in pending_versions
    assert "087_organization_member_credentials" in pending_versions
    assert "091_catalog_security_schema_repair" in pending_versions


def test_verify_catalog_schema_reports_missing_session_epoch(catalog_db):
    errors = verify_catalog_schema(catalog_db)
    assert "users.session_epoch column missing" in errors


def test_verify_catalog_schema_passes_with_session_epoch(catalog_db):
    catalog_db.execute(
        text("ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0")
    )
    catalog_db.execute(
        text(
            """
            CREATE TABLE organization_member_credentials (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                user_id TEXT NOT NULL
            )
            """
        )
    )
    catalog_db.commit()
    assert verify_catalog_schema(catalog_db) == []


def test_is_catalog_engine_url_ignores_masked_password(monkeypatch):
    from sqlalchemy.engine import make_url

    catalog_url = "postgresql://efficientai:password@localhost:5432/efficientai"
    monkeypatch.setattr(
        "app.config.settings",
        type(
            "S",
            (),
            {
                "DB_SHARDING_ENABLED": True,
                "DB_CATALOG_URL": catalog_url,
                "DATABASE_URL": catalog_url,
            },
        )(),
    )
    engine_url = make_url(catalog_url)
    assert _is_catalog_engine_url(engine_url)


def test_is_catalog_engine_url_matches_catalog_host(monkeypatch):
    catalog_url = "postgresql://user:pass@catalog-host:5432/efficientai?sslmode=require"
    monkeypatch.setattr(
        "app.config.settings",
        type(
            "S",
            (),
            {
                "DB_SHARDING_ENABLED": True,
                "DB_CATALOG_URL": catalog_url,
                "DATABASE_URL": "postgresql://user:pass@shard-host:5432/efficientai_data_01",
            },
        )(),
    )
    assert _is_catalog_engine_url(catalog_url)
    assert not _is_catalog_engine_url(
        "postgresql://user:pass@shard-host:5432/efficientai_data_01?sslmode=require"
    )
