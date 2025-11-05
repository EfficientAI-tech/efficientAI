# Database Migrations

This directory contains database migration scripts that run automatically when the application starts.

## How It Works

1. **Automatic Execution**: Migrations run automatically on application startup via `app/main.py`
2. **Version Tracking**: Applied migrations are tracked in the `schema_migrations` table
3. **Idempotent**: Each migration only runs once, even if the application restarts
4. **Ordered Execution**: Migrations run in alphabetical order (use numbered prefixes)

## Migration File Format

Each migration file should:
- Be named with a numeric prefix: `001_description.py`, `002_another.py`, etc.
- Have a `description` variable at the top
- Have an `upgrade(db)` function that takes a SQLAlchemy Session

Example:

```python
"""
Migration: Add New Feature
Description of what this migration does.
"""

description = "Add new feature support"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    
    # Your migration code here
    db.execute(text("CREATE TABLE IF NOT EXISTS new_table (...)"))
    db.commit()
```

## Running Migrations Manually

You can run migrations manually using the CLI:

```bash
eai migrate
```

Or with verbose output:

```bash
eai migrate --verbose
```

## Creating New Migrations

1. Create a new file in `migrations/` directory
2. Use the next sequential number: `004_new_feature.py`
3. Follow the format above
4. Test the migration on a development database first

## Best Practices

- **Use IF NOT EXISTS**: Always check if objects exist before creating them
- **Handle Errors Gracefully**: Use try/except blocks for idempotent operations
- **Use Transactions**: Wrap related changes in transactions
- **Test First**: Test migrations on a copy of production data if possible
- **Document Changes**: Include clear descriptions of what each migration does

## Migration Order

Current migrations:
- `001_add_organizations.py` - Adds organization-based multi-tenancy
- `002_add_iam.py` - Adds user management, memberships, and invitations
- `003_add_integrations.py` - Adds external platform integrations support

## Troubleshooting

If a migration fails:
1. Check the application logs for error details
2. Fix the migration script
3. Manually remove the failed migration from `schema_migrations` table if needed
4. Re-run the migration

## Notes

- Migrations use raw SQL for maximum control over PostgreSQL features
- The migration system tracks which migrations have been applied
- Never modify existing migration files after they've been applied to production
- Always create new migrations for schema changes

