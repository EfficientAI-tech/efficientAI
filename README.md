# Voice AI Evaluation Platform

A voice AI evaluation platform built with FastAPI and React. Supports audio file uploads, evaluation processing with multiple metrics, batch processing, and a modern web interface.

## Quick Start

There are two ways to run the application:

### Method 1: Using Docker Compose

1. **Start all services**
   ```bash
   docker compose up -d
   ```

2. **Initialize database**
   ```bash
   docker compose exec api python scripts/init_db.py
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

# Start without building frontend (if already built)
eai start --no-build-frontend

# Start without auto-reload (production mode)
eai start --no-reload --no-build-frontend
```

### Generate Config File
```bash
# Generate default config.yml
eai init-config

# Generate custom config file
eai init-config --output my-config.yml
```

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

## Development

### Running Locally

1. **Start PostgreSQL and Redis**
   ```bash
   docker compose up -d db redis
   ```

2. **Run the application**
   ```bash
   eai start --config config.yml --reload
   ```

3. **Run Celery worker** (in separate terminal)
   ```bash
   celery -A app.workers.celery_app worker --loglevel=info
   ```

### Frontend Development

```bash
cd frontend
npm install
npm run dev
```

## License

MIT License - see LICENSE file for details
