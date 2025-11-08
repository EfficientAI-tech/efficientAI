"""FastAPI application entry point."""

import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import settings
from app.api.v1.api import api_router
from app.database import init_db
from app.core.migrations import run_migrations, ensure_migrations_directory

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="EfficientAI Voice AI Evaluation Platform API",
    docs_url="/docs",
    redoc_url="/redoc",
)

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


@app.on_event("startup")
async def startup_event():
    """Initialize database and run migrations on startup."""
    # Try to load config.yml if it exists (in case server wasn't started with eai start)
    from app.config import load_config_from_file
    from pathlib import Path
    
    config_path = Path("config.yml")
    if config_path.exists():
        try:
            load_config_from_file(str(config_path))
            print(f"✅ Loaded configuration from {config_path}")
        except Exception as e:
            print(f"⚠️  Warning: Could not load config.yml: {e}")
    
    # Ensure migrations directory exists
    ensure_migrations_directory()
    
    # Run database migrations
    run_migrations()
    
    # Initialize database (creates tables if they don't exist)
    init_db()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

