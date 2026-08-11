"""Clear LLM usage ContextVar at request boundaries to avoid thread reuse leaks."""

from __future__ import annotations

from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.services.usage.context import (
    infer_product_section_from_path,
    reset_usage_context,
    reset_usage_hints,
    set_usage_context,
    set_usage_hints,
)


class LLMUsageContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        section = infer_product_section_from_path(request.url.path)
        request.state.usage_product_section = section

        workspace_hint = None
        raw_ws = request.headers.get("x-workspace-id") or request.query_params.get(
            "workspace_id"
        )
        if raw_ws:
            try:
                workspace_hint = UUID(raw_ws)
            except (TypeError, ValueError):
                workspace_hint = None

        ctx_token = set_usage_context(None)
        hint_tokens = set_usage_hints(
            workspace_id=workspace_hint,
            product_section=section,
        )
        try:
            return await call_next(request)
        finally:
            reset_usage_hints(hint_tokens)
            reset_usage_context(ctx_token)
