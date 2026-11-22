"""Copilot tool registry.

Each tool is defined once: a name, a description, a Pydantic argument model, the
workspace capability it needs, and a handler that calls the service layer. The
same definition renders as an OpenAI-style function (for the in-app chat) or an
MCP tool (for a later MCP server), so the two can never drift apart.

Handlers never receive organization or workspace ids from the model; they come
from ``ToolContext``, which is built from the authenticated request.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type
from uuid import UUID

from loguru import logger
from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal

SIDE_EFFECT_READ = "read"
SIDE_EFFECT_GENERATE = "generate"  # calls an LLM, returns a draft, saves nothing
SIDE_EFFECT_PROPOSE = "propose"  # records a proposal; changes happen only on user confirm

MAX_TOOL_RESULT_CHARS = 12_000
READ_STATEMENT_TIMEOUT_MS = 5_000


class ToolError(Exception):
    """A failure the model (and user) should see verbatim, e.g. 'agent not found'."""


@dataclass(frozen=True)
class LLMChoice:
    provider: Any  # ModelProvider
    model: str
    credential_id: Optional[UUID]


@dataclass(frozen=True)
class ToolContext:
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID
    capabilities: frozenset[str]
    timezone: str
    session_id: UUID
    llm: LLMChoice
    message_id: Optional[UUID] = None  # the assistant reply being produced


@dataclass
class ToolOutput:
    """``data`` goes to the model; ``ui`` (optional) is sent to the chat UI as a card."""

    data: dict[str, Any]
    ui: Optional[dict[str, Any]] = None


Handler = Callable[[ToolContext, Session, Any], "ToolOutput | dict[str, Any]"]


@dataclass(frozen=True)
class CopilotTool:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Handler
    capability: Optional[str] = None
    side_effect: str = SIDE_EFFECT_READ
    needs_db: bool = True  # False: don't check out a DB connection at all
    # Tool group for per-turn tool selection (see skills.py). "core" is always offered.
    group: str = "core"
    statement_timeout_ms: int = READ_STATEMENT_TIMEOUT_MS


@dataclass
class ToolExecution:
    status: str  # ok | error
    content: str  # JSON (or error text) returned to the model
    latency_ms: int
    ui: Optional[dict[str, Any]] = None
    error: Optional[str] = None


_REGISTRY: dict[str, CopilotTool] = {}
_loaded = False


def register(tool: CopilotTool) -> CopilotTool:
    if tool.name in _REGISTRY:
        raise ValueError(f"duplicate copilot tool {tool.name}")
    _REGISTRY[tool.name] = tool
    return tool


def _load_tools() -> None:
    # Importing the modules registers their tools. Guarded by a flag, not by
    # "registry is empty": importing one tool module directly must not stop
    # the others from loading.
    global _loaded
    if _loaded:
        return
    from app.services.copilot.tools import (  # noqa: F401
        activity,
        docs,
        imports,
        metrics,
        proposals,
        simulations,
        test_setup,
        workspace,
    )

    _loaded = True


def all_tools() -> list[CopilotTool]:
    _load_tools()
    return list(_REGISTRY.values())


def available_tools(capabilities: frozenset[str]) -> list[CopilotTool]:
    """Tools the caller may use. Tools they lack a capability for are never offered."""
    return [t for t in all_tools() if t.capability is None or t.capability in capabilities]


def get_tool(name: str) -> Optional[CopilotTool]:
    _load_tools()
    return _REGISTRY.get(name)


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def input_schema(tool: CopilotTool) -> dict[str, Any]:
    return _strip_titles(tool.args_model.model_json_schema())


def openai_definition(tool: CopilotTool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": input_schema(tool),
        },
    }


def mcp_definition(tool: CopilotTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": input_schema(tool),
        "annotations": {"readOnlyHint": tool.side_effect != SIDE_EFFECT_PROPOSE},
    }


def _limit_db(db: Session, tool: CopilotTool) -> None:
    """Cap read queries so one slow question can't tie up a catalog connection."""
    if tool.side_effect != SIDE_EFFECT_READ:
        return
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {int(tool.statement_timeout_ms)}"))


def _encode(data: dict[str, Any]) -> str:
    content = json.dumps(data, default=str, ensure_ascii=False)
    if len(content) > MAX_TOOL_RESULT_CHARS:
        content = (
            content[:MAX_TOOL_RESULT_CHARS]
            + '... [truncated: result too large; narrow the query or lower "limit"]'
        )
    return content


def execute(
    ctx: ToolContext,
    name: str,
    raw_arguments: Any,
    *,
    session_factory: Optional[Callable[[], Session]] = None,
) -> ToolExecution:
    started = time.monotonic()
    session_factory = session_factory or SessionLocal

    def done(status: str, content: str, *, ui=None, error=None) -> ToolExecution:
        return ToolExecution(
            status=status,
            content=content,
            latency_ms=int((time.monotonic() - started) * 1000),
            ui=ui,
            error=error,
        )

    tool = get_tool(name)
    if tool is None or (tool.capability and tool.capability not in ctx.capabilities):
        return done("error", f"Unknown tool {name!r}.", error="unknown_tool")

    if isinstance(raw_arguments, str):
        try:
            raw_arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            return done("error", f"Arguments were not valid JSON: {exc}", error="bad_arguments")
    try:
        args = tool.args_model.model_validate(raw_arguments or {})
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}"
            for err in exc.errors()
        )
        return done("error", f"Invalid arguments: {detail}", error="bad_arguments")

    db = session_factory() if tool.needs_db else None
    try:
        if db is not None:
            _limit_db(db, tool)
        result = tool.handler(ctx, db, args)
        output = result if isinstance(result, ToolOutput) else ToolOutput(data=result)
        return done("ok", _encode(output.data), ui=output.ui)
    except ToolError as exc:
        return done("error", str(exc), error="tool_error")
    except Exception:
        logger.exception("[Copilot] tool {} failed", name)
        return done("error", "The tool failed unexpectedly. Tell the user and do not retry.", error="internal")
    finally:
        if db is not None:
            db.close()
