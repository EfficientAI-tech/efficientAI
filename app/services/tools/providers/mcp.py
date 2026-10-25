"""MCP servers (Slack, Notion, Google Drive, ...) as a tool provider.

The tool list comes from the connection's cached ``tools/list`` result, so building a
toolset never touches the network. The server session opens on the first call and
stays open for the conversation; ``close()`` ends it.

The MCP client is async and its transports use anyio cancel scopes, which must be
entered and exited by the same task. ``McpSession`` therefore runs one long-lived
task on a private event loop thread that owns the session and serves requests from
a queue; sync callers wait on ``concurrent.futures.Future`` results.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from app.services.tools.base import (
    SIM_MODE_MOCK_WRITES,
    ToolResult,
    ToolSpec,
    classify_side_effect,
)

TRANSPORT_STREAMABLE_HTTP = "streamable_http"
TRANSPORT_SSE = "sse"
TRANSPORT_STDIO = "stdio"
TRANSPORTS = (TRANSPORT_STREAMABLE_HTTP, TRANSPORT_SSE, TRANSPORT_STDIO)

MAX_RESULT_CHARS = 12000


class McpConnectionError(RuntimeError):
    pass


def assert_transport_allowed(config: dict[str, Any]) -> None:
    from app.config import settings
    from app.services.telephony.recording_download import assert_outbound_http_url_safe

    transport = config.get("transport") or TRANSPORT_STREAMABLE_HTTP
    if transport not in TRANSPORTS:
        raise McpConnectionError(f"Unknown MCP transport: {transport}")
    if transport == TRANSPORT_STDIO:
        if not settings.TOOL_CONNECTIONS_ALLOW_STDIO:
            raise McpConnectionError(
                "stdio MCP servers are disabled on this deployment "
                "(set TOOL_CONNECTIONS_ALLOW_STDIO=true on self-hosted installs)"
            )
        if not (config.get("command") or "").strip():
            raise McpConnectionError("stdio MCP servers need a command")
        return
    url = (config.get("url") or "").strip()
    if not url:
        raise McpConnectionError("MCP server URL is required")
    try:
        assert_outbound_http_url_safe(url, allow_loopback=bool(settings.DEBUG))
    except Exception as exc:
        raise McpConnectionError(f"MCP server URL is not allowed: {exc}") from exc


async def _open_client_session(
    stack: AsyncExitStack,
    config: dict[str, Any],
    secrets: dict[str, Any],
    timeout: float,
):
    from mcp import ClientSession

    transport = config.get("transport") or TRANSPORT_STREAMABLE_HTTP
    headers = {**(config.get("headers") or {}), **(secrets.get("headers") or {})}
    if transport == TRANSPORT_STDIO:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=config["command"],
            args=list(config.get("args") or []),
            env={**(config.get("env") or {}), **(secrets.get("env") or {})} or None,
        )
        read, write = await stack.enter_async_context(stdio_client(params))
    elif transport == TRANSPORT_SSE:
        from mcp.client.sse import sse_client

        read, write = await stack.enter_async_context(
            sse_client(config["url"], headers=headers, timeout=timeout)
        )
    else:
        import httpx
        from mcp.client.streamable_http import streamable_http_client

        # Own client: the SDK default follows redirects, which would bypass the SSRF check.
        http_client = await stack.enter_async_context(
            httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False)
        )
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(config["url"], http_client=http_client)
        )
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


class McpSession:
    """A live MCP client session driven from synchronous code."""

    def __init__(self, config: dict[str, Any], secrets: dict[str, Any], *, timeout: float):
        self.timeout = timeout
        self._config = config
        self._secrets = secrets
        self._ready: concurrent.futures.Future = concurrent.futures.Future()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        self._thread = threading.Thread(target=self._run, name="mcp-session", daemon=True)
        self._thread.start()
        try:
            self._ready.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            self.close()
            raise McpConnectionError(f"MCP server did not respond within {timeout:.0f}s") from exc
        except Exception as exc:
            self.close()
            raise McpConnectionError(f"Could not connect to MCP server: {exc}") from exc

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        try:
            async with AsyncExitStack() as stack:
                session = await _open_client_session(
                    stack, self._config, self._secrets, self.timeout
                )
                self._ready.set_result(None)
                while True:
                    item = await self._queue.get()
                    if item is None:
                        break
                    fn, future = item
                    try:
                        future.set_result(await fn(session))
                    except Exception as exc:
                        future.set_exception(exc)
        except BaseException as exc:  # noqa: BLE001 - surface any startup failure to the caller
            if not self._ready.done():
                self._ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError(exc))
            else:
                logger.warning("[MCP] Session ended with error: {}", exc)

    def run(self, fn: Callable[[Any], Awaitable[Any]]) -> Any:
        if self._loop is None or self._queue is None or not self._thread.is_alive():
            raise McpConnectionError("MCP session is closed")
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (fn, future))
        try:
            return future.result(timeout=self.timeout)
        except concurrent.futures.TimeoutError as exc:
            raise McpConnectionError(f"MCP call timed out after {self.timeout:.0f}s") from exc

    def close(self) -> None:
        if self._loop is not None and self._queue is not None and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        self._thread.join(timeout=5)


def tool_entry_from_mcp(tool: Any) -> dict[str, Any]:
    """Serializable form of an ``mcp.types.Tool`` for ``ToolConnection.cached_tools``."""
    annotations = getattr(tool, "annotations", None)
    return {
        "name": tool.name,
        "description": tool.description or getattr(tool, "title", None) or tool.name,
        "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
        "read_only_hint": getattr(annotations, "readOnlyHint", None),
        "destructive_hint": getattr(annotations, "destructiveHint", None),
    }


def discover_mcp_tools(
    config: dict[str, Any], secrets: dict[str, Any], *, timeout: float
) -> list[dict[str, Any]]:
    """Connect, run ``tools/list`` (all pages) and disconnect."""
    assert_transport_allowed(config)

    async def _list(session) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = await session.list_tools(cursor=cursor)
            entries.extend(tool_entry_from_mcp(tool) for tool in page.tools)
            cursor = page.nextCursor
            if not cursor:
                return entries

    session = McpSession(config, secrets, timeout=timeout)
    try:
        return session.run(_list)
    finally:
        session.close()


def _result_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        kind = getattr(item, "type", None)
        if kind == "text":
            parts.append(item.text)
        elif kind == "resource":
            resource = getattr(item, "resource", None)
            parts.append(
                getattr(resource, "text", None) or f"[resource {getattr(resource, 'uri', '')}]"
            )
        else:
            parts.append(f"[{kind} content]")
    if not parts and getattr(result, "structuredContent", None) is not None:
        import json

        parts.append(json.dumps(result.structuredContent))
    text = "\n".join(parts).strip() or "(empty result)"
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "…"


class McpToolProvider:
    """Tools of one MCP connection, exposed as ``<prefix>__<tool>``."""

    def __init__(
        self,
        *,
        name: str,
        prefix: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
        cached_tools: list[dict[str, Any]],
        enabled_tools: Optional[list[str]] = None,
        simulation_mode: str = SIM_MODE_MOCK_WRITES,
        timeout: float = 30.0,
    ):
        self.name = name
        self.prefix = prefix
        self.config = config
        self.secrets = secrets
        self.simulation_mode = simulation_mode
        self.timeout = timeout
        overrides = config.get("tool_side_effects") or {}
        enabled = set(enabled_tools) if enabled_tools is not None else None
        self._tools: dict[str, dict[str, Any]] = {}
        self._specs: list[ToolSpec] = []
        for entry in cached_tools:
            if enabled is not None and entry["name"] not in enabled:
                continue
            exposed = f"{prefix}__{entry['name']}"
            self._tools[exposed] = entry
            self._specs.append(
                ToolSpec(
                    name=exposed,
                    description=entry.get("description") or entry["name"],
                    parameters=entry.get("input_schema") or {"type": "object", "properties": {}},
                    provider=name,
                    side_effect=overrides.get(entry["name"])
                    or classify_side_effect(
                        entry["name"],
                        read_only_hint=entry.get("read_only_hint"),
                        destructive_hint=entry.get("destructive_hint"),
                    ),
                )
            )
        self._session: Optional[McpSession] = None
        self._lock = threading.Lock()

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs)

    def _ensure_session(self) -> McpSession:
        with self._lock:
            if self._session is None:
                assert_transport_allowed(self.config)
                self._session = McpSession(self.config, self.secrets, timeout=self.timeout)
            return self._session

    def call(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        entry = self._tools.get(tool_name)
        if entry is None:
            return ToolResult(f"Unknown tool: {tool_name}", is_error=True)
        session = self._ensure_session()

        async def _call(client):
            return await client.call_tool(
                entry["name"],
                arguments,
                read_timeout_seconds=timedelta(seconds=self.timeout),
            )

        result = session.run(_call)
        return ToolResult(_result_text(result), is_error=bool(getattr(result, "isError", False)))

    def close(self) -> None:
        with self._lock:
            session, self._session = self._session, None
        if session is not None:
            session.close()
