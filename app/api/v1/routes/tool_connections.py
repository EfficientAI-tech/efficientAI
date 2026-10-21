"""Tool connections (MCP servers, HTTP tools, Postgres) and which agents use them."""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.api_rate_limit import enforce_resource_create_rate_limit
from app.core.auth import Principal
from app.dependencies import get_db, get_organization_id, get_workspace_id
from app.models.database import Agent, AgentToolConnection, ToolConnection
from app.models.schemas import (
    AgentToolCatalogEntry,
    AgentToolConnectionLink,
    AgentToolConnectionsUpdate,
    ToolConnectionCreate,
    ToolConnectionResponse,
    ToolConnectionUpdate,
)
from app.services.tools.connections import (
    CONNECTION_TYPE_MCP,
    agent_tool_links,
    connection_tool_views,
    decrypt_secrets,
    encrypt_secrets,
    merge_secrets,
    refresh_connection_tools,
    replace_agent_tool_connections,
    secret_keys,
    unique_slug,
    validate_connection,
)

router = APIRouter(prefix="/tool-connections", tags=["tool-connections"])


def _response(db: Session, connection: ToolConnection) -> ToolConnectionResponse:
    agent_count = (
        db.query(func.count(AgentToolConnection.agent_id))
        .filter(AgentToolConnection.tool_connection_id == connection.id)
        .scalar()
        or 0
    )
    return ToolConnectionResponse(
        id=connection.id,
        name=connection.name,
        slug=connection.slug,
        connection_type=connection.connection_type,
        preset=connection.preset,
        config=connection.config or {},
        simulation_mode=connection.simulation_mode,
        secret_keys=secret_keys(connection),
        tools=connection_tool_views(connection),
        last_tested_at=connection.last_tested_at,
        last_error=connection.last_error,
        agent_count=int(agent_count),
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _get_connection(
    db: Session, connection_id: UUID, organization_id: UUID, workspace_id: UUID
) -> ToolConnection:
    connection = (
        db.query(ToolConnection)
        .filter(
            ToolConnection.id == connection_id,
            ToolConnection.organization_id == organization_id,
            ToolConnection.workspace_id == workspace_id,
        )
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Tool connection not found")
    return connection


def _get_agent(db: Session, agent_id: UUID, organization_id: UUID, workspace_id: UUID) -> Agent:
    agent = (
        db.query(Agent)
        .filter(
            Agent.id == agent_id,
            Agent.organization_id == organization_id,
            Agent.workspace_id == workspace_id,
        )
        .first()
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _check_transport(connection_type: str, config: dict) -> None:
    if connection_type != CONNECTION_TYPE_MCP:
        return
    from app.services.tools.providers.mcp import McpConnectionError, assert_transport_allowed

    try:
        assert_transport_allowed(config)
    except McpConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=List[ToolConnectionResponse])
def list_tool_connections(
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ToolConnection)
        .filter(
            ToolConnection.organization_id == organization_id,
            ToolConnection.workspace_id == workspace_id,
        )
        .order_by(ToolConnection.created_at.desc())
        .all()
    )
    return [_response(db, row) for row in rows]


@router.post("", response_model=ToolConnectionResponse, status_code=status.HTTP_201_CREATED)
def create_tool_connection(
    payload: ToolConnectionCreate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
    principal: Principal = Depends(enforce_resource_create_rate_limit),
):
    """Create the connection and immediately discover its tools (errors land in ``last_error``)."""
    try:
        validate_connection(payload.connection_type, payload.config, payload.simulation_mode)
        secrets = merge_secrets({}, payload.secrets, payload.connection_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _check_transport(payload.connection_type, payload.config)
    connection = ToolConnection(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=payload.name.strip(),
        slug=unique_slug(db, workspace_id=workspace_id, name=payload.name),
        connection_type=payload.connection_type,
        preset=payload.preset,
        config=payload.config,
        secrets=encrypt_secrets(secrets),
        simulation_mode=payload.simulation_mode,
        created_by=getattr(principal, "user_id", None) and str(principal.user_id),
    )
    db.add(connection)
    db.flush()
    refresh_connection_tools(db, connection)
    db.commit()
    db.refresh(connection)
    return _response(db, connection)


@router.get("/{connection_id}", response_model=ToolConnectionResponse)
def get_tool_connection(
    connection_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    return _response(db, _get_connection(db, connection_id, organization_id, workspace_id))


@router.patch("/{connection_id}", response_model=ToolConnectionResponse)
def update_tool_connection(
    connection_id: UUID,
    payload: ToolConnectionUpdate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    connection = _get_connection(db, connection_id, organization_id, workspace_id)
    config = payload.config if payload.config is not None else dict(connection.config or {})
    mode = payload.simulation_mode or connection.simulation_mode
    try:
        validate_connection(connection.connection_type, config, mode)
        secrets = merge_secrets(
            decrypt_secrets(connection), payload.secrets, connection.connection_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _check_transport(connection.connection_type, config)
    if payload.name is not None:
        connection.name = payload.name.strip()
    connection.config = config
    connection.simulation_mode = mode
    connection.secrets = encrypt_secrets(secrets)
    # Endpoint, credentials or tool definitions may have changed: re-discover.
    if payload.config is not None or payload.secrets:
        refresh_connection_tools(db, connection)
    db.commit()
    db.refresh(connection)
    return _response(db, connection)


@router.post("/{connection_id}/test", response_model=ToolConnectionResponse)
def test_tool_connection(
    connection_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Reconnect, refresh the cached tool list and report any error."""
    connection = _get_connection(db, connection_id, organization_id, workspace_id)
    refresh_connection_tools(db, connection)
    db.commit()
    db.refresh(connection)
    return _response(db, connection)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool_connection(
    connection_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    connection = _get_connection(db, connection_id, organization_id, workspace_id)
    db.query(AgentToolConnection).filter(
        AgentToolConnection.tool_connection_id == connection.id
    ).delete()
    db.delete(connection)
    db.commit()


@router.get("/agents/{agent_id}/links", response_model=List[AgentToolConnectionLink])
def list_agent_tool_connections(
    agent_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    agent = _get_agent(db, agent_id, organization_id, workspace_id)
    return [
        AgentToolConnectionLink(
            tool_connection_id=link.tool_connection_id, enabled_tools=link.enabled_tools
        )
        for link in agent_tool_links(db, agent_id=agent.id)
    ]


@router.put("/agents/{agent_id}/links", response_model=List[AgentToolConnectionLink])
def update_agent_tool_connections(
    agent_id: UUID,
    payload: AgentToolConnectionsUpdate,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    agent = _get_agent(db, agent_id, organization_id, workspace_id)
    try:
        replace_agent_tool_connections(
            db, agent=agent, links=[link.model_dump() for link in payload.links]
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return payload.links


@router.get("/agents/{agent_id}/catalog", response_model=List[AgentToolCatalogEntry])
def agent_tool_catalog(
    agent_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """Every tool the agent's production side can call in a simulation, and whether it is mocked."""
    from app.services.tools.toolset import build_agent_toolset

    agent = _get_agent(db, agent_id, organization_id, workspace_id)
    toolset = build_agent_toolset(db, agent=agent, organization_id=organization_id)
    try:
        entries = []
        for name in toolset.tool_names:
            spec = toolset.spec(name)
            entries.append(
                AgentToolCatalogEntry(
                    name=name,
                    description=spec.description,
                    source=spec.provider,
                    side_effect=spec.side_effect,
                    simulation_behavior="mocked" if toolset.should_mock(name) else "live",
                )
            )
        return entries
    finally:
        toolset.close()
