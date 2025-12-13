#!/usr/bin/env python3
"""Check database connection and credentials"""

from app.config import settings
from app.database import engine
from sqlalchemy import text

print("=" * 80)
print("Database Connection Information")
print("=" * 80)
print(f"Host: {settings.POSTGRES_HOST}")
print(f"Port: {settings.POSTGRES_PORT}")
print(f"Database: {settings.POSTGRES_DB}")
print(f"Username: {settings.POSTGRES_USER}")
print(f"Password: {'*' * len(settings.POSTGRES_PASSWORD) if settings.POSTGRES_PASSWORD else 'NOT SET'}")
print(f"\nConnection URL: {settings.DATABASE_URL.split('@')[0]}@***")
print("\n" + "=" * 80)

# Try to connect
try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT current_user, current_database(), version()"))
        row = result.fetchone()
        print("✅ Connection successful!")
        print(f"Connected as: {row[0]}")
        print(f"Database: {row[1]}")
        print(f"PostgreSQL version: {row[2].split(',')[0]}")
        
        # Check if efficientai user exists
        result = conn.execute(text("""
            SELECT usename FROM pg_user WHERE usename = :username
        """), {"username": settings.POSTGRES_USER})
        user_exists = result.fetchone()
        
        if user_exists:
            print(f"\n✅ User '{settings.POSTGRES_USER}' exists in database")
        else:
            print(f"\n❌ User '{settings.POSTGRES_USER}' does NOT exist in database")
            print("\nTo create the user, run as postgres superuser:")
            print(f"  CREATE USER {settings.POSTGRES_USER} WITH PASSWORD '{settings.POSTGRES_PASSWORD}';")
            print(f"  GRANT ALL PRIVILEGES ON DATABASE {settings.POSTGRES_DB} TO {settings.POSTGRES_USER};")
        
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print("\nTroubleshooting:")
    print("1. Check if PostgreSQL is running")
    print("2. Verify the password is correct")
    print("3. Check if the user exists")
    print("4. Verify pg_hba.conf allows password authentication")

