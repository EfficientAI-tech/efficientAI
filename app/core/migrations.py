"""
Database migration system that runs automatically on application startup.
Migrations are tracked in a `schema_migrations` table to ensure they only run once.
"""

import sys
from pathlib import Path
from typing import List, Set, Tuple
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker
import logging

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def _sorted_migration_files() -> List[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(
        path
        for path in MIGRATIONS_DIR.glob("*.py")
        if not path.stem.startswith("__")
    )


def _migration_scope_for_file(migration_file: Path) -> str:
    import importlib.util

    version = migration_file.stem
    spec = importlib.util.spec_from_file_location(f"migrations_scope_{version}", migration_file)
    if spec is None or spec.loader is None:
        return "all"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(getattr(module, "MIGRATION_SCOPE", "all") or "all")


def _canonical_db_url_key(url) -> tuple:
    """Compare DB URLs ignoring driver suffix normalisation (postgresql vs postgresql+psycopg2)."""
    from sqlalchemy.engine import URL, make_url

    parsed = url if isinstance(url, URL) else make_url(url)
    driver = (parsed.drivername or "").split("+", 1)[0]
    return (
        driver,
        parsed.username or "",
        parsed.password or "",
        parsed.host or "",
        parsed.port,
        parsed.database or "",
    )


def _is_catalog_engine_url(engine_url) -> bool:
    from app.config import settings

    if not getattr(settings, "DB_SHARDING_ENABLED", False):
        return True
    catalog_url = getattr(settings, "DB_CATALOG_URL", None) or settings.DATABASE_URL
    try:
        return _canonical_db_url_key(engine_url) == _canonical_db_url_key(catalog_url)
    except Exception:
        return str(engine_url) == str(catalog_url)


def _migration_applies_to_engine(
    migration_file: Path,
    *,
    is_catalog: bool,
    sharding_enabled: bool,
) -> bool:
    if not sharding_enabled:
        return True
    scope = _migration_scope_for_file(migration_file)
    if scope == "all":
        return True
    if scope == "catalog":
        return is_catalog
    if scope == "shard":
        return not is_catalog
    return True


def _catalog_migration_gaps(applied: Set[str]) -> List[Path]:
    """Catalog-scoped migrations missing while a later migration was already applied."""
    gaps: List[Path] = []
    all_files = _sorted_migration_files()
    for migration_file in all_files:
        version = migration_file.stem
        if version in applied:
            continue
        if _migration_scope_for_file(migration_file) != "catalog":
            continue
        if any(other.stem in applied and other.stem > version for other in all_files):
            gaps.append(migration_file)
    return gaps


def verify_catalog_schema(db: Session) -> List[str]:
    """Return errors when required catalog auth schema is missing."""
    errors: List[str] = []
    inspector = inspect(db.get_bind())

    if not inspector.has_table("users"):
        return errors

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "session_epoch" not in user_columns:
        errors.append("users.session_epoch column missing")

    if not inspector.has_table("organization_member_credentials"):
        errors.append("organization_member_credentials table missing")

    return errors


class MigrationRunner:
    """Handles running database migrations in order."""

    def __init__(self, db: Session, *, is_catalog: bool, sharding_enabled: bool = False):
        self.db = db
        self.is_catalog = is_catalog
        self.sharding_enabled = sharding_enabled
        self.ensure_migrations_table()

    def ensure_migrations_table(self):
        """Create the schema_migrations table if it doesn't exist."""
        try:
            self.db.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """))
            self.db.commit()
            logger.info("Schema migrations table ready")
        except Exception as e:
            logger.error(f"Error creating migrations table: {e}")
            self.db.rollback()
            raise

    def get_applied_migrations(self) -> List[str]:
        """Get list of already applied migration versions."""
        try:
            result = self.db.execute(text("SELECT version FROM schema_migrations ORDER BY version"))
            return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching applied migrations: {e}")
            return []

    def record_migration(self, version: str, description: str):
        """Record that a migration has been applied."""
        try:
            self.db.execute(
                text("INSERT INTO schema_migrations (version, description) VALUES (:version, :description)"),
                {"version": version, "description": description}
            )
            self.db.commit()
            logger.info(f"Recorded migration: {version}")
        except Exception as e:
            logger.error(f"Error recording migration: {e}")
            self.db.rollback()
            raise

    def get_pending_migrations(self) -> List[Path]:
        """Get list of migration files that haven't been applied yet."""
        if not MIGRATIONS_DIR.exists():
            logger.warning(f"Migrations directory does not exist: {MIGRATIONS_DIR}")
            return []

        applied = set(self.get_applied_migrations())
        pending: List[Path] = []
        skipped_catalog: List[str] = []

        for migration_file in _sorted_migration_files():
            version = migration_file.stem
            if version in applied:
                continue
            if _migration_applies_to_engine(
                migration_file,
                is_catalog=self.is_catalog,
                sharding_enabled=self.sharding_enabled,
            ):
                pending.append(migration_file)
            elif self.is_catalog and _migration_scope_for_file(migration_file) == "catalog":
                skipped_catalog.append(version)

        if self.is_catalog:
            gap_versions = {path.stem for path in pending}
            for migration_file in _catalog_migration_gaps(applied):
                if migration_file.stem not in gap_versions:
                    logger.warning(
                        "Catalog migration gap detected: %s missing while later migrations are applied",
                        migration_file.stem,
                    )
                    pending.append(migration_file)
                    gap_versions.add(migration_file.stem)

        if skipped_catalog:
            logger.error(
                "Catalog engine skipped required catalog migrations: %s",
                ", ".join(skipped_catalog),
            )

        pending.sort(key=lambda path: path.stem)
        return pending

    def run_migration(self, migration_file: Path) -> bool:
        """Run a single migration file."""
        version = migration_file.stem
        logger.info(f"Running migration: {version}")

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"migrations_{version}", migration_file)
            if spec is None or spec.loader is None:
                logger.error(f"Could not load migration file: {migration_file}")
                return False

            migration_module = importlib.util.module_from_spec(spec)
            sys.modules[f"migrations_{version}"] = migration_module
            spec.loader.exec_module(migration_module)

            if not hasattr(migration_module, "upgrade"):
                logger.error(f"Migration {version} does not have an 'upgrade' function")
                return False

            migration_module.upgrade(self.db)
            description = getattr(migration_module, "description", "No description")
            self.record_migration(version, description)

            logger.info(f"Successfully applied migration: {version}")
            return True

        except Exception as e:
            import traceback
            logger.error(f"Error running migration {version}: {e}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            self.db.rollback()
            return False
        finally:
            if f"migrations_{version}" in sys.modules:
                del sys.modules[f"migrations_{version}"]

    def run_all(self) -> bool:
        """Run all pending migrations."""
        pending = self.get_pending_migrations()

        if not pending:
            logger.info("✅ No pending migrations - database is up to date")
            return True

        logger.info(f"📋 Found {len(pending)} pending migration(s):")
        for migration_file in pending:
            logger.info(f"   - {migration_file.name}")

        success = True

        for migration_file in pending:
            logger.info("")
            logger.info(f"🔄 Applying migration: {migration_file.name}")
            if not self.run_migration(migration_file):
                logger.error(f"❌ Failed to run migration: {migration_file.name}")
                success = False
                break
            logger.info(f"✅ Successfully applied: {migration_file.name}")

        if success:
            logger.info("")
            logger.info("✅ All pending migrations completed successfully")

        return success


def run_migrations():
    """
    Run all pending database migrations.
    This should be called on application startup.

    When sharding is enabled, catalog-scoped migrations run only on the catalog
    engine URL; scope=all migrations run on catalog and every shard.

    Raises:
        RuntimeError: If migrations fail, preventing application startup
    """
    from app.db_sharding.pool_manager import db_pool_manager

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True
    )

    logger.info("=" * 60)
    logger.info("🔄 Starting database migrations...")
    logger.info("=" * 60)

    sharding_enabled = db_pool_manager.sharding_enabled
    engines = db_pool_manager.all_engines_for_migrations()
    for idx, eng in enumerate(engines):
        url_hint = str(eng.url).split("@")[-1] if eng.url else f"engine-{idx}"
        is_catalog = _is_catalog_engine_url(eng.url)
        role_label = "catalog" if is_catalog else "shard"
        logger.info("Migration target: %s (role=%s)", url_hint, role_label)
        factory = sessionmaker(autocommit=False, autoflush=False, bind=eng)
        db = factory()
        try:
            runner = MigrationRunner(
                db,
                is_catalog=is_catalog,
                sharding_enabled=sharding_enabled,
            )

            applied = runner.get_applied_migrations()
            pending = runner.get_pending_migrations()

            if applied:
                logger.info(f"📊 Currently applied migrations: {len(applied)}")
                for version in applied[-5:]:
                    logger.info(f"   ✓ {version}")
                if len(applied) > 5:
                    logger.info(f"   ... and {len(applied) - 5} more")

            if not pending:
                if is_catalog:
                    schema_errors = verify_catalog_schema(db)
                    if schema_errors:
                        raise RuntimeError(
                            "Catalog auth schema incomplete after migrations: "
                            + "; ".join(schema_errors)
                        )
                logger.info("✅ Database is up to date - no migrations needed (%s)", url_hint)
                continue

            success = runner.run_all()
            if not success:
                logger.error("")
                logger.error("=" * 60)
                logger.error("❌ MIGRATION FAILED - Application cannot start!")
                logger.error("=" * 60)
                logger.error("Target: %s", url_hint)
                raise RuntimeError("Database migrations failed")

            final_pending = runner.get_pending_migrations()
            if final_pending:
                raise RuntimeError(
                    f"{len(final_pending)} migration(s) still pending after run on {url_hint}: "
                    + ", ".join(path.stem for path in final_pending)
                )

            if is_catalog:
                schema_errors = verify_catalog_schema(db)
                if schema_errors:
                    raise RuntimeError(
                        "Catalog auth schema incomplete after migrations: "
                        + "; ".join(schema_errors)
                    )

            logger.info("✅ Verification complete - all migrations applied (%s)", url_hint)
        except RuntimeError:
            raise
        except Exception as e:
            logger.error("❌ UNEXPECTED ERROR during migrations on %s: %s", url_hint, e)
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            raise
        finally:
            db.close()

    logger.info("=" * 60)


