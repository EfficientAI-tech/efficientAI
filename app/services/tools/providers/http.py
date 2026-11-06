"""User-defined HTTP endpoints as tools (a customer's own order / CRM / booking APIs).

Connection config::

    {"base_url": "https://api.example.com",
     "headers": {"Accept": "application/json"},
     "tools": [{"name": "get_order", "description": "Look up an order",
                "method": "GET", "path": "/orders/{order_id}",
                "parameters": {"type": "object",
                               "properties": {"order_id": {"type": "string"}},
                               "required": ["order_id"]},
                "side_effect": "read"}]}

Secrets: ``{"headers": {"Authorization": "Bearer ..."}}``. ``{placeholders}`` in the
path are filled from the arguments; the rest go in the query string for GET/DELETE
and in a JSON body otherwise.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.services.tools.base import (
    SIDE_EFFECT_READ,
    SIDE_EFFECT_WRITE,
    SIM_MODE_MOCK_WRITES,
    ToolResult,
    ToolSpec,
)

MAX_RESULT_CHARS = 12000
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_PLACEHOLDER_RE = re.compile(r"{([a-zA-Z0-9_]+)}")


def validate_http_tools(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized tool definitions; raises ``ValueError`` on bad config."""
    tools = config.get("tools") or []
    if not isinstance(tools, list) or not tools:
        raise ValueError("Define at least one HTTP tool")
    seen: set[str] = set()
    normalized = []
    for tool in tools:
        name = str(tool.get("name") or "").strip()
        if not _TOOL_NAME_RE.match(name):
            raise ValueError(f"Invalid tool name {name!r}: use letters, digits, _ or -")
        if name in seen:
            raise ValueError(f"Duplicate tool name {name!r}")
        seen.add(name)
        method = str(tool.get("method") or "GET").upper()
        if method not in HTTP_METHODS:
            raise ValueError(f"{name}: unsupported method {method}")
        if not (tool.get("path") or tool.get("url") or config.get("base_url")):
            raise ValueError(f"{name}: needs a path or URL")
        parameters = tool.get("parameters") or {"type": "object", "properties": {}}
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ValueError(f"{name}: parameters must be a JSON schema object")
        side_effect = tool.get("side_effect") or (
            SIDE_EFFECT_READ if method == "GET" else SIDE_EFFECT_WRITE
        )
        normalized.append(
            {
                "name": name,
                "description": str(tool.get("description") or name),
                "method": method,
                "path": tool.get("path") or "",
                "url": tool.get("url") or "",
                "parameters": parameters,
                "side_effect": side_effect,
            }
        )
    return normalized


def tool_entries_from_http_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    """``cached_tools`` entries, in the same shape MCP discovery produces."""
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"],
            "read_only_hint": tool["side_effect"] == SIDE_EFFECT_READ,
            "destructive_hint": None,
        }
        for tool in validate_http_tools(config)
    ]


class HttpToolProvider:
    def __init__(
        self,
        *,
        name: str,
        prefix: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
        enabled_tools: Optional[list[str]] = None,
        simulation_mode: str = SIM_MODE_MOCK_WRITES,
        timeout: float = 30.0,
    ):
        self.name = name
        self.simulation_mode = simulation_mode
        self.timeout = timeout
        self.base_url = (config.get("base_url") or "").rstrip("/")
        self.headers = {**(config.get("headers") or {}), **(secrets.get("headers") or {})}
        enabled = set(enabled_tools) if enabled_tools is not None else None
        self._tools = {
            f"{prefix}__{tool['name']}": tool
            for tool in validate_http_tools(config)
            if enabled is None or tool["name"] in enabled
        }

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=exposed,
                description=tool["description"],
                parameters=tool["parameters"],
                provider=self.name,
                side_effect=tool["side_effect"],
            )
            for exposed, tool in self._tools.items()
        ]

    def _build_request(self, tool: dict[str, Any], arguments: dict[str, Any]):
        remaining = dict(arguments)

        def _fill(match: re.Match) -> str:
            key = match.group(1)
            if key not in remaining:
                raise ValueError(f"Missing path argument: {key}")
            return quote(str(remaining.pop(key)), safe="")

        target = tool["url"] or f"{self.base_url}{tool['path']}"
        url = _PLACEHOLDER_RE.sub(_fill, target)
        if tool["method"] in ("GET", "DELETE"):
            return url, {k: v for k, v in remaining.items() if v is not None}, None
        return url, None, remaining

    def call(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        from app.config import settings
        from app.services.telephony.recording_download import assert_outbound_http_url_safe

        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(f"Unknown tool: {tool_name}", is_error=True)
        try:
            url, params, body = self._build_request(tool, arguments)
            assert_outbound_http_url_safe(url, allow_loopback=bool(settings.DEBUG))
        except Exception as exc:
            return ToolResult(f"Request not sent: {exc}", is_error=True)
        with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
            response = client.request(
                tool["method"], url, params=params, json=body, headers=self.headers
            )
        text = response.text
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "…"
        if response.status_code >= 400:
            return ToolResult(f"HTTP {response.status_code}: {text}", is_error=True)
        return ToolResult(
            text or f"HTTP {response.status_code}", extra={"http_status": response.status_code}
        )
