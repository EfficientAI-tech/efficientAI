---
id: development
title: Development & Troubleshooting
sidebar_position: 2
---

# 🛠️ Development

## Running Locally

Start PostgreSQL and Redis:

```bash
docker compose up -d db redis
```

Run the application with hot reload:

```bash
# Backend auto-reload + Frontend auto-rebuild on file changes
eai start --config config.yml --watch-frontend
```

The `--watch-frontend` flag automatically rebuilds the frontend whenever you modify source files (`.tsx`, `.ts`, `.css`, etc.), so you don't need to manually rebuild after each change.

Run Celery worker (in separate terminal):

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

## Frontend Development

**Option 1: Using CLI with watch mode (Recommended)**

```bash
# From project root - automatically rebuilds on changes
eai start --watch-frontend
```

**Option 2: Using Vite dev server (for instant hot module replacement)**

```bash
cd frontend
npm install
npm run dev
```

This runs Vite dev server on http://localhost:3000 with instant hot module replacement. 

**Note**: You'll need to run the backend separately on port 8000.

# 🔧 Troubleshooting

## Database Migration Issues

**Problem**: After cloning the repository, you see errors like:

```
psycopg2.errors.UndefinedColumn: column "organization_id" of relation "api_keys" does not exist
```

**Cause**: The database schema is out of sync with the code. This happens when:
- The database was created before migrations were added
- Migrations failed to run on startup
- The database was created using an older version of the code

**Solution**:

Check migration status:

```bash
python scripts/check_migrations.py
```

This will show which migrations have been applied and identify any schema issues.

Run migrations manually:

```bash
# Using CLI (recommended)
eai migrate --verbose

# Or using Python directly
python -c "from app.core.migrations import run_migrations; run_migrations()"
```

**If you're using a fresh database (just created/nuked):**

- The migration system now handles fresh databases correctly
- If tables don't exist, migrations will skip them and `init_db()` will create them with the correct schema

However, if you see this error on a fresh DB, try:

```bash
# Stop the application
# Then run migrations explicitly
eai migrate --verbose
# Then start the application again
eai start
```

**If migrations still fail:**

1. Ensure your database connection is correct in `config.yml` or `.env`
2. Check that you have the necessary permissions on the database
3. Review the migration logs for specific errors
4. You may need to manually add missing columns (see migration files in `migrations/` directory)

**For fresh databases**: Make sure migrations run BEFORE any tables are created.

**For Docker setups**:

```bash
docker compose exec api eai migrate --verbose
```

**Important for Docker**: If you nuked the DB container and created a new one:
- The new container starts with an empty database
- Migrations should run automatically on startup
- If they don't, run them manually as shown above

**Prevention**: Always ensure migrations run successfully before using the application. Check the startup logs for migration status messages.

# 📞 Support

- 📧 Email: tejas@efficientai.cloud
- 📅 Book a Demo: Schedule a call
- 💬 LinkedIn: Connect with us
- 🐦 X (Twitter): Follow us
- 💻 GitHub: View on GitHub

# 📄 License

MIT License - see LICENSE file for details
