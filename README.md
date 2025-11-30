<div align="center">

# 🎙️ Efficient<span style="color: #EAB308;">AI</span>

[![GitHub Stars](https://img.shields.io/github/stars/EfficientAI-tech/efficientAI?style=social&label=Star)](https://github.com/EfficientAI-tech/efficientAI)
[![GitHub Forks](https://img.shields.io/github/forks/EfficientAI-tech/efficientAI?style=social&label=Fork)](https://github.com/EfficientAI-tech/efficientAI)

**Test your Voice AI Agents before Production**

<span style="color: #EAB308;">**Open-source**</span> evaluation platform for conversational AI.

Test quality, measure performance, & ship with confidence.

 [📅 Book a Demo](https://calendly.com/aadhar-efficientai/30min) • [💻 GitHub](https://github.com/EfficientAI-tech/efficientAI)

[![GitHub Stars](https://img.shields.io/github/stars/EfficientAI-tech/efficientAI?style=flat-square&logo=github)](https://github.com/EfficientAI-tech/efficientAI)
[![License](https://img.shields.io/github/license/EfficientAI-tech/efficientAI?style=flat-square)](https://github.com/EfficientAI-tech/efficientAI)
[![LinkedIn](https://img.shields.io/static/v1?label=Connect%20on&message=LinkedIn&color=0077B5&logo=LinkedIn&style=flat-square)](https://www.linkedin.com/company/efficientaicloud)
[![X (Twitter)](https://img.shields.io/static/v1?label=Follow%20on&message=X%20(Twitter)&color=000000&logo=X&style=flat-square)](https://x.com/AiEfficient)
[![Book a Demo](https://img.shields.io/static/v1?label=Schedule&message=Demo&color=006BFF&logo=Calendly&style=flat-square)](https://calendly.com/aadhar-efficientai/30min)

</div>

---

## ✨ What EfficientAI Does

- ✅ **Voice AI Evaluation**: Test your voice AI agents with comprehensive evaluation metrics
- ✅ **Persona Creation**: Design diverse voice personas with unique characteristics and behaviors
- ✅ **Scenario Building**: Create comprehensive conversation flows and dialogue trees
- ✅ **Automated Testing**: Execute tests automatically across all your voice agents
- ✅ **Real-time Insights**: Get real-time insights on latency, accuracy, and quality metrics
- ✅ **Batch Processing**: Process multiple audio files and evaluations efficiently
- ✅ **Modern Web Interface**: Beautiful React-based UI for managing evaluations

**Quick Navigation:** [Quick Start](#-quick-start) • [CLI Commands](#-cli-commands) • [Development](#-development)

---

## 🚀 Quick Start

There are two ways to run the application:

### Method 1: Using Docker Compose

1. **Start all services**
   ```bash
   docker compose up -d
   ```
   
   This will automatically:
   - Build Docker images if they don't exist
   - Build the frontend during the Docker build process
   - Start all services (database, Redis, API, worker)
   - Run database migrations automatically on startup
   
   **Note:** If you make changes to the frontend or backend code, you may need to rebuild:
   ```bash
   # Rebuild and restart (forces rebuild even if image exists)
   docker compose up -d --build
   
   # Or rebuild without cache for a clean build
   docker compose build --no-cache api
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
   
   **Note:** The frontend is automatically built into the Docker image during the first `docker compose up -d` command. If you make frontend changes later, rebuild with:
   ```bash
   docker compose up -d --build
   ```

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
   - **Run database migrations** (ensures schema is up to date)
   - Build the frontend (if needed)
   - Start the API server
   - Serve both API and frontend from the same server
   
   **Important:** Migrations run automatically before startup. If migrations fail, the app won't start.

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

### Prerequisites

**For Docker Compose:**
- Docker and Docker Compose installed

**For CLI:**
- Python 3.11+
- Node.js 18+ and npm
- PostgreSQL running (locally or remote)
- Redis running (locally or remote)

---

## 💻 CLI Commands

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

---

## ⚙️ Configuration

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

---

## 🗄️ Database Migrations

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

**Automatic (Recommended - Default Behavior):**
- ✅ Migrations run **automatically** when you start the app with `eai start`
- ✅ Migrations also run automatically when the application starts (via lifespan handler)
- ✅ **If migrations fail, the application will NOT start** - this ensures database consistency
- ✅ API requests are **blocked** if migrations are pending
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

### Creating New Migrations

1. Create a new file in `migrations/` directory with the next sequential number
2. Follow the format shown above
3. Test the migration on a development database first
4. Use `IF NOT EXISTS` checks for idempotent operations

See `migrations/README.md` for detailed documentation.

---

## 🛠️ Development

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

---

## 🔧 Troubleshooting

### Database Migration Issues

**Problem:** After cloning the repository, you see errors like:
```
psycopg2.errors.UndefinedColumn: column "organization_id" of relation "api_keys" does not exist
```

**Cause:** The database schema is out of sync with the code. This happens when:
- The database was created before migrations were added
- Migrations failed to run on startup
- The database was created using an older version of the code

**Solution:**

1. **Check migration status:**
   ```bash
   python scripts/check_migrations.py
   ```
   This will show which migrations have been applied and identify any schema issues.

2. **Run migrations manually:**
   ```bash
   # Using CLI (recommended)
   eai migrate --verbose
   
   # Or using Python directly
   python -c "from app.core.migrations import run_migrations; run_migrations()"
   ```

3. **If you're using a fresh database (just created/nuked):**
   - The migration system now handles fresh databases correctly
   - If tables don't exist, migrations will skip them and `init_db()` will create them with the correct schema
   - However, if you see this error on a fresh DB, try:
     ```bash
     # Stop the application
     # Then run migrations explicitly
     eai migrate --verbose
     # Then start the application again
     eai start
     ```

4. **If migrations still fail:**
   - Ensure your database connection is correct in `config.yml` or `.env`
   - Check that you have the necessary permissions on the database
   - Review the migration logs for specific errors
   - You may need to manually add missing columns (see migration files in `migrations/` directory)
   - **For fresh databases**: Make sure migrations run BEFORE any tables are created

5. **For Docker setups:**
   ```bash
   docker compose exec api eai migrate --verbose
   ```
   
   **Important for Docker**: If you nuked the DB container and created a new one:
   - The new container starts with an empty database
   - Migrations should run automatically on startup
   - If they don't, run them manually as shown above

**Prevention:** Always ensure migrations run successfully before using the application. Check the startup logs for migration status messages.

---

## 📞 Support

- 📧 **Email**: [tejas@efficientai.cloud](mailto:tejas@efficientai.cloud)
- 📅 **Book a Demo**: [Schedule a call](https://calendly.com/aadhar-efficientai/30min)
- 💬 **LinkedIn**: [Connect with us](https://www.linkedin.com/company/efficientaicloud)
- 🐦 **X (Twitter)**: [Follow us](https://x.com/AiEfficient)
- 💻 **GitHub**: [View on GitHub](https://github.com/EfficientAI-tech/efficientAI)

---

## 📄 License

MIT License - see LICENSE file for details
