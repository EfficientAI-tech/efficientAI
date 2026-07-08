"""Application factory for API and media service modes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings, validate_auth_configuration
from app.core.auth.rbac import require_admin
from app.core.health import build_health_status
from app.core.migration_middleware import MigrationCheckMiddleware
from app.core.migrations import check_migrations_status, ensure_migrations_directory, run_migrations
from app.core.operational_access_middleware import OperationalAccessMiddleware
from app.core.rbac_middleware import ReaderReadOnlyMiddleware
from app.core.security_headers_middleware import SecurityHeadersMiddleware
from app.database import init_db

logger = logging.getLogger(__name__)


def _includes_http_routes() -> bool:
    return settings.SERVICE_MODE in ("api", "all")


def _includes_media_routes() -> bool:
    return settings.SERVICE_MODE in ("media", "all")


@asynccontextmanager
async def _api_lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("Starting EfficientAI Application (mode=%s)", settings.SERVICE_MODE)
    logger.info("=" * 60)

    ensure_migrations_directory()

    if _includes_http_routes():
        try:
            validate_auth_configuration()
            logger.info("Authentication configuration validated")
        except Exception as e:
            logger.error("CRITICAL: Authentication configuration is invalid: %s", e)
            raise

    try:
        init_db()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error("Error initializing database: %s", e)
        raise

    if _includes_http_routes():
        try:
            run_migrations()
        except Exception as e:
            logger.error("CRITICAL: Database migrations failed: %s", e)
            raise

        is_up_to_date, pending = check_migrations_status()
        if not is_up_to_date:
            logger.warning("Warning: %d migration(s) still pending: %s", len(pending), ", ".join(pending))
        else:
            logger.info("All migrations are up to date")

        from app.services.billing.flexprice_service import log_startup_status

        log_startup_status(component="api")

    logger.info("Application startup complete - Ready to serve requests")
    logger.info("=" * 60)
    yield
    logger.info("Shutting down EfficientAI Application...")


def _add_common_middleware(app: FastAPI) -> None:
    if _includes_http_routes():
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
    app.add_middleware(SecurityHeadersMiddleware)
    if _includes_http_routes():
        app.add_middleware(OperationalAccessMiddleware)

    if settings.OBSERVABILITY_ENABLED and _includes_http_routes():
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_group_untemplated=True,
            excluded_handlers=["/health", "/metrics"],
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


def _mount_frontend(app: FastAPI) -> None:
    if not _includes_http_routes():
        return

    frontend_dist = Path(settings.FRONTEND_DIR)
    if not frontend_dist.exists() or not frontend_dist.is_dir():
        return

    static_dir = frontend_dist / "assets"
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if (
            full_path.startswith("api/")
            or full_path.startswith("docs")
            or full_path.startswith("redoc")
            or full_path.startswith("assets/")
            or full_path == "health"
            or full_path == "health/detail"
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


def create_app() -> FastAPI:
    """Create API, media, or combined app based on SERVICE_MODE."""
    title_suffix = {
        "api": " API",
        "media": " Media",
        "all": "",
    }.get(settings.SERVICE_MODE, "")

    app = FastAPI(
        title=f"{settings.APP_NAME}{title_suffix}",
        version=settings.APP_VERSION,
        description="EfficientAI Voice AI Evaluation Platform",
        docs_url="/docs" if settings.DEBUG and _includes_http_routes() else None,
        redoc_url="/redoc" if settings.DEBUG and _includes_http_routes() else None,
        openapi_url="/openapi.json" if settings.DEBUG and _includes_http_routes() else None,
        lifespan=_api_lifespan,
    )

    _add_common_middleware(app)

    if _includes_http_routes():
        from app.api.v1.api import api_router

        app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    if _includes_media_routes():
        from app.api.v1.media import media_router

        app.include_router(media_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health")
    async def health_check():
        payload, status_code = build_health_status(detailed=False)
        return JSONResponse(content=payload, status_code=status_code)

    if _includes_http_routes():

        @app.get("/health/detail")
        async def health_detail(_admin=Depends(require_admin)):
            payload, status_code = build_health_status(detailed=True)
            return JSONResponse(content=payload, status_code=status_code)

    _mount_frontend(app)
    return app
