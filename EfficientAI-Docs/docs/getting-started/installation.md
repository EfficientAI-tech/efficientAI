---
id: installation
title: Installation
sidebar_position: 1
---

# 🚀 Quick Start

There are two ways to run the application:

## Method 1: Using Docker Compose

Start all services:

```bash
docker compose up -d
```

This will automatically:

- Build Docker images if they don't exist
- Build the frontend during the Docker build process
- Start all services (database, Redis, API, worker)
- Run database migrations automatically on startup

**Note**: If you make changes to the frontend or backend code, you may need to rebuild:

```bash
# Rebuild and restart (forces rebuild even if image exists)
docker compose up -d --build

# Or rebuild without cache for a clean build
docker compose build --no-cache api
docker compose up -d
```

### Initialize database

Migrations run automatically on startup, but you can also run manually:

```bash
# Option 1: Let migrations run automatically on startup
# (No action needed - migrations run when the app starts)

# Option 2: Run migrations manually before starting
docker compose exec api eai migrate
```

### Create an API key

```bash
docker compose exec api python scripts/create_api_key.py "My API Key"
```

### Access the application

- Frontend: http://localhost:8000/
- API Docs: http://localhost:8000/docs

**Note**: The frontend is automatically built into the Docker image during the first `docker compose up -d` command. If you make frontend changes later, rebuild with:

```bash
docker compose up -d --build
```

## Method 2: Using Command Line (CLI)

### Install the package

```bash
pip install -e .
```

### Generate configuration file

```bash
eai init-config
```

Edit `config.yml` with your settings:

```yaml
# EfficientAI Configuration File

# Application Settings
app:
  name: "Voice AI Evaluation Platform"
  version: "0.1.0"
  debug: true  # Set to false in production
  secret_key: "your-secret-key-here-change-in-production"

# Server Settings
server:
  host: "0.0.0.0"
  port: 8000

# Database Configuration (Required)
database:
  url: "postgresql://efficientai:password@localhost:5432/efficientai"

# Redis Configuration (Required)
redis:
  url: "redis://localhost:6379/0"

# Celery Configuration
celery:
  broker_url: "redis://localhost:6379/0"
  result_backend: "redis://localhost:6379/0"

# File Storage
storage:
  upload_dir: "./uploads"
  max_file_size_mb: 500
  allowed_audio_formats:
    - "wav"
    - "mp3"
    - "flac"
    - "m4a"

# S3 Configuration (Optional - for cloud audio storage)
s3:
  enabled: false
  bucket_name: "your-s3-bucket-name"
  region: "us-east-1"
  access_key_id: "your-access-key-id"
  secret_access_key: "your-secret-access-key"
  endpoint_url: null  # For S3-compatible services (MinIO, DigitalOcean Spaces)
  prefix: "audio/"

# CORS Settings
cors:
  origins:
    - "http://localhost:3000"
    - "http://localhost:8000"

# API Settings
api:
  prefix: "/api/v1"
  key_header: "X-API-Key"
  rate_limit_per_minute: 60
```

> **Important**: Make sure to change `secret_key` to a secure random value in production!

### Start the application and worker

**Option A: Start both together (Recommended)**

```bash
eai start-all --config config.yml
```

This single command will:

- Start the API server
- Start the Celery worker (for background task processing)
- Run database migrations automatically
- Build the frontend (if needed)

Press `Ctrl+C` to stop both services together.

**Option B: Start separately (for advanced use)**

In one terminal, start the application:

```bash
eai start --config config.yml
```

In another terminal, start the Celery worker:

```bash
eai worker --config config.yml
```

Or use the Celery command directly:

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

The application will automatically:

- Run database migrations (ensures schema is up to date)
- Build the frontend (if needed)
- Start the API server
- Serve both API and frontend from the same server

**Important**: Migrations run automatically before startup. If migrations fail, the app won't start.

### For development with hot reload

```bash
# Enable auto-rebuild of frontend on file changes
eai start-all --config config.yml --watch-frontend
```

This will:

- Automatically rebuild the frontend when source files change
- Keep the backend hot-reload enabled (by default)
- Perfect for active frontend development

### Access the application

- Frontend: http://localhost:8000/
- API Docs: http://localhost:8000/docs

## Prerequisites

**For Docker Compose**:
- Docker and Docker Compose installed

**For CLI**:
- Python 3.11+
- Node.js 18+ and npm
- PostgreSQL running (locally or remote)
- Redis running (locally or remote)
