# Voice AI Evaluation Platform

A containerized voice AI evaluation platform built with Python (uv), FastAPI, and Docker. The platform supports audio file uploads, evaluation processing with multiple metrics, and comprehensive results management.

## Features

- **Audio File Management**: Upload, store, and manage audio files (WAV, MP3, FLAC, M4A)
- **ASR Evaluation**: Evaluate Automatic Speech Recognition models with metrics like WER, CER, latency
- **Batch Processing**: Process multiple audio files in parallel
- **Results Management**: Store, retrieve, and compare evaluation results
- **RESTful API**: Comprehensive REST API with OpenAPI documentation
- **Async Processing**: Celery-based async task processing for long-running evaluations
- **Containerized**: Fully containerized with Docker Compose

## Tech Stack

- **Package Manager**: uv (Python)
- **Framework**: FastAPI
- **Containerization**: Docker & Docker Compose
- **Database**: PostgreSQL (with SQLAlchemy ORM)
- **File Storage**: Local filesystem (extensible to S3)
- **Authentication**: API Key based
- **Audio Processing**: librosa, whisper
- **Task Queue**: Celery + Redis (for async batch processing)

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- (Optional) uv installed locally for development

### Setup

1. **Clone the repository**

```bash
git clone <repository-url>
cd efficientAI
```

2. **Configure environment variables**

Create a `.env` file in the root directory (see `.env.example` for reference):

```env
DATABASE_URL=postgresql://efficientai:password@db:5432/efficientai
POSTGRES_USER=efficientai
POSTGRES_PASSWORD=password
POSTGRES_DB=efficientai
REDIS_URL=redis://redis:6379/0
SECRET_KEY=your-secret-key-here
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
UPLOAD_DIR=/app/uploads
```

3. **Start services**

```bash
docker compose up -d
```

Or if using older Docker Compose:
```bash
docker-compose up -d
```

This will start:
- PostgreSQL database (port 5432)
- Redis (port 6379)
- FastAPI application (port 8000)
- Celery worker

4. **Initialize database**

```bash
docker compose exec api python scripts/init_db.py
```

5. **Create an API key**

```bash
docker compose exec api python scripts/create_api_key.py "My API Key"
```

The script will output an API key that you can use for authentication.

6. **Access the API**

- API Documentation: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health Check: http://localhost:8000/health

## API Usage

### Authentication

All API endpoints (except `/health` and `/`) require authentication via API key. Include the API key in the request header:

```
X-API-Key: your-api-key-here
```

### Example Workflow

1. **Upload an audio file**

```bash
curl -X POST "http://localhost:8000/api/v1/audio/upload" \
  -H "X-API-Key: your-api-key" \
  -F "file=@audio.wav"
```

2. **Create an evaluation**

```bash
curl -X POST "http://localhost:8000/api/v1/evaluations/create" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "audio_id": "audio-uuid-here",
    "evaluation_type": "asr",
    "model_name": "base",
    "metrics": ["wer", "latency", "rtf"],
    "reference_text": "optional reference text for WER calculation"
  }'
```

3. **Check evaluation status**

```bash
curl -X GET "http://localhost:8000/api/v1/evaluations/{evaluation_id}" \
  -H "X-API-Key: your-api-key"
```

4. **Get results**

```bash
curl -X GET "http://localhost:8000/api/v1/results/{evaluation_id}" \
  -H "X-API-Key: your-api-key"
```

## API Endpoints

### Authentication
- `POST /api/v1/auth/generate-key` - Generate API key
- `POST /api/v1/auth/validate` - Validate API key

### Audio Management
- `POST /api/v1/audio/upload` - Upload audio file
- `GET /api/v1/audio/{audio_id}` - Get audio metadata
- `GET /api/v1/audio/{audio_id}/download` - Download audio file
- `DELETE /api/v1/audio/{audio_id}` - Delete audio file
- `GET /api/v1/audio` - List audio files (paginated)

