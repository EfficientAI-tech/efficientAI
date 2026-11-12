"""
Static checks for migration scope vs touched tables (sharded deployments).

Run via tests/test_core/test_migration_scope_audit.py on every CI build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Row / payload tables queried on data shards when DB sharding is enabled.
SHARD_DATA_TABLES = frozenset(
    {
        "call_import_rows",
        "call_import_evaluation_rows",
        "evaluator_result_payloads",
        "call_recording_payloads",
        "platform_import_ledger_rows",
    }
)

SCOPE_RE = re.compile(r'MIGRATION_SCOPE\s*=\s*["\'](\w+)["\']')
TABLE_RE = re.compile(
    r"\b(?:ALTER\s+TABLE|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|"
    r"DROP\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+([a-z_][a-z0-9_]*)",
    re.I,
)


@dataclass(frozen=True)
class MigrationScopeIssue:
    migration: str
    scope: str
    shard_tables: tuple[str, ...]
    message: str


def _migration_scope(source: str) -> str:
    match = SCOPE_RE.search(source)
    return match.group(1) if match else "all"


def _upgrade_section(source: str) -> str:
    if "def downgrade" in source:
        return source.split("def downgrade", 1)[0]
    return source


def iter_migration_files() -> Iterable[Path]:
    return sorted(
        path
        for path in MIGRATIONS_DIR.glob("[0-9]*.py")
        if not path.stem.startswith("__")
    )


def find_catalog_scope_shard_table_mismatches() -> List[MigrationScopeIssue]:
    """Catalog-only migrations must not ALTER/CREATE shard row tables."""
    issues: List[MigrationScopeIssue] = []
    for path in iter_migration_files():
        source = path.read_text(encoding="utf-8")
        scope = _migration_scope(source)
        if scope != "catalog":
            continue
        tables = set(TABLE_RE.findall(_upgrade_section(source)))
        shard_touch = sorted(tables & SHARD_DATA_TABLES)
        if not shard_touch:
            continue
        issues.append(
            MigrationScopeIssue(
                migration=path.name,
                scope=scope,
                shard_tables=tuple(shard_touch),
                message=(
                    f"{path.name} is catalog-scoped but touches shard data table(s): "
                    f"{', '.join(shard_touch)}"
                ),
            )
        )
    return issues


def find_duplicate_migration_stems() -> List[str]:
    stems: List[str] = [path.stem for path in iter_migration_files()]
    seen: set[str] = set()
    dups: List[str] = []
    for stem in stems:
        if stem in seen:
            dups.append(stem)
        seen.add(stem)
    return sorted(dups)


def required_shard_migrations() -> Sequence[tuple[str, str]]:
    """(filename prefix, expected MIGRATION_SCOPE) for high-risk call-import DDL."""
    return (
        ("108_call_import_recording_duration_seconds", "all"),
        ("103_platform_import_hardening", "all"),
        ("054_call_import_sharding", "all"),
    )


def assert_required_scopes() -> List[str]:
    errors: List[str] = []
    for prefix, expected in required_shard_migrations():
        matches = [p for p in iter_migration_files() if p.stem == prefix]
        if not matches:
            errors.append(f"Missing migration {prefix}")
            continue
        source = matches[0].read_text(encoding="utf-8")
        scope = _migration_scope(source)
        if scope != expected:
            errors.append(
                f"{matches[0].name}: expected MIGRATION_SCOPE={expected!r}, got {scope!r}"
            )
    return errors
