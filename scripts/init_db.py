"""Database initialization script."""

from app.database import init_db, engine
from app.models.database import Base

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Database initialized successfully!")

