---
id: database
title: Database
sidebar_position: 1
---

# 🗄️ Database Migrations

The application includes an automatic migration system that runs database schema changes on startup.

## How It Works

- **Automatic Execution**: Migrations run automatically when the application starts
- **Version Tracking**: Applied migrations are tracked in the `schema_migrations` table
- **Idempotent**: Each migration only runs once, even if the application restarts
- **Ordered Execution**: Migrations run in alphabetical order (use numbered prefixes like 001_, 002_, etc.)

## Migration Files

Migrations are stored in the `migrations/` directory. Each migration file should:

1. Have a numeric prefix: `001_description.py`, `002_another.py`, etc.
2. Include a `description` variable
3. Have an `upgrade(db)` function that takes a SQLAlchemy Session

Example migration:

```python
"""
Migration: Add New Feature
"""

description = "Add new feature support"

def upgrade(db):
    """Apply this migration."""
    from sqlalchemy import text
    
    db.execute(text("CREATE TABLE IF NOT EXISTS new_table (...)"))
    db.commit()
```

## Running Migrations

**Automatic (Recommended - Default Behavior):**

- ✅ Migrations run automatically when you start the app with `eai start`
- ✅ Migrations also run automatically when the application starts (via lifespan handler)
- ✅ If migrations fail, the application will NOT start - this ensures database consistency
- ✅ API requests are blocked if migrations are pending
- ✅ When cloning from main, migrations will run automatically on first startup
- ✅ Each migration only runs once (tracked in `schema_migrations` table)

**Manual:**

```bash
# Run migrations manually
eai migrate

# With verbose output
eai migrate --verbose
```

**Skip migrations (not recommended):**

```bash
# Only use this if you know what you're doing
eai start --skip-migrations
```

## Creating New Migrations

1. Create a new file in `migrations/` directory with the next sequential number
2. Follow the format shown above
3. Test the migration on a development database first
4. Use `IF NOT EXISTS` checks for idempotent operations
5. See `migrations/README.md` for detailed documentation.

# 📊 Database ER Diagram

Generate a visual Entity-Relationship (ER) diagram of your database schema to visualize table structures and relationships.

## Prerequisites

Install the required system and Python packages:

```bash
# Install system graphviz package
sudo apt-get update
sudo apt-get install -y graphviz libgraphviz-dev pkg-config

# Install Python packages
pip install eralchemy graphviz
```

## Generating the ER Diagram

Run the script to generate a PNG ER diagram:

```bash
python scripts/generate_er_diagram_simple.py
```

This will create `schema_er_diagram.png` in the project root directory, showing:

- All database tables
- Column names and types
- Primary keys
- Foreign key relationships
- Indexes

**Note**: The diagram is automatically generated from your current database schema, so make sure your database is running and migrations are up to date.
