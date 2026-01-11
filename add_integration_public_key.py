"""Add public_key column to integrations table."""

from sqlalchemy import text
from app.database import engine

def upgrade():
    """Add public_key column to integrations table."""
    with engine.connect() as conn:
        # Add public_key column (nullable for existing records)
        conn.execute(text("""
            ALTER TABLE integrations
            ADD COLUMN IF NOT EXISTS public_key VARCHAR(255)
        """))
        conn.commit()
        print("✅ Added public_key column to integrations table")

def downgrade():
    """Remove public_key column from integrations table."""
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE integrations
            DROP COLUMN IF EXISTS public_key
        """))
        conn.commit()
        print("✅ Removed public_key column from integrations table")

if __name__ == "__main__":
    upgrade()
