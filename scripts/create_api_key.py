"""
Create an API key bound to an existing organization.

Usage:
    # Create a key in an existing organization, by org id:
    python -m scripts.create_api_key --org-id <uuid> --name "my-key"

    # Create a key and a brand-new organization in one shot (OSS onboarding):
    python -m scripts.create_api_key --new-org "Acme Inc" --name "initial-key"

The previous version of this script created `APIKey` rows without an
`organization_id`. Every route in the app scopes data by organization, so
those keys would return empty results or trip `NULL` invariants. This
version enforces that an org must exist or be created.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from uuid import UUID

from app.database import SessionLocal, init_db
from app.models.database import APIKey, Organization


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an EfficientAI API key.")
    parser.add_argument("--name", help="Human-readable name for the key.", default=None)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--org-id",
        help="UUID of an existing organization to attach the key to.",
        default=None,
    )
    group.add_argument(
        "--new-org",
        help="Name of a new organization to create and attach the key to.",
        default=None,
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    try:
        if args.org_id:
            try:
                org_uuid = UUID(args.org_id)
            except ValueError:
                print(f"--org-id must be a UUID, got: {args.org_id}", file=sys.stderr)
                return 2
            org = db.query(Organization).filter(Organization.id == org_uuid).first()
            if org is None:
                print(f"Organization {args.org_id} does not exist.", file=sys.stderr)
                return 3
        else:
            org = Organization(name=args.new_org)
            db.add(org)
            db.flush()

        api_key = secrets.token_urlsafe(32)
        db_key = APIKey(
            key=api_key,
            name=args.name,
            organization_id=org.id,
            is_active=True,
        )
        db.add(db_key)
        db.commit()
        db.refresh(db_key)
        db.refresh(org)

        print("API Key created successfully!")
        print(f"  Organization: {org.name} ({org.id})")
        print(f"  Name:         {args.name or '(unnamed)'}")
        print(f"  Key:          {api_key}")
        print()
        print("Use this header in your requests:")
        print(f"  X-API-Key: {api_key}")
        return 0

    except Exception as exc:
        db.rollback()
        print(f"Error creating API key: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
