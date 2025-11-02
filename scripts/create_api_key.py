"""Script to create API keys."""

import sys
import secrets
from app.database import SessionLocal, init_db
from app.models.database import APIKey

if __name__ == "__main__":
    # Initialize database if needed
    init_db()

    db = SessionLocal()

    try:
        name = sys.argv[1] if len(sys.argv) > 1 else None
        api_key = secrets.token_urlsafe(32)

        db_key = APIKey(key=api_key, name=name)
        db.add(db_key)
        db.commit()

        print(f"API Key created successfully!")
        print(f"Name: {name or 'N/A'}")
        print(f"Key: {api_key}")
        print(f"\nUse this header in your requests:")
        print(f"X-API-Key: {api_key}")

    except Exception as e:
        print(f"Error creating API key: {e}")
        db.rollback()
    finally:
        db.close()

