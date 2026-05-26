"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_config_from_file, settings
from app.core.migration_middleware import MigrationCheckMiddleware
from app.core.migrations import check_migrations_status, ensure_migrations_directory, run_migrations
from app.core.rbac_middleware import ReaderReadOnlyMiddleware
from app.database import init_db

logger = logging.getLogger(__name__)


def _load_default_config_if_present() -> None:
    """Load config.yml before app construction for direct uvicorn runs."""
    config_path = Path("config.yml")
    if config_path.exists():
        try:
            load_config_from_file(str(config_path))
            logger.info(f"Loaded configuration from {config_path}")
        except Exception as e:
            logger.warning(f"Warning: Could not load config.yml: {e}")


_load_default_config_if_present()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI.
    Ensures migrations run before the app starts serving requests.
    """
    logger.info("=" * 60)
    logger.info("Starting EfficientAI Application")
    logger.info("=" * 60)

    ensure_migrations_directory()

    try:
        init_db()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

    try:
        run_migrations()
    except Exception as e:
        logger.error("=" * 60)
        logger.error("CRITICAL: Database migrations failed!")
        logger.error("=" * 60)
        logger.error("The application cannot start without successful migrations.")
        logger.error(f"Error: {e}")
        logger.error("")
        logger.error("Please fix the migration errors and try again.")
        logger.error("You can run migrations manually with: eai migrate --verbose")
        raise

    is_up_to_date, pending = check_migrations_status()
    if not is_up_to_date:
        logger.warning(
            f"Warning: {len(pending)} migration(s) still pending after startup: "
            f"{', '.join(pending)}"
        )
    else:
        logger.info("All migrations are up to date")

    logger.info("=" * 60)
    logger.info("Application startup complete - Ready to serve requests")
    logger.info("=" * 60)

    yield

    logger.info("Shutting down EfficientAI Application...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="EfficientAI Voice AI Evaluation Platform API",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(MigrationCheckMiddleware)
    app.add_middleware(ReaderReadOnlyMiddleware)

    if settings.OBSERVABILITY_ENABLED and settings.LOKI_ENABLED and settings.LOKI_MULTI_TENANT:
        from app.core.observability_middleware import OrgLoggingMiddleware

        app.add_middleware(OrgLoggingMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.OBSERVABILITY_ENABLED:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_group_untemplated=True,
            excluded_handlers=["/health", "/metrics"],
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    from app.api.v1.api import api_router

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health")
    async def health_check():
        """
        Health check endpoint.
        Returns migration status to help diagnose issues.
        """
        is_up_to_date, pending = check_migrations_status()

        if is_up_to_date:
            return {"status": "healthy", "migrations": "up_to_date"}
        return {
            "status": "degraded",
            "migrations": "pending",
            "pending_migrations": pending,
            "message": f"{len(pending)} migration(s) pending: {', '.join(pending)}",
        }

    frontend_dist = Path(settings.FRONTEND_DIR)
    if frontend_dist.exists() and frontend_dist.is_dir():
        static_dir = frontend_dist / "assets"
        if static_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")

        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str, request: Request):
            """Serve frontend for all non-API routes."""
            if (
                full_path.startswith("api/")
                or full_path.startswith("docs")
                or full_path.startswith("redoc")
                or full_path.startswith("assets/")
                or full_path == "health"
                or full_path == "metrics"
            ):
                return {"detail": "Not found"}

            file_path = frontend_dist / full_path
            if file_path.exists() and file_path.is_file() and file_path.parent == frontend_dist:
                return FileResponse(str(file_path))

            index_path = frontend_dist / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"detail": "Frontend not found"}

    return app


app = create_app()
