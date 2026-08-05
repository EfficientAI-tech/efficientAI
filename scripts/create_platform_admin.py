"""
Create a platform administrator account.

Usage:
    python -m scripts.create_platform_admin --email ops@example.com --password 'SecurePass1!'

Loads config.yml and runs pending migrations so the admin is created in the
same catalog database the API server uses (important when DB sharding is on).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from app.config import load_config_from_file
from app.core.migrations import run_migrations
from app.core.password import hash_password, validate_password_strength
from app.database import SessionLocal, init_db
from app.db_sharding.pool_manager import db_pool_manager
from app.models.database import PlatformAdmin

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"


def _load_runtime_config() -> None:
    if CONFIG_PATH.exists():
        load_config_from_file(str(CONFIG_PATH))
    db_pool_manager.reset()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an EfficientAI platform admin.")
    parser.add_argument("--email", required=True, help="Platform admin email address.")
    parser.add_argument(
        "--password",
        help="Password (prompted securely when omitted).",
        default=None,
    )
    args = parser.parse_args()

    password = args.password or getpass.getpass("Platform admin password: ")
    try:
        validate_password_strength(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _load_runtime_config()
    init_db()
    run_migrations()

    db = SessionLocal()
    try:
        existing = db.query(PlatformAdmin).filter(PlatformAdmin.email == args.email).first()
        if existing is not None:
            print(f"Platform admin already exists for {args.email}.", file=sys.stderr)
            return 3

        admin = PlatformAdmin(
            email=args.email,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        admin_count = (
            db.query(PlatformAdmin)
            .filter(PlatformAdmin.is_active == True)  # noqa: E712
            .count()
        )
        catalog_url = str(db_pool_manager.catalog_engine.url)
        print(f"Created platform admin {args.email} (id={admin.id})")
        print(f"  Catalog database: {catalog_url}")
        print(f"  Active platform admins: {admin_count}")
        print()
        print("Sign in at /platform/login on the frontend.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
