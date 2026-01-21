---
id: configuration
title: Configuration
sidebar_position: 2
---

# ⚙️ Configuration

## YAML Configuration (for CLI)

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

## Environment Variables (for Docker)

Create a `.env` file for Docker Compose:

```bash
DATABASE_URL=postgresql://efficientai:password@db:5432/efficientai
POSTGRES_USER=efficientai
POSTGRES_PASSWORD=password
POSTGRES_DB=efficientai
REDIS_URL=redis://redis:6379/0
SECRET_KEY=your-secret-key-here
```
