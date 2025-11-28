"""
Middleware to ensure migrations are up to date before serving requests.
Blocks API requests if migrations are pending.
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.migrations import check_migrations_status
import logging

logger = logging.getLogger(__name__)

# Global flag to track if migrations have been checked on startup
_migrations_checked = False
_migrations_up_to_date = False


class MigrationCheckMiddleware(BaseHTTPMiddleware):
    """
    Middleware that blocks API requests if database migrations are pending.
    Allows health checks and migration-related endpoints to pass through.
    """
    
    # Endpoints that should be allowed even if migrations are pending
    ALLOWED_PATHS = [
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]
    
    async def dispatch(self, request: Request, call_next):
        # Allow health checks and docs
        if any(request.url.path.startswith(path) for path in self.ALLOWED_PATHS):
            return await call_next(request)
        
        # Allow static assets (frontend)
        if request.url.path.startswith("/assets/"):
            return await call_next(request)
        
        # Check migration status
        is_up_to_date, pending = check_migrations_status()
        
        if not is_up_to_date:
            # Block API requests if migrations are pending
            if request.url.path.startswith("/api/"):
                logger.warning(
                    f"Blocked API request to {request.url.path} - {len(pending)} migration(s) pending: {', '.join(pending)}"
                )
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "detail": "Database migrations are pending. Please wait for migrations to complete.",
                        "pending_migrations": pending,
                        "message": f"Application is starting up. {len(pending)} migration(s) need to be applied: {', '.join(pending)}"
                    }
                )
        
        return await call_next(request)