### Evaluations
- `POST /api/v1/evaluations/create` - Create evaluation job
- `GET /api/v1/evaluations/{evaluation_id}` - Get evaluation details
- `GET /api/v1/evaluations` - List evaluations (filtered, paginated)
- `POST /api/v1/evaluations/{evaluation_id}/cancel` - Cancel pending evaluation
- `DELETE /api/v1/evaluations/{evaluation_id}` - Delete evaluation

### Results
- `GET /api/v1/results/{evaluation_id}` - Get detailed results
- `GET /api/v1/results/{evaluation_id}/metrics` - Get metrics breakdown
- `GET /api/v1/results/{evaluation_id}/transcript` - Get transcription
- `POST /api/v1/results/compare` - Compare multiple evaluations

### Batch Processing
- `POST /api/v1/batch/create` - Create batch evaluation job
- `GET /api/v1/batch/{batch_id}` - Get batch status
- `GET /api/v1/batch/{batch_id}/results` - Get batch results summary
- `POST /api/v1/batch/{batch_id}/export` - Export results as CSV/JSON

## Evaluation Metrics

The platform supports the following evaluation metrics:

- **WER (Word Error Rate)**: Percentage of word errors in transcription (requires reference text)
- **CER (Character Error Rate)**: Percentage of character errors in transcription (requires reference text)
- **Latency**: Processing time in milliseconds
- **RTF (Real-Time Factor)**: Processing time relative to audio duration
- **Quality Score**: Placeholder for quality metrics

## Development

### Local Development Setup

1. **Install uv** (if not using Docker)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. **Install dependencies**

```bash
uv pip install -e .
```

3. **Run services locally**

```bash
# Start PostgreSQL and Redis
docker-compose up -d db redis

# Run FastAPI
uvicorn app.main:app --reload

# Run Celery worker (in separate terminal)
celery -A app.workers.celery_app worker --loglevel=info
```

### Project Structure

```
efficientAI/
├── app/
│   ├── api/v1/routes/     # API route handlers
│   ├── models/            # Database models and schemas
│   ├── services/          # Business logic services
│   ├── core/              # Core utilities (security, exceptions)
│   ├── workers/           # Celery task definitions
│   ├── main.py           # FastAPI application
│   └── config.py         # Configuration
├── docker/                # Dockerfiles
├── scripts/               # Utility scripts
└── tests/                 # Test files
```

## Configuration

Configuration is managed through environment variables (see `.env.example`). Key settings:

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `UPLOAD_DIR`: Directory for uploaded audio files
- `MAX_FILE_SIZE_MB`: Maximum file size in MB
- `ALLOWED_AUDIO_FORMATS`: Comma-separated list of allowed formats

## Troubleshooting

### Docker Daemon Connection Issues

If you see an error like "Cannot connect to the Docker daemon at unix:///var/run/docker.sock":

1. **Check Docker is running:**
   ```bash
   docker ps
   ```

2. **If Docker Desktop is not running (Windows/WSL):**
   - Start Docker Desktop
   - Wait for it to fully initialize
   - Verify with `docker ps`

3. **If using WSL, ensure Docker Desktop integration is enabled:**
   - Open Docker Desktop Settings
   - Go to Resources → WSL Integration
   - Enable integration for your WSL distribution

4. **Try the command again:**
   ```bash
   docker compose up -d
   ```

### Port Already in Use

If you see port conflicts (e.g., port 5432 or 8000 already in use):

- Check what's using the port:
  ```bash
  # For Linux/WSL
  sudo lsof -i :8000
  # or
  sudo netstat -tulpn | grep :8000
  ```

- Stop conflicting services or change ports in `docker-compose.yml`

### Database Connection Issues

If the API can't connect to the database:

- Ensure the database container is healthy:
  ```bash
  docker compose ps
  ```

- Check database logs:
  ```bash
  docker compose logs db
  ```

- Verify the `DATABASE_URL` in your `.env` file matches the docker-compose configuration

## Production Deployment

For production deployment:

1. Set strong `SECRET_KEY`
2. Configure proper CORS origins
3. Use external PostgreSQL and Redis instances
4. Consider using S3 or similar for file storage
5. Set up proper logging and monitoring
6. Configure rate limiting
7. Use HTTPS

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
