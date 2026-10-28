"""Static migration scope audit — prevents catalog-only DDL on shard row tables."""

from __future__ import annotations

from app.core.migration_scope_audit import (
    assert_required_scopes,
    find_catalog_scope_shard_table_mismatches,
    find_duplicate_migration_stems,
)


def test_no_catalog_scoped_migrations_touch_shard_data_tables():
    issues = find_catalog_scope_shard_table_mismatches()
    assert issues == [], "\n".join(issue.message for issue in issues)


def test_migration_version_stems_are_unique():
    assert find_duplicate_migration_stems() == []


def test_call_import_shard_ddl_uses_all_scope():
    errors = assert_required_scopes()
    assert errors == [], "\n".join(errors)
