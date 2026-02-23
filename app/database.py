"""Database connection and session management."""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Create database engine
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={"options": "-c timezone=UTC"},
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    Base.metadata.create_all(bind=engine)
    _run_column_migrations()


def _run_column_migrations():
    """Add new columns to existing tables if they don't exist yet."""
    from sqlalchemy import text, inspect
    
    inspector = inspect(engine)
    
    migrations = [
        ("evaluators", "name", "ALTER TABLE evaluators ADD COLUMN name VARCHAR"),
        ("evaluators", "custom_prompt", "ALTER TABLE evaluators ADD COLUMN custom_prompt TEXT"),
        ("evaluators", "agent_id", None),  # ALTER nullable handled below
        ("evaluators", "persona_id", None),
        ("evaluators", "scenario_id", None),
        ("evaluators", "llm_provider", "ALTER TABLE evaluators ADD COLUMN llm_provider VARCHAR"),
        ("evaluators", "llm_model", "ALTER TABLE evaluators ADD COLUMN llm_model VARCHAR"),
    ]
    
    with engine.begin() as conn:
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
            try:
                conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"))
            except Exception:
                pass

