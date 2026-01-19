"""FastAPI application entry point."""

import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import settings
from app.api.v1.api import api_router
from app.database import init_db
from app.core.migrations import run_migrations, ensure_migrations_directory, check_migrations_status
from app.core.migration_middleware import MigrationCheckMiddleware
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI.
    Ensures migrations run before the app starts serving requests.
    """
    # Startup: Run migrations
    logger.info("=" * 60)
    logger.info("🚀 Starting EfficientAI Application")
    logger.info("=" * 60)
    
    # Try to load config.yml if it exists (in case server wasn't started with eai start)
    from app.config import load_config_from_file
    config_path = Path("config.yml")
    if config_path.exists():
        try:
            load_config_from_file(str(config_path))
            logger.info(f"✅ Loaded configuration from {config_path}")
        except Exception as e:
            logger.warning(f"⚠️  Warning: Could not load config.yml: {e}")
    
    # Ensure migrations directory exists
    ensure_migrations_directory()
    
    # Initialize database FIRST (creates tables if they don't exist)
    # This must happen before migrations since migrations modify existing tables
    try:
        init_db()
        logger.info("✅ Database tables initialized")
    except Exception as e:
        logger.error(f"❌ Error initializing database: {e}")
        raise
    
    # Run database migrations (this will raise if they fail)
    try:
        run_migrations()
    except Exception as e:
        logger.error("=" * 60)
        logger.error("❌ CRITICAL: Database migrations failed!")
        logger.error("=" * 60)
        logger.error("The application cannot start without successful migrations.")
        logger.error(f"Error: {e}")
        logger.error("")
        logger.error("Please fix the migration errors and try again.")
        logger.error("You can run migrations manually with: eai migrate --verbose")
        raise  # Re-raise to prevent app from starting
    
    # Verify migrations are up to date
    is_up_to_date, pending = check_migrations_status()
    if not is_up_to_date:
        logger.warning(f"⚠️  Warning: {len(pending)} migration(s) still pending after startup: {', '.join(pending)}")
    else:
        logger.info("✅ All migrations are up to date")
    
    logger.info("=" * 60)
    logger.info("✅ Application startup complete - Ready to serve requests")
    logger.info("=" * 60)
    
    yield  # Application is running
    
    # Shutdown: Cleanup (if needed)
    logger.info("Shutting down EfficientAI Application...")


# Create FastAPI app with lifespan
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="EfficientAI Voice AI Evaluation Platform API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add migration check middleware FIRST (before CORS)
# This ensures API requests are blocked if migrations are pending
app.add_middleware(MigrationCheckMiddleware)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router (must be before frontend routes)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Serve static frontend files if dist directory exists
frontend_dist = Path(settings.FRONTEND_DIR)
if frontend_dist.exists() and frontend_dist.is_dir():
    # Mount static files (JS, CSS, images, etc.) from assets directory
    static_dir = frontend_dist / "assets"
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")
    
    # Serve index.html for all non-API routes (must be last to catch all routes)
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str, request: Request):
        """Serve frontend for all non-API routes."""
        # Don't serve frontend for API routes, docs, health, or static assets
        if (
            full_path.startswith("api/") 
            or full_path.startswith("docs") 
            or full_path.startswith("redoc")
            or full_path.startswith("assets/")
            or full_path == "health"
        ):
            return {"detail": "Not found"}
        
        # Check if it's a static file request (like favicon, robots.txt, etc.)
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file() and file_path.parent == frontend_dist:
            return FileResponse(str(file_path))
        
        # Otherwise serve index.html for SPA routing
        index_path = frontend_dist / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"detail": "Frontend not found"}


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    Returns migration status to help diagnose issues.
    """
    is_up_to_date, pending = check_migrations_status()
    
    if is_up_to_date:
        return {
            "status": "healthy",
            "migrations": "up_to_date"
        }
    else:
        return {
            "status": "degraded",
            "migrations": "pending",
            "pending_migrations": pending,
            "message": f"{len(pending)} migration(s) pending: {', '.join(pending)}"
        }

