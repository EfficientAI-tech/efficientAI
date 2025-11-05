# Voice AI Evaluation Platform

A voice AI evaluation platform built with FastAPI and React. Supports audio file uploads, evaluation processing with multiple metrics, batch processing, and a modern web interface.

## Quick Start

There are two ways to run the application:

### Method 1: Using Docker Compose

1. **Start all services**
   ```bash
   docker compose up -d
   ```

2. **Initialize database** (migrations run automatically on startup, but you can also run manually)
   ```bash
   # Option 1: Let migrations run automatically on startup
   # (No action needed - migrations run when the app starts)
   
   # Option 2: Run migrations manually before starting
   docker compose exec api eai migrate
   ```

3. **Create an API key**
   ```bash
   docker compose exec api python scripts/create_api_key.py "My API Key"
   ```

4. **Access the application**
   - Frontend: http://localhost:8000/
   - API Docs: http://localhost:8000/docs

### Method 2: Using Command Line (CLI)

1. **Install the package**
   ```bash
   pip install -e .
   ```

2. **Generate configuration file**
   ```bash
   eai init-config
   ```

3. **Edit `config.yml`** with your database and Redis connection strings:
   ```yaml
   database:
     url: "postgresql://efficientai:password@localhost:5432/efficientai"
   
   redis:
     url: "redis://localhost:6379/0"
   ```

4. **Start the application**
   ```bash
   eai start --config config.yml
   ```

   The application will automatically:
   - Build the frontend (if needed)
   - Start the API server
   - Serve both API and frontend from the same server

   **For development with hot reload:**
   ```bash
   # Enable auto-rebuild of frontend on file changes
   eai start --config config.yml --watch-frontend
   ```
   
   This will:
   - Automatically rebuild the frontend when source files change
   - Keep the backend hot-reload enabled (by default)
   - Perfect for active frontend development

5. **Access the application**
   - Frontend: http://localhost:8000/
   - API Docs: http://localhost:8000/docs

## Prerequisites

**For Docker Compose:**
- Docker and Docker Compose installed

**For CLI:**
- Python 3.11+
- Node.js 18+ and npm
- PostgreSQL running (locally or remote)
- Redis running (locally or remote)

## CLI Commands

### Start Application
```bash
# Start with default config.yml
eai start

# Start with custom config
eai start --config production.yml

# Start with frontend file watching (auto-rebuild on changes)
eai start --watch-frontend

# Start without building frontend (if already built)
eai start --no-build-frontend

# Start without auto-reload (production mode)
eai start --no-reload --no-build-frontend
```

**Development Mode:**
```bash
# Full development setup with both backend and frontend hot reload
eai start --watch-frontend --reload
```

### Generate Config File
```bash
# Generate default config.yml
eai init-config

# Generate custom config file
eai init-config --output my-config.yml
```

### Database Migrations
```bash
# Run pending migrations manually
eai migrate

# Run migrations with verbose output
eai migrate --verbose
```

**Note:** Migrations run automatically on application startup. You only need to run them manually if you want to apply migrations before starting the server.

## Configuration

### YAML Configuration (for CLI)

Edit `config.yml` to configure your application:

```yaml
# Server Settings
server:
  host: "0.0.0.0"
  port: 8000

# Database Configuration
database:
  url: "postgresql://user:password@host:port/dbname"

# Redis Configuration
redis:
  url: "redis://host:port/db"

# File Storage
storage:
  upload_dir: "./uploads"
  max_file_size_mb: 500
```

### Environment Variables (for Docker)

Create a `.env` file for Docker Compose:

```env
DATABASE_URL=postgresql://efficientai:password@db:5432/efficientai
POSTGRES_USER=efficientai
POSTGRES_PASSWORD=password
POSTGRES_DB=efficientai
REDIS_URL=redis://redis:6379/0
SECRET_KEY=your-secret-key-here
```

## Database Migrations

The application includes an automatic migration system that runs database schema changes on startup.

### How It Works

- **Automatic Execution**: Migrations run automatically when the application starts
- **Version Tracking**: Applied migrations are tracked in the `schema_migrations` table
- **Idempotent**: Each migration only runs once, even if the application restarts
- **Ordered Execution**: Migrations run in alphabetical order (use numbered prefixes like `001_`, `002_`, etc.)

### Migration Files

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

### Running Migrations

**Automatic (Recommended):**
- Migrations run automatically when you start the app with `eai start`

**Manual:**
```bash
# Run migrations manually
eai migrate

# With verbose output
eai migrate --verbose
```

### Creating New Migrations

1. Create a new file in `migrations/` directory with the next sequential number
2. Follow the format shown above
3. Test the migration on a development database first
4. Use `IF NOT EXISTS` checks for idempotent operations

See `migrations/README.md` for detailed documentation.

## Development

### Running Locally

1. **Start PostgreSQL and Redis**
   ```bash
   docker compose up -d db redis
   ```

2. **Run the application with hot reload**
   ```bash
   # Backend auto-reload + Frontend auto-rebuild on file changes
   eai start --config config.yml --watch-frontend
   ```
   
   The `--watch-frontend` flag automatically rebuilds the frontend whenever you modify source files (`.tsx`, `.ts`, `.css`, etc.), so you don't need to manually rebuild after each change.

3. **Run Celery worker** (in separate terminal)
   ```bash
   celery -A app.workers.celery_app worker --loglevel=info
   ```

### Frontend Development

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
This runs Vite dev server on `http://localhost:3000` with instant hot module replacement. Note: You'll need to run the backend separately on port 8000.

## License

MIT License - see LICENSE file for details
