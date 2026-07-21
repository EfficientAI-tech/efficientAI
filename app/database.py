"""Database connection and session management."""

from sqlalchemy.orm import declarative_base

from app.db_sharding.pool_manager import db_pool_manager

class _EngineProxy:
    """Proxy so `from app.database import engine` works after lazy init."""

    def __getattr__(self, name):
        return getattr(db_pool_manager.catalog_engine, name)

    def __repr__(self):
        return repr(db_pool_manager.catalog_engine)


engine = _EngineProxy()


class _SessionLocalFactory:
    def __call__(self):
        factory = db_pool_manager.catalog_session_factory()
        return factory()

    def __getattr__(self, name):
        return getattr(db_pool_manager.catalog_session_factory(), name)


SessionLocal = _SessionLocalFactory()

# Base class for models
Base = declarative_base()


def get_db():
    """
    Dependency for FastAPI to get database session.

    Yields:
        Database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database by creating all tables and run column migrations."""
    # Import all models so SQLAlchemy registers them with Base.metadata
    # before create_all is called. Without this, tables won't be created
    # on a fresh database.
    import app.models.database  # noqa: F401

    for eng in db_pool_manager.all_engines_for_migrations():
        Base.metadata.create_all(bind=eng)
    _run_column_migrations()


def _run_column_migrations():
    """Add new columns to existing tables if they don't exist yet."""
    from sqlalchemy import inspect, text

    migrations = [
        ("evaluators", "name", "ALTER TABLE evaluators ADD COLUMN name VARCHAR"),
        ("evaluators", "custom_prompt", "ALTER TABLE evaluators ADD COLUMN custom_prompt TEXT"),
        ("evaluators", "agent_id", None),  # ALTER nullable handled below
        ("evaluators", "persona_id", None),
        ("evaluators", "scenario_id", None),
        ("evaluators", "llm_provider", "ALTER TABLE evaluators ADD COLUMN llm_provider VARCHAR"),
        ("evaluators", "llm_model", "ALTER TABLE evaluators ADD COLUMN llm_model VARCHAR"),
    ]

    for eng in db_pool_manager.all_engines_for_migrations():
        inspector = inspect(eng)
        if not inspector.has_table("evaluators"):
            continue
        with eng.begin() as conn:
            existing_cols = {c["name"] for c in inspector.get_columns("evaluators")}

            for table, column, ddl in migrations:
                if ddl and column not in existing_cols:
                    conn.execute(text(ddl))

            nullable_changes = [
                ("evaluators", "agent_id"),
                ("evaluators", "persona_id"),
                ("evaluators", "scenario_id"),
                ("evaluator_results", "agent_id"),
            ]
            for table, column in nullable_changes:
                if not inspector.has_table(table):
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"))
                except Exception:
                    pass
