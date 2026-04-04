"""
Per-organization logging middleware for multi-tenant Loki.

When LOKI_MULTI_TENANT is enabled, this middleware captures request metadata
for authenticated API calls and pushes structured log entries to Loki with
the X-Scope-OrgID header set to the request's organization UUID.

This is Layer 2 of the observability stack. Layer 1 (Docker log driver)
always runs as a safety net regardless of this middleware's state.
"""

import time
import json
import logging
from uuid import UUID
from typing import Optional

import httpx
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import get_db
from app.core.security import get_api_key_organization_id

logger = logging.getLogger(__name__)

_http_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=5.0)
    return _http_client


def _extract_org_id(request: Request) -> Optional[UUID]:
    """Extract organization ID from the request's API key header."""
    api_key = request.headers.get("X-API-Key") or request.headers.get("X-EFFICIENTAI-API-KEY")
    if not api_key:
        return None

    db = next(get_db())
    try:
        return get_api_key_organization_id(api_key, db)
    except Exception:
        return None
    finally:
        db.close()


class OrgLoggingMiddleware(BaseHTTPMiddleware):
    """
    Pushes per-request structured logs to Loki with the organization's
    tenant ID. No-op for unauthenticated requests or when multi-tenant
    mode is disabled.
    """

    SKIP_PATHS = ["/health", "/metrics", "/docs", "/redoc", "/openapi.json", "/assets/"]

    async def dispatch(self, request: Request, call_next):
        if not settings.LOKI_MULTI_TENANT:
            return await call_next(request)

        if any(request.url.path.startswith(p) for p in self.SKIP_PATHS):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 2)

        org_id = _extract_org_id(request)
        if org_id is None:
            return response

        try:
            await self._push_to_loki(request, response, org_id, duration_ms)
        except Exception as e:
            logger.warning(f"Failed to push org log to Loki: {e}")

        return response

    async def _push_to_loki(
        self,
        request: Request,
        response,
        org_id: UUID,
        duration_ms: float,
    ):
        ts_ns = str(int(time.time() * 1e9))

        log_line = json.dumps({
            "timestamp": ts_ns,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "organization_id": str(org_id),
            "client_host": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", ""),
        })

        payload = {
            "streams": [
                {
                    "stream": {
                        "service": "api",
                        "organization_id": str(org_id),
                        "level": "error" if response.status_code >= 500 else "info",
                    },
                    "values": [[ts_ns, log_line]],
                }
            ]
        }

        loki_url = f"{settings.LOKI_URL}/loki/api/v1/push"
        headers = {
            "Content-Type": "application/json",
            "X-Scope-OrgID": str(org_id),
        }

        client = _get_client()
        resp = await client.post(loki_url, json=payload, headers=headers)
        if resp.status_code not in (200, 204):
            logger.warning(f"Loki push returned {resp.status_code}: {resp.text[:200]}")