def check_migrations_status() -> Tuple[bool, List[str]]:
    """
    Check if there are any pending migrations.

    Uses the same engine list and per-engine ``MIGRATION_SCOPE`` rules as
    ``run_migrations`` so readiness checks do not false-positive when sharding
    is enabled.

    Returns:
        Tuple of (is_up_to_date, pending_migration_names)
    """
    from app.db_sharding.pool_manager import db_pool_manager

    pending_names: List[str] = []
    try:
        sharding_enabled = db_pool_manager.sharding_enabled
        for eng in db_pool_manager.all_engines_for_migrations():
            factory = sessionmaker(autocommit=False, autoflush=False, bind=eng)
            db = factory()
            try:
                is_catalog = _is_catalog_engine_url(eng.url)
                runner = MigrationRunner(
                    db,
                    is_catalog=is_catalog,
                    sharding_enabled=sharding_enabled,
                )
                for migration_file in runner.get_pending_migrations():
                    name = migration_file.stem
                    if name not in pending_names:
                        pending_names.append(name)
                if is_catalog:
                    for error in verify_catalog_schema(db):
                        marker = f"schema:{error}"
                        if marker not in pending_names:
                            pending_names.append(marker)
            finally:
                db.close()
        return (len(pending_names) == 0, pending_names)
    except Exception as e:
        logger.error(f"Error checking migration status: {e}")
        return (False, ["unknown"])


def ensure_migrations_directory():
    """Ensure the migrations directory exists."""
    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)

    init_file = MIGRATIONS_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# Migrations package\n")
