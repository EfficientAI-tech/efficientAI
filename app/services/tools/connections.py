"""Tool connections: validation, encrypted secrets, tool discovery, providers and agent links."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import Agent, AgentToolConnection, ToolConnection
from app.services.tools.base import SIM_MODES, ToolProvider

CONNECTION_TYPE_MCP = "mcp"
CONNECTION_TYPE_HTTP = "http"
CONNECTION_TYPE_POSTGRES = "postgres"
CONNECTION_TYPES = (CONNECTION_TYPE_MCP, CONNECTION_TYPE_HTTP, CONNECTION_TYPE_POSTGRES)

# Secret keys per type: dicts of header / env values, or the Postgres DSN.
SECRET_FIELDS = {
    CONNECTION_TYPE_MCP: ("headers", "env"),
    CONNECTION_TYPE_HTTP: ("headers",),
    CONNECTION_TYPE_POSTGRES: ("dsn",),
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("_", (name or "").lower()).strip("_")[:40] or "tools"


def unique_slug(
    db: Session, *, workspace_id: UUID, name: str, exclude_id: Optional[UUID] = None
) -> str:
    base = slugify(name)
    slug, suffix = base, 2
    while True:
        query = db.query(ToolConnection.id).filter(
            ToolConnection.workspace_id == workspace_id, ToolConnection.slug == slug
        )
        if exclude_id is not None:
            query = query.filter(ToolConnection.id != exclude_id)
        if query.first() is None:
            return slug
        slug, suffix = f"{base}_{suffix}", suffix + 1


def encrypt_secrets(secrets: dict[str, Any]) -> Optional[str]:
    from app.core.encryption import encrypt_api_key

    cleaned = {k: v for k, v in (secrets or {}).items() if v not in (None, "", {})}
    return encrypt_api_key(json.dumps(cleaned)) if cleaned else None


def decrypt_secrets(connection: ToolConnection) -> dict[str, Any]:
    from app.core.encryption import decrypt_api_key

    if not connection.secrets:
        return {}
    return json.loads(decrypt_api_key(connection.secrets))


def secret_keys(connection: ToolConnection) -> list[str]:
    """Names of stored secrets (``headers.Authorization``, ``dsn``) — never the values."""
    try:
        secrets = decrypt_secrets(connection)
    except Exception:
        return []
    keys: list[str] = []
    for field, value in secrets.items():
        if isinstance(value, dict):
            keys.extend(f"{field}.{name}" for name in value)
        else:
            keys.append(field)
    return sorted(keys)


def merge_secrets(
    existing: dict[str, Any], updates: Optional[dict[str, Any]], connection_type: str
) -> dict[str, Any]:
    """Apply a secrets patch: dict fields merge per key (``""`` deletes), scalars replace."""
    if not updates:
        return existing
    allowed = SECRET_FIELDS[connection_type]
    merged = dict(existing)
    for field, value in updates.items():
        if field not in allowed:
            raise ValueError(f"Unknown secret field for {connection_type}: {field}")
        if isinstance(value, dict):
            current = dict(merged.get(field) or {})
            for key, item in value.items():
                if item in (None, ""):
                    current.pop(key, None)
                else:
                    current[str(key)] = str(item)
            merged[field] = current
        elif value in (None, ""):
            merged.pop(field, None)
        else:
            merged[field] = str(value)
    return merged


def validate_connection(connection_type: str, config: dict[str, Any], simulation_mode: str) -> None:
    from app.services.tools.providers.http import validate_http_tools
    from app.services.tools.providers.mcp import TRANSPORTS

    if connection_type not in CONNECTION_TYPES:
        raise ValueError(f"Unknown connection type: {connection_type}")
    if simulation_mode not in SIM_MODES:
        raise ValueError(f"Unknown simulation mode: {simulation_mode}")
    if connection_type == CONNECTION_TYPE_MCP:
        transport = config.get("transport") or "streamable_http"
        if transport not in TRANSPORTS:
            raise ValueError(f"Unknown MCP transport: {transport}")
        if transport == "stdio" and not (config.get("command") or "").strip():
            raise ValueError("stdio MCP servers need a command")
        if transport != "stdio" and not (config.get("url") or "").strip():
            raise ValueError("MCP server URL is required")
    elif connection_type == CONNECTION_TYPE_HTTP:
        validate_http_tools(config)


def build_provider(
    connection: ToolConnection,
    *,
    enabled_tools: Optional[list[str]] = None,
) -> Optional[ToolProvider]:
    """Provider for a connection's cached tools, or ``None`` if it has none yet."""
    from app.config import settings

    timeout = settings.TOOL_CALL_TIMEOUT_SECONDS
    secrets = decrypt_secrets(connection)
    common = dict(
        name=connection.name,
        prefix=connection.slug,
        config=dict(connection.config or {}),
        secrets=secrets,
        enabled_tools=enabled_tools,
        simulation_mode=connection.simulation_mode,
        timeout=timeout,
    )
    if connection.connection_type == CONNECTION_TYPE_HTTP:
        from app.services.tools.providers.http import HttpToolProvider

        return HttpToolProvider(**common)
    if connection.connection_type == CONNECTION_TYPE_POSTGRES:
        from app.services.tools.providers.postgres import PostgresToolProvider

        return PostgresToolProvider(**common)
    if not connection.cached_tools:
        return None
    from app.services.tools.providers.mcp import McpToolProvider

    return McpToolProvider(cached_tools=list(connection.cached_tools), **common)


