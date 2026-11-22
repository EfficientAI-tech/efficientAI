"""MCP server for the copilot's tools (Streamable HTTP, stateless, JSON responses).

Point an MCP client (Claude, Cursor, a customer's agent) at
``POST /api/v1/copilot/mcp`` with a user-bound API key (``X-API-Key``) and an
``X-Workspace-Id`` header. It exposes exactly the tools the in-app assistant
has, through the same registry, permissions and workspace scoping.

Write tools only *propose*: the change waits in the user's "MCP" conversation
in the app until they confirm it there. No MCP client can change data on its own.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.dependencies import WorkspaceContext, get_db, get_workspace_context
from app.models.database import CopilotSession
from app.services.copilot import redis_state, store
from app.services.copilot.readiness import check_readiness
from app.services.copilot.registry import (
    LLMChoice,
    ToolContext,
    available_tools,
    execute,
    mcp_definition,
)

router = APIRouter(prefix="/copilot", tags=["copilot"])

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
MCP_SESSION_TITLE = "Requests from MCP clients"
_NO_LLM = LLMChoice(provider=None, model="", credential_id=None)


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_session(db: Session, ctx: WorkspaceContext, user_id: UUID) -> CopilotSession:
    """Proposals from MCP land in one conversation per user and workspace, where they confirm them."""
    row = (
        db.query(CopilotSession)
        .filter(
            CopilotSession.user_id == user_id,
            CopilotSession.workspace_id == ctx.workspace_id,
            CopilotSession.status == "active",
            CopilotSession.title == MCP_SESSION_TITLE,
        )
        .first()
    )
    return row or store.create_session(
        db,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        user_id=user_id,
        title=MCP_SESSION_TITLE,
    )


def _call_tool(db: Session, ctx: WorkspaceContext, user_id: UUID, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str):
        raise ValueError("params.name is required")
    limit = redis_state.check_message_rate(user_id, ctx.organization_id)
    if not limit.allowed:
        return {
            "content": [{"type": "text", "text": f"Rate limited. Retry in {limit.retry_after_seconds}s."}],
            "isError": True,
        }
    readiness = check_readiness(db, ctx.organization_id)
    session_row = _mcp_session(db, ctx, user_id)
    tool_ctx = ToolContext(
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        user_id=user_id,
        capabilities=ctx.capabilities,
        timezone=str(params.get("_meta", {}).get("timezone") or "UTC") if isinstance(params.get("_meta"), dict) else "UTC",
        session_id=session_row.id,
        llm=readiness.llm or _NO_LLM,
    )
    db.rollback()  # release the connection; tools open their own sessions
    outcome = execute(tool_ctx, name, params.get("arguments") or {})
    text = outcome.content
    if outcome.ui and outcome.ui.get("type") == "proposal":
        text += (
            "\n\nThe user must confirm this in the EfficientAI app "
            f"(assistant conversation \"{MCP_SESSION_TITLE}\") before anything changes."
        )
    return {"content": [{"type": "text", "text": text}], "isError": outcome.status != "ok"}


def _handle(db: Session, ctx: WorkspaceContext, user_id: UUID, message: Any) -> Optional[dict[str, Any]]:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
    request_id = message.get("id")
    method = message["method"]
    params = message.get("params") or {}
    if request_id is None:  # notification, e.g. notifications/initialized
        return None
    try:
        if method == "initialize":
            requested = params.get("protocolVersion")
            return _rpc_result(request_id, {
                "protocolVersion": requested if requested in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "efficientai-copilot", "version": "1.0.0"},
                "instructions": (
                    "Tools read and change data in one EfficientAI workspace. Changes are proposals the "
                    "user confirms in the app."
                ),
            })
        if method == "ping":
            return _rpc_result(request_id, {})
        if method == "tools/list":
            return _rpc_result(request_id, {
                "tools": [mcp_definition(t) for t in available_tools(ctx.capabilities)],
            })
        if method == "tools/call":
            return _rpc_result(request_id, _call_tool(db, ctx, user_id, params))
        return _rpc_error(request_id, -32601, f"Method not found: {method}")
    except ValueError as exc:
        return _rpc_error(request_id, -32602, str(exc))


@router.post("/mcp", operation_id="copilotMcp")
async def mcp_endpoint(
    request: Request,
    principal: Principal = Depends(get_principal),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db: Session = Depends(get_db),
):
    if principal.user_id is None:
        raise HTTPException(status_code=403, detail="Use an API key that belongs to a user.")
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)

    def run() -> Any:
        if isinstance(body, list):
            replies = [r for r in (_handle(db, ctx, principal.user_id, m) for m in body) if r is not None]
            return replies or None
        return _handle(db, ctx, principal.user_id, body)

    reply = await run_in_threadpool(run)
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply)


@router.get("/mcp", include_in_schema=False)
def mcp_no_stream():
    # Stateless server: no server-initiated stream. Clients fall back to POST only.
    return Response(status_code=405, headers={"Allow": "POST"})