def discover_tools(connection: ToolConnection) -> list[dict[str, Any]]:
    """Fetch the connection's tool list from its source, proving the credentials work."""
    from app.config import settings

    secrets = decrypt_secrets(connection)
    config = dict(connection.config or {})
    timeout = settings.TOOL_CALL_TIMEOUT_SECONDS
    if connection.connection_type == CONNECTION_TYPE_MCP:
        from app.services.tools.providers.mcp import discover_mcp_tools

        return discover_mcp_tools(config, secrets, timeout=timeout)
    if connection.connection_type == CONNECTION_TYPE_HTTP:
        from app.services.tools.providers.http import tool_entries_from_http_config

        return tool_entries_from_http_config(config)
    from app.services.tools.providers.postgres import (
        PostgresToolProvider,
        tool_entries_for_postgres,
    )

    if not secrets.get("dsn"):
        raise ValueError("Add a connection string (dsn)")
    provider = PostgresToolProvider(
        name=connection.name,
        prefix=connection.slug,
        config=config,
        secrets=secrets,
        timeout=timeout,
    )
    try:
        result = provider.call(f"{connection.slug}__list_tables", {})
    finally:
        provider.close()
    if result.is_error:
        raise ValueError(result.content)
    return tool_entries_for_postgres()


def refresh_connection_tools(db: Session, connection: ToolConnection) -> bool:
    """Run discovery and store the result; returns whether it succeeded."""
    try:
        tools = discover_tools(connection)
    except Exception as exc:
        connection.last_error = str(exc)[:2000] or exc.__class__.__name__
        connection.last_tested_at = datetime.now(timezone.utc)
        return False
    connection.cached_tools = tools
    connection.last_error = None
    connection.last_tested_at = datetime.now(timezone.utc)
    return True


def agent_tool_links(db: Session, *, agent_id: UUID) -> list[AgentToolConnection]:
    return db.query(AgentToolConnection).filter(AgentToolConnection.agent_id == agent_id).all()


def replace_agent_tool_connections(
    db: Session,
    *,
    agent: Agent,
    links: Iterable[dict[str, Any]],
) -> None:
    """``links``: ``[{"tool_connection_id": UUID, "enabled_tools": [..] | None}]``."""
    desired = {UUID(str(link["tool_connection_id"])): link.get("enabled_tools") for link in links}
    if desired:
        found = {
            row[0]
            for row in db.query(ToolConnection.id)
            .filter(
                ToolConnection.id.in_(desired),
                ToolConnection.organization_id == agent.organization_id,
                ToolConnection.workspace_id == agent.workspace_id,
            )
            .all()
        }
        missing = [str(cid) for cid in desired if cid not in found]
        if missing:
            raise ValueError(f"Tool connection(s) not found in workspace: {', '.join(missing)}")
    db.query(AgentToolConnection).filter(AgentToolConnection.agent_id == agent.id).delete()
    for connection_id, enabled_tools in desired.items():
        db.add(
            AgentToolConnection(
                agent_id=agent.id,
                tool_connection_id=connection_id,
                organization_id=agent.organization_id,
                workspace_id=agent.workspace_id,
                enabled_tools=list(enabled_tools) if enabled_tools is not None else None,
            )
        )


def agent_connection_providers(db: Session, *, agent: Any) -> list[ToolProvider]:
    """Providers for every tool connection attached to the agent."""
    from loguru import logger

    agent_id = getattr(agent, "id", None)
    if agent_id is None:
        return []
    rows = (
        db.query(AgentToolConnection, ToolConnection)
        .join(ToolConnection, ToolConnection.id == AgentToolConnection.tool_connection_id)
        .filter(AgentToolConnection.agent_id == agent_id)
        .all()
    )
    providers: list[ToolProvider] = []
    for link, connection in rows:
        try:
            provider = build_provider(connection, enabled_tools=link.enabled_tools)
        except Exception as exc:
            logger.warning("[Tools] Skipping connection {}: {}", connection.name, exc)
            continue
        if provider is not None:
            providers.append(provider)
    return providers


def connection_tool_views(connection: ToolConnection) -> list[dict[str, Any]]:
    """Cached tools with their exposed name and read/write classification."""
    from app.services.tools.base import classify_side_effect

    overrides = (connection.config or {}).get("tool_side_effects") or {}
    views = []
    for entry in connection.cached_tools or []:
        views.append(
            {
                "name": entry["name"],
                "exposed_name": f"{connection.slug}__{entry['name']}",
                "description": entry.get("description"),
                "input_schema": entry.get("input_schema"),
                "side_effect": overrides.get(entry["name"])
                or classify_side_effect(
                    entry["name"],
                    read_only_hint=entry.get("read_only_hint"),
                    destructive_hint=entry.get("destructive_hint"),
                ),
            }
        )
    return views
